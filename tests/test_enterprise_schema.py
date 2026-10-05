"""Schema contract plus real PostgreSQL tests.

Set OPPILOT_TEST_DATABASE_URL to a disposable PostgreSQL database. Integration
fixtures use isolated schemas and roll back all changes; DATABASE_URL is ignored.
"""
import os
from pathlib import Path
import re
import uuid

import pytest

SCHEMA = (Path(__file__).resolve().parents[1] / 'db/schema.sql').read_text()
LEGACY = {'specialty', 'provider', 'appointment', 'performance', 'appointment_event'}
NEW = {'organization', 'region', 'practice', 'employee', 'provider_capacity',
       'staffing_daily', 'encounter', 'referral', 'payment', 'ground_truth_anomaly'}
TABLES = dict(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);', SCHEMA, re.S))


def test_table_contract_and_no_patient_fields():
    assert set(TABLES) == LEGACY | NEW
    # Exact column allowlist prevents accidental introduction of identifying or
    # clinical columns; patient_amount is an operational financial component.
    expected = {
        'specialty': 'specialty_id specialty_name',
        'provider': 'provider_id provider_name specialty_id clinic_name',
        'appointment': 'provider_id appointment_date available_slots booked_appointments no_shows',
        'performance': 'provider_id performance_date fte staffed_hours completed_visits realized_revenue',
        'appointment_event': 'appointment_id provider_id appointment_date appointment_status modeled_revenue practice_id appointment_type scheduled_at slot_duration_minutes payer_category',
        'organization': 'organization_id organization_name created_at',
        'region': 'region_id organization_id region_name region_code',
        'practice': 'practice_id region_id practice_name practice_code city state practice_type opening_date active',
        'employee': 'employee_id practice_id role fte hourly_cost hire_date termination_date status',
        'provider_capacity': 'provider_id capacity_date scheduled_hours clinical_hours available_slots blocked_slots pto_hours admin_hours',
        'staffing_daily': 'practice_id staff_date role budgeted_fte scheduled_fte actual_fte overtime_hours agency_hours absence_hours',
        'encounter': 'encounter_id appointment_id provider_id practice_id encounter_date visit_type work_rvu modeled_charge allowed_amount',
        'referral': 'referral_id practice_id specialty_id referral_date scheduled_date referral_source status',
        'payment': 'payment_id encounter_id payment_date payer_category allowed_amount paid_amount patient_amount adjustment_amount',
        'ground_truth_anomaly': 'anomaly_id practice_id start_date end_date anomaly_type affected_metric expected_direction severity description',
    }
    for name, columns in expected.items():
        actual = re.findall(r'^    (\w+) (?:BIGSERIAL|BIGINT|TEXT|DATE|TIMESTAMPTZ|BOOLEAN|NUMERIC|INTEGER)\b', TABLES[name], re.M)
        assert actual == columns.split(), name
    assert re.findall(r'ALTER TABLE provider ADD COLUMN IF NOT EXISTS (\w+)', SCHEMA) == ['practice_id']
    assert 'provider_id TEXT PRIMARY KEY' in TABLES['provider']
    assert 'clinic_name TEXT NOT NULL' in TABLES['provider']


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for real PostgreSQL constraint tests')
    import psycopg
    from psycopg import sql
    with psycopg.connect(url) as connection:
        schema_name = 'oppilot_test_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema_name)))
        try:
            yield connection
        finally:
            connection.rollback()


