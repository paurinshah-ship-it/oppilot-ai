"""Transactional loading for Phase 1E encounter and payment fixtures."""
from decimal import Decimal
import uuid

from src.enterprise_finance import FIELDS, generate_enterprise_finance, validate_enterprise_finance

KEYS = {'encounter': ('encounter_id',), 'payment': ('payment_id',)}


class FinanceConflict(ValueError):
    """Stored encounter/payment rows conflict with the generated fixture."""


def _as_value(value):
    return Decimal(str(value)) if type(value) is float else value


def _copy_rows(cursor, stage, table, rows):
    from psycopg import sql
    columns = FIELDS[table]
    with cursor.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(
            sql.Identifier('pg_temp', stage), sql.SQL(', ').join(map(sql.Identifier, columns)))) as copy:
        for row in rows:
            copy.write_row(tuple(_as_value(row[column]) for column in columns))


def _check_appointments(connection, stage):
    mismatch = connection.execute(f'''SELECT 1 FROM pg_temp.{stage} e
        JOIN appointment_event a USING (appointment_id)
        WHERE a.appointment_status <> 'completed'
           OR a.provider_id <> e.provider_id
           OR a.practice_id IS DISTINCT FROM e.practice_id
           OR a.appointment_date <> e.encounter_date
        LIMIT 1''').fetchone()
    if mismatch:
        raise FinanceConflict('Encounters must match completed appointment events')
    missing = connection.execute(f'''SELECT 1 FROM pg_temp.{stage} e
        WHERE NOT EXISTS (SELECT 1 FROM appointment_event a
                          WHERE a.appointment_id = e.appointment_id
                            AND a.appointment_status = 'completed')
        LIMIT 1''').fetchone()
    if missing:
        raise FinanceConflict('Load matching Phase 1D appointment events before finance rows')


def load_enterprise_finance(connection, data=None, count=1_000_000, seed=42,
                            reference=None, start=None, end=None):
    """Insert matching encounter/payment rows once; reject conflicts."""
    from psycopg import sql
    from src.enterprise_appointments import START_DATE, END_DATE
    start = START_DATE if start is None else start
    end = END_DATE if end is None else end
    data = generate_enterprise_finance(count, seed, reference, start, end) if data is None else data
    validate_enterprise_finance(data, reference)
    inserted = {}
    with connection.transaction():
        connection.execute('LOCK TABLE appointment_event, encounter, payment IN SHARE ROW EXCLUSIVE MODE')
        stages = {}
        for table in ('encounter', 'payment'):
            stage = 'finance_stage_' + table + '_' + uuid.uuid4().hex
            stages[table] = stage
            connection.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE {} INCLUDING CONSTRAINTS) ON COMMIT DROP').format(
                sql.Identifier(stage), sql.Identifier(table)))
            with connection.cursor() as cursor:
                _copy_rows(cursor, stage, table, data[table])
        _check_appointments(connection, stages['encounter'])
        staged_encounters = set(connection.execute(sql.SQL('SELECT encounter_id FROM {}').format(
            sql.Identifier('pg_temp', stages['encounter']))).fetchall())
        payment_orphans = connection.execute(sql.SQL('''SELECT 1 FROM {} p
            WHERE NOT EXISTS (SELECT 1 FROM {} e WHERE e.encounter_id = p.encounter_id)
            LIMIT 1''').format(sql.Identifier('pg_temp', stages['payment']),
                               sql.Identifier('pg_temp', stages['encounter']))).fetchone()
        if payment_orphans or len(staged_encounters) != len(data['encounter']):
            raise FinanceConflict('Payments must reference staged encounters one-to-one')
        for table in ('encounter', 'payment'):
            columns = FIELDS[table]
            stage = stages[table]
            join = sql.SQL(' AND ').join(sql.SQL('t.{} = s.{}').format(sql.Identifier(k), sql.Identifier(k)) for k in KEYS[table])
            target_values = sql.SQL(', ').join(sql.SQL('t.{}').format(sql.Identifier(c)) for c in columns)
            staged_values = sql.SQL(', ').join(sql.SQL('s.{}').format(sql.Identifier(c)) for c in columns)
            conflict = connection.execute(sql.SQL('''SELECT 1 FROM {} t JOIN {} s ON {}
                WHERE ROW({}) IS DISTINCT FROM ROW({}) LIMIT 1''').format(
                sql.Identifier(table), sql.Identifier('pg_temp', stage), join,
                target_values, staged_values)).fetchone()
            if conflict:
                raise FinanceConflict(f'Conflicting {table} row; no existing values were overwritten')
            result = connection.execute(sql.SQL('''INSERT INTO {} ({}) SELECT {} FROM {} s
                WHERE NOT EXISTS (SELECT 1 FROM {} t WHERE {})''').format(
                sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)), staged_values,
                sql.Identifier('pg_temp', stage), sql.Identifier(table), join))
            inserted[table] = result.rowcount
            connection.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier('pg_temp', stage)))
    return {'rows': {table: len(rows) for table, rows in data.items()}, 'inserted': inserted}
