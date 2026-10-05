"""Bulk COPY staging and atomic, insert-only loading of synthetic operations."""
from datetime import date
from decimal import Decimal
import uuid

from src.enterprise_reference import generate_enterprise_reference_data
from src.enterprise_operations import START_DATE, END_DATE, FIELDS, validate_enterprise_operations

KEYS = {'employee': ('employee_id',), 'provider_capacity': ('provider_id', 'capacity_date'),
        'staffing_daily': ('practice_id', 'staff_date', 'role')}


class OperationsConflict(ValueError):
    """A fixture key or reference identity conflicts with stored data."""


def _check_references(connection, reference):
    expected_practices = set()
    regions = {r['region_id']: r for r in reference['region']}
    for p in reference['practice']:
        r = regions[p['region_id']]
        expected_practices.add((p['practice_id'], p['practice_name'], p['practice_code'], p['city'], p['state'],
                               p['practice_type'], date.fromisoformat(p['opening_date']), p['active'],
                               r['region_id'], r['region_name'], r['region_code'], r['organization_id'],
                               reference['organization'][0]['organization_name']))
    actual = set(connection.execute('''SELECT p.practice_id, p.practice_name, p.practice_code, p.city, p.state,
        p.practice_type, p.opening_date, p.active, r.region_id, r.region_name, r.region_code,
        o.organization_id, o.organization_name FROM practice p JOIN region r USING (region_id)
        JOIN organization o USING (organization_id)''').fetchall())
    if not expected_practices <= actual:
        raise OperationsConflict('Load matching Phase 1B practice hierarchy before operations')
    specialties = {s['specialty_id']: s['specialty_name'] for s in reference['specialty']}
    expected_providers = {(p['provider_id'], p['provider_name'], specialties[p['specialty_id']], p['clinic_name'], p['practice_id'])
                          for p in reference['provider']}
    actual = set(connection.execute('''SELECT p.provider_id, p.provider_name, s.specialty_name, p.clinic_name, p.practice_id
        FROM provider p JOIN specialty s USING (specialty_id)''').fetchall())
    if not expected_providers <= actual:
        raise OperationsConflict('Load matching Phase 1B providers before operations')


def _copy_rows(cursor, stage, table, rows):
    from psycopg import sql
    columns = FIELDS[table]
    with cursor.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(
            sql.Identifier('pg_temp', stage), sql.SQL(', ').join(map(sql.Identifier, columns)))) as copy:
        for row in rows:
            # Avoid binary floating-point differences against NUMERIC values.
            copy.write_row(tuple(Decimal(str(row[c])) if type(row[c]) is float else row[c] for c in columns))


def _advance_employee_sequence(connection):
    from psycopg import sql
    sequence = connection.execute('''SELECT n.nspname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.oid = pg_get_serial_sequence('employee', 'employee_id')::regclass''').fetchone()
    if sequence is None:
        raise OperationsConflict('Missing employee serial sequence')
    name = sql.Identifier(*sequence)
    last, called = connection.execute(sql.SQL('SELECT last_value, is_called FROM {}').format(name)).fetchone()
    maximum = connection.execute('SELECT MAX(employee_id) FROM employee').fetchone()[0]
    if maximum is not None and (last + 1 if called else last) <= maximum:
        connection.execute(sql.SQL('ALTER SEQUENCE {} RESTART WITH {}').format(name, sql.Literal(maximum + 1)))


def load_enterprise_operations(connection, data, start=START_DATE, end=END_DATE):
    """Load matching rows once; reject any differing existing key without updates.

    Inside an existing transaction this owns a savepoint, not the outer commit.
    Phase 1B references must already exist. No reference or legacy fact writes.
    """
    from psycopg import sql
    reference = generate_enterprise_reference_data()
    validate_enterprise_operations(data, reference, start, end)
    inserted = {}
    with connection.transaction():
        # Coordinate with the Phase 1B loader and prevent concurrent remapping.
        connection.execute('LOCK TABLE organization, region, practice, specialty, provider IN SHARE MODE')
        connection.execute('LOCK TABLE employee, provider_capacity, staffing_daily IN SHARE ROW EXCLUSIVE MODE')
        _check_references(connection, reference)
        for table, columns in FIELDS.items():
            stage = 'op_stage_' + uuid.uuid4().hex
            connection.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE {} INCLUDING CONSTRAINTS) ON COMMIT DROP').format(
                sql.Identifier(stage), sql.Identifier(table)))
            with connection.cursor() as cursor:
                _copy_rows(cursor, stage, table, data[table])
            join = sql.SQL(' AND ').join(sql.SQL('t.{} = s.{}').format(sql.Identifier(k), sql.Identifier(k)) for k in KEYS[table])
            target_values = sql.SQL(', ').join(sql.SQL('t.{}').format(sql.Identifier(c)) for c in columns)
            staged_values = sql.SQL(', ').join(sql.SQL('s.{}').format(sql.Identifier(c)) for c in columns)
            conflict = connection.execute(sql.SQL('''SELECT 1 FROM {} t JOIN {} s ON {}
                WHERE ROW({}) IS DISTINCT FROM ROW({}) LIMIT 1''').format(
                sql.Identifier(table), sql.Identifier('pg_temp', stage), join, target_values, staged_values)).fetchone()
            if conflict:
                raise OperationsConflict(f'Conflicting {table} row; no existing values were overwritten')
            result = connection.execute(sql.SQL('''INSERT INTO {} ({}) SELECT {} FROM {} s
                WHERE NOT EXISTS (SELECT 1 FROM {} t WHERE {})''').format(
                sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)), staged_values,
                sql.Identifier('pg_temp', stage), sql.Identifier(table), join))
            inserted[table] = result.rowcount
            connection.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier('pg_temp', stage)))
        _advance_employee_sequence(connection)
    return {'rows': {table: len(rows) for table, rows in data.items()}, 'inserted': inserted}