@pytest.fixture
def populated(db):
    db.execute(SCHEMA)
    db.execute("INSERT INTO organization (organization_id, organization_name) VALUES (1, 'Synthetic Org')")
    db.execute("INSERT INTO region VALUES (1, 1, 'Synthetic Region', 'R1')")
    db.execute("INSERT INTO practice VALUES (1, 1, 'Synthetic Practice', 'P1', 'Demo City', 'NY', 'ambulatory', '2021-01-01', true)")
    db.execute("INSERT INTO specialty VALUES (1, 'Primary Care')")
    db.execute("INSERT INTO provider (provider_id, provider_name, specialty_id, clinic_name) VALUES ('SYN-001', 'Fictional Provider', 1, 'North Clinic')")
    db.execute("INSERT INTO appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) VALUES (1, 'SYN-001', '2025-01-02', 'completed', 100)")
    db.execute("INSERT INTO employee VALUES (1, 1, 'scheduler', 1, 20, '2021-01-01', NULL, 'active')")
    db.execute("INSERT INTO provider_capacity VALUES ('SYN-001', '2025-01-02', 8, 6, 20, 2, 0, 2)")
    db.execute("INSERT INTO staffing_daily VALUES (1, '2025-01-02', 'scheduler', 2, 2, 2, 0, 0, 0)")
    db.execute("INSERT INTO encounter VALUES (1, 1, 'SYN-001', 1, '2025-01-02', 'office', 1, 100, 80)")
    db.execute("INSERT INTO referral VALUES (1, 1, 1, '2025-01-01', '2025-01-02', 'synthetic_internal', 'scheduled')")
    db.execute("INSERT INTO payment VALUES (1, 1, '2025-01-03', 'commercial', 80, 60, 20, 20)")
    db.execute("INSERT INTO ground_truth_anomaly VALUES (1, 1, '2025-01-01', '2025-01-31', 'capacity_drop', 'available_slots', 'decrease', 'high', 'Synthetic capacity reduction')")
    return db


def test_legacy_upgrade_preserves_rows_and_is_repeatable(db):
    # Recreate the exact pre-Phase-1A five-table structure: no new FK column.
    legacy_schema = '\n'.join(f'CREATE TABLE IF NOT EXISTS {t} ({TABLES[t]}\n);'
                              for t in ('specialty', 'provider', 'appointment', 'performance'))
    legacy_schema += "\nCREATE TABLE appointment_event (appointment_id BIGINT PRIMARY KEY, provider_id TEXT NOT NULL REFERENCES provider(provider_id), appointment_date DATE NOT NULL, appointment_status TEXT NOT NULL CHECK (appointment_status IN ('completed', 'no_show', 'cancelled')), modeled_revenue NUMERIC(12,2) NOT NULL CHECK (modeled_revenue >= 0));"
    db.execute(legacy_schema)
    db.execute("INSERT INTO specialty VALUES (1, 'Primary Care')")
    db.execute("INSERT INTO provider VALUES ('SYN-001', 'Fictional Provider', 1, 'North Clinic')")
    db.execute("INSERT INTO appointment VALUES ('SYN-001', '2025-01-02', 10, 8, 1)")
    db.execute("INSERT INTO performance VALUES ('SYN-001', '2025-01-02', 1, 8, 7, 700)")
    for i, status in enumerate(('completed', 'no_show', 'cancelled'), 1):
        db.execute('INSERT INTO appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) VALUES (%s, %s, %s, %s, 0)', (i, 'SYN-001', '2025-01-02', status))
    before = {t: db.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() for t in LEGACY}
    db.execute(SCHEMA)
    db.execute(SCHEMA)
    for t in LEGACY - {'provider', 'appointment_event'}:
        assert db.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() == before[t]
    assert db.execute('SELECT appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue FROM appointment_event ORDER BY appointment_id').fetchall() == before['appointment_event']
    assert db.execute('SELECT provider_id, provider_name, specialty_id, clinic_name FROM provider').fetchall() == before['provider']
    assert db.execute('SELECT practice_id FROM provider').fetchone() == (None,)
    # Execute the same explicit-column legacy upsert used by the loader.
    db.execute("""INSERT INTO provider (provider_id, provider_name, specialty_id, clinic_name)
        VALUES ('SYN-001', 'Fictional Provider', 1, 'North Clinic') ON CONFLICT (provider_id)
        DO UPDATE SET clinic_name = EXCLUDED.clinic_name""")
    from src.postgres_analytics import BASE_FROM
    assert db.execute('SELECT p.provider_id, p.clinic_name, a.available_slots, pe.completed_visits, pe.realized_revenue ' + BASE_FROM).fetchone() == ('SYN-001', 'North Clinic', 10, 7, 700)


