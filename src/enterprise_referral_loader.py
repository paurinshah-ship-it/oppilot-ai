"""Transactional loading for Phase 1E referral-demand fixtures."""
from datetime import date
import uuid

from src.enterprise_referrals import FIELDS, generate_referrals, validate_referrals


class ReferralConflict(ValueError):
    """Stored referral rows conflict with the generated fixture."""


def _copy_rows(cursor, stage, rows):
    from psycopg import sql
    with cursor.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(
            sql.Identifier('pg_temp', stage), sql.SQL(', ').join(map(sql.Identifier, FIELDS)))) as copy:
        for row in rows:
            copy.write_row(tuple(row[column] for column in FIELDS))


def _verify_references(connection, reference):
    practices = {p['practice_id'] for p in reference['practice']}
    specialties = {s['specialty_id'] for s in reference['specialty']}
    actual_practices = {row[0] for row in connection.execute('SELECT practice_id FROM practice')}
    actual_specialties = {row[0] for row in connection.execute('SELECT specialty_id FROM specialty')}
    if not practices <= actual_practices or not specialties <= actual_specialties:
        raise ReferralConflict('Load matching Phase 1B reference data before referrals')


def load_enterprise_referrals(connection, rows=None, count=50_000, seed=42,
                              reference=None, start=None, end=None):
    from psycopg import sql
    from src.enterprise_operations import START_DATE, END_DATE
    from src.enterprise_reference import generate_enterprise_reference_data
    reference = generate_enterprise_reference_data() if reference is None else reference
    start = START_DATE if start is None else start
    end = END_DATE if end is None else end
    rows = generate_referrals(count, seed, reference, start, end) if rows is None else rows
    validate_referrals(rows, reference, start, end)
    inserted = 0
    with connection.transaction():
        connection.execute('LOCK TABLE practice, specialty IN SHARE MODE')
        connection.execute('LOCK TABLE referral IN SHARE ROW EXCLUSIVE MODE')
        _verify_references(connection, reference)
        stage = 'referral_stage_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE referral INCLUDING CONSTRAINTS) ON COMMIT DROP').format(sql.Identifier(stage)))
        with connection.cursor() as cursor:
            _copy_rows(cursor, stage, rows)
        columns = FIELDS
        join = sql.SQL('t.referral_id = s.referral_id')
        target_values = sql.SQL(', ').join(sql.SQL('t.{}').format(sql.Identifier(c)) for c in columns)
        staged_values = sql.SQL(', ').join(sql.SQL('s.{}').format(sql.Identifier(c)) for c in columns)
        conflict = connection.execute(sql.SQL('''SELECT 1 FROM referral t JOIN {} s ON {}
            WHERE ROW({}) IS DISTINCT FROM ROW({}) LIMIT 1''').format(
            sql.Identifier('pg_temp', stage), join, target_values, staged_values)).fetchone()
        if conflict:
            raise ReferralConflict('Conflicting referral row; no existing values were overwritten')
        result = connection.execute(sql.SQL('''INSERT INTO referral ({}) SELECT {} FROM {} s
            WHERE NOT EXISTS (SELECT 1 FROM referral t WHERE {})''').format(
            sql.SQL(', ').join(map(sql.Identifier, columns)), staged_values,
            sql.Identifier('pg_temp', stage), join))
        inserted = result.rowcount
        connection.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier('pg_temp', stage)))
    return {'rows': len(rows), 'inserted': inserted}
