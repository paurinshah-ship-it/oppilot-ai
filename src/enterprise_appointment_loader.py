"""Atomic PostgreSQL COPY staging and insert-only loading for enterprise events."""
from decimal import Decimal
import uuid

from src.enterprise_appointments import (FIELDS, MIN_APPOINTMENT_ID, _reference_maps,
    _validate_row, generate_appointment_events)
from src.enterprise_reference import generate_enterprise_reference_data
from src.scalable_analytics import NO_SHOW_DENOMINATOR_STATUSES


class AppointmentEventConflict(ValueError):
    """Stored reference or event identity conflicts with the synthetic fixture."""


def _verify_reference(connection, reference):
    provider_rows = connection.execute('''SELECT p.provider_id, p.provider_name, s.specialty_name,
        p.clinic_name, p.practice_id FROM provider p JOIN specialty s USING (specialty_id)''').fetchall()
    actual = {row[0]: row for row in provider_rows}
    specialties = {s['specialty_id']: s['specialty_name'] for s in reference['specialty']}
    for p in reference['provider']:
        expected = (p['provider_id'], p['provider_name'], specialties[p['specialty_id']], p['clinic_name'], p['practice_id'])
        if actual.get(p['provider_id']) != expected:
            raise AppointmentEventConflict('Load matching Phase 1B providers before appointment events')


def _as_values(row):
    return tuple(Decimal(str(row[k])) if type(row[k]) is float else row[k] for k in FIELDS)


def load_appointment_events(connection, count=1_000_000, seed=42, reference=None,
                            start=None, end=None):
    """COPY-stage events and insert missing rows in one transaction/savepoint.

    Legacy IDs 1–1,000,000 remain untouched; enterprise fixture IDs begin above
    that range. Matching reruns insert nothing; changed existing rows abort.
    """
    from psycopg import sql
    from src.enterprise_appointments import START_DATE, END_DATE, _business_dates
    reference = generate_enterprise_reference_data() if reference is None else reference
    start = START_DATE if start is None else start
    end = END_DATE if end is None else end
    # Validate the interval before acquiring table locks.
    _business_dates(start, end)
    providers, provider_lookup, _, _ = _reference_maps(reference)
    if not providers:
        raise ValueError('At least one enterprise provider is required')
    inserted = 0
    count_by_status = {}
    with connection.transaction():
        connection.execute('LOCK TABLE organization, region, practice, specialty, provider IN SHARE MODE')
        connection.execute('LOCK TABLE appointment_event IN SHARE ROW EXCLUSIVE MODE')
        _verify_reference(connection, reference)
        stage = 'event_stage_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE appointment_event INCLUDING CONSTRAINTS) ON COMMIT DROP').format(sql.Identifier(stage)))
        with connection.cursor() as cursor:
            statement = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier('pg_temp', stage), sql.SQL(', ').join(map(sql.Identifier, FIELDS)))
            expected = MIN_APPOINTMENT_ID
            with cursor.copy(statement) as copy:
                for row in generate_appointment_events(count=count, seed=seed, reference=reference, start=start, end=end):
                    try:
                        _validate_row(row, reference, expected, provider_lookup)
                    except (TypeError, ValueError) as exc:
                        raise AppointmentEventConflict(str(exc)) from exc
                    expected += 1
                    count_by_status[row['appointment_status']] = count_by_status.get(row['appointment_status'], 0) + 1
                    copy.write_row(_as_values(row))
        comparison = sql.SQL(', ').join(sql.SQL('t.{}').format(sql.Identifier(c)) for c in FIELDS)
        staged = sql.SQL(', ').join(sql.SQL('s.{}').format(sql.Identifier(c)) for c in FIELDS)
        join = sql.SQL('t.appointment_id = s.appointment_id')
        conflict = connection.execute(sql.SQL('''SELECT 1 FROM appointment_event t JOIN {} s ON {}
            WHERE ROW({}) IS DISTINCT FROM ROW({}) LIMIT 1''').format(
            sql.Identifier('pg_temp', stage), join, comparison, staged)).fetchone()
        if conflict:
            raise AppointmentEventConflict('Existing appointment event differs from generated fixture')
        result = connection.execute(sql.SQL('''INSERT INTO appointment_event ({}) SELECT {} FROM {} s
            WHERE NOT EXISTS (SELECT 1 FROM appointment_event t WHERE {})''').format(
            sql.SQL(', ').join(map(sql.Identifier, FIELDS)), staged, sql.Identifier('pg_temp', stage), join))
        inserted = result.rowcount
        connection.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier('pg_temp', stage)))
    return {'count': count, 'inserted': inserted, 'status_counts': count_by_status,
            'no_show_denominator_statuses': NO_SHOW_DENOMINATOR_STATUSES}