def test_fresh_schema_optional_practice_and_indexes(populated):
    db = populated
    db.execute(SCHEMA)
    assert db.execute('SELECT provider_id, clinic_name, practice_id FROM provider').fetchone() == ('SYN-001', 'North Clinic', None)
    db.execute("UPDATE provider SET practice_id = 1 WHERE provider_id = 'SYN-001'")
    db.execute(SCHEMA)
    db.execute("""INSERT INTO provider (provider_id, provider_name, specialty_id, clinic_name)
        VALUES ('SYN-001', 'Fictional Provider', 1, 'North Clinic') ON CONFLICT (provider_id)
        DO UPDATE SET clinic_name = EXCLUDED.clinic_name""")
    assert db.execute('SELECT practice_id FROM provider').fetchone() == (1,)
    tables = {r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")}
    assert tables == LEGACY | NEW
    indexes = ' '.join(r[0] for r in db.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema()"))
    for columns in ('organization_id, region_code', 'region_id, practice_code', 'practice_id',
                    'provider_id, capacity_date', 'practice_id, staff_date, role',
                    'practice_id, encounter_date', 'practice_id, referral_date',
                    'encounter_id, payment_date', 'practice_id, start_date, end_date'):
        assert '(' + columns + ')' in indexes


NONNEGATIVE = {
    'employee': 'fte hourly_cost',
    'provider_capacity': 'scheduled_hours clinical_hours available_slots blocked_slots pto_hours admin_hours',
    'staffing_daily': 'budgeted_fte scheduled_fte actual_fte overtime_hours agency_hours absence_hours',
    'encounter': 'work_rvu modeled_charge allowed_amount',
    'payment': 'allowed_amount paid_amount patient_amount adjustment_amount',
}


@pytest.mark.parametrize('table,column', [(t, c) for t, columns in NONNEGATIVE.items() for c in columns.split()])
def test_negative_operational_values_rejected_and_zero_allowed(populated, table, column):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation), populated.transaction():
        populated.execute(f'UPDATE {table} SET {column} = -1')
    populated.execute(f'UPDATE {table} SET {column} = 0')
    if column not in ('available_slots', 'blocked_slots'):
        with pytest.raises(psycopg.errors.CheckViolation), populated.transaction():
            populated.execute(f"UPDATE {table} SET {column} = 'NaN'")


FOREIGN_KEYS = [
    ('region', 'organization_id', 'organization', 'organization_id'),
    ('practice', 'region_id', 'region', 'region_id'),
    ('provider', 'practice_id', 'practice', 'practice_id'),
    ('employee', 'practice_id', 'practice', 'practice_id'),
    ('provider_capacity', 'provider_id', 'provider', 'provider_id'),
    ('staffing_daily', 'practice_id', 'practice', 'practice_id'),
    ('encounter', 'appointment_id', 'appointment_event', 'appointment_id'),
    ('encounter', 'provider_id', 'provider', 'provider_id'),
    ('encounter', 'practice_id', 'practice', 'practice_id'),
    ('referral', 'practice_id', 'practice', 'practice_id'),
    ('referral', 'specialty_id', 'specialty', 'specialty_id'),
    ('payment', 'encounter_id', 'encounter', 'encounter_id'),
    ('ground_truth_anomaly', 'practice_id', 'practice', 'practice_id'),
]


@pytest.mark.parametrize('table,column,parent,key', FOREIGN_KEYS)
def test_foreign_keys_reject_orphans(populated, table, column, parent, key):
    import psycopg
    constraints = ' '.join(row[0] for row in populated.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'", (table,)))
    assert f'FOREIGN KEY ({column}) REFERENCES {parent}({key})' in constraints
    value = 'SYN-MISSING' if column == 'provider_id' else 999999
    with pytest.raises(psycopg.errors.ForeignKeyViolation), populated.transaction():
        populated.execute(f'UPDATE {table} SET {column} = %s', (value,))


@pytest.mark.parametrize('statement', [
    "UPDATE employee SET termination_date = '2020-12-31', status = 'terminated'",
    "UPDATE employee SET status = 'terminated'",
    "UPDATE employee SET status = 'unknown'",
    "UPDATE referral SET scheduled_date = '2020-12-31'",
    "UPDATE referral SET status = 'unknown'",
    "UPDATE referral SET scheduled_date = NULL",
    "UPDATE ground_truth_anomaly SET end_date = '2020-12-31'",
    "UPDATE ground_truth_anomaly SET severity = 'unknown'",
    "UPDATE ground_truth_anomaly SET expected_direction = 'unknown'",
])
def test_invalid_dates_and_categories_rejected(populated, statement):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation), populated.transaction():
        populated.execute(statement)


def test_boundary_dates_and_valid_categories(populated):
    db = populated
    db.execute("UPDATE employee SET termination_date = hire_date, status = 'terminated'")
    db.execute("UPDATE employee SET termination_date = NULL, status = 'on_leave'")
    db.execute("UPDATE referral SET scheduled_date = referral_date")
    for status in ('received', 'scheduled', 'completed', 'expired', 'lost',
                   'pending', 'cancelled', 'declined'):
        db.execute('UPDATE referral SET status = %s', (status,))
    db.execute('UPDATE ground_truth_anomaly SET end_date = start_date')
    for severity in ('low', 'medium', 'high'):
        for direction in ('increase', 'decrease'):
            db.execute('UPDATE ground_truth_anomaly SET severity = %s, expected_direction = %s', (severity, direction))


def test_appointment_status_compatibility_and_expansion(populated):
    import psycopg
    for status in ('completed', 'no_show', 'cancelled', 'cancelled_patient', 'cancelled_provider', 'cancelled_practice', 'rescheduled'):
        populated.execute('UPDATE appointment_event SET appointment_status = %s', (status,))
    for status in ('unknown',):
        with pytest.raises(psycopg.errors.CheckViolation), populated.transaction():
            populated.execute('UPDATE appointment_event SET appointment_status = %s', (status,))
    doc = (Path(__file__).resolve().parents[1] / 'docs/architecture/enterprise-data-model.md').read_text()
    for status in ('completed', 'no_show', 'cancelled', 'cancelled_patient', 'cancelled_provider', 'cancelled_practice', 'rescheduled'):
        assert f'`{status}`' in doc


@pytest.mark.parametrize('statement', [
    "INSERT INTO organization (organization_id, organization_name) VALUES (2, 'Synthetic Org')",
    "INSERT INTO region (region_id, organization_id, region_name, region_code) VALUES (2, 1, 'Other', 'R1')",
    "INSERT INTO practice (practice_id, region_id, practice_name, practice_code, city, state, practice_type, opening_date) VALUES (2, 1, 'Other', 'P1', 'Demo', 'NY', 'ambulatory', '2021-01-01')",
    "INSERT INTO provider_capacity SELECT * FROM provider_capacity",
    "INSERT INTO staffing_daily SELECT * FROM staffing_daily",
    "INSERT INTO encounter SELECT 3, appointment_id, provider_id, practice_id, encounter_date, visit_type, work_rvu, modeled_charge, allowed_amount FROM encounter",
])
def test_duplicate_grains_rejected(populated, statement):
    import psycopg
    with pytest.raises(psycopg.errors.UniqueViolation), populated.transaction():
        populated.execute(statement)


def test_required_relationship_cannot_be_null(populated):
    import psycopg
    with pytest.raises(psycopg.errors.NotNullViolation), populated.transaction():
        populated.execute('UPDATE practice SET region_id = NULL')
    # Optional walk-in encounter linkage is supported.
    populated.execute('UPDATE encounter SET appointment_id = NULL')
