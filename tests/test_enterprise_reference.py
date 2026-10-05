"""Phase 1B generation and PostgreSQL reference loading regression coverage."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import uuid

import pytest

from src.data import generate_data, legacy_provider_records, load_data
from src.enterprise_reference import generate_enterprise_reference_data, validate_enterprise_reference_data
from src.enterprise_reference_loader import ReferenceDataConflict, load_enterprise_reference_data

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TABLES = ('organization', 'region', 'practice', 'specialty', 'provider')
FACT_TABLES = ('appointment', 'performance', 'appointment_event', 'employee', 'provider_capacity',
               'staffing_daily', 'encounter', 'referral', 'payment', 'ground_truth_anomaly')


def test_deterministic_output_and_no_global_random_side_effects():
    state = random.getstate()
    first = generate_enterprise_reference_data()
    assert random.getstate() == state
    assert first == generate_enterprise_reference_data()
    first['provider'][0]['clinic_name'] = 'changed'
    assert generate_enterprise_reference_data()['provider'][0]['clinic_name'] == 'North Clinic'


def test_counts_stable_ids_and_region_distribution():
    data = generate_enterprise_reference_data()
    assert {key: len(rows) for key, rows in data.items()} == {
        'organization': 1, 'region': 5, 'practice': 25, 'specialty': 12, 'provider': 150}
    assert data['organization'] == [{'organization_id': 10001, 'organization_name': 'NorthStar Medical Group',
                                      'created_at': '2021-01-01T00:00:00+00:00'}]
    assert [(r['region_code'], r['region_name']) for r in data['region']] == [
        ('R01', 'Northeast'), ('R02', 'Mid-Atlantic'), ('R03', 'Southeast'), ('R04', 'Midwest'), ('R05', 'Southwest')]
    assert [r['region_id'] for r in data['region']] == list(range(10001, 10006))
    assert [p['practice_id'] for p in data['practice']] == list(range(10001, 10026))
    assert [p['practice_code'] for p in data['practice']] == [f'P{i:02d}' for i in range(1, 26)]
    assert [p['provider_id'] for p in data['provider']] == [f'SYN-{i:03d}' for i in range(1, 151)]
    assert Counter(p['region_id'] for p in data['practice']) == {i: 5 for i in range(10001, 10006)}
    assert len({p['specialty_id'] for p in data['provider'][48:]}) == 10
    practices = {p['practice_id']: p for p in data['practice']}
    specialties = {s['specialty_id'] for s in data['specialty']}
    assert set(Counter(p['practice_id'] for p in data['provider'])) == set(practices)
    for provider in data['provider']:
        assert provider['clinic_name'] == practices[provider['practice_id']]['practice_name']
        assert provider['specialty_id'] in specialties


def test_legacy_identity_matches_committed_csv():
    fixture = generate_enterprise_reference_data()
    names = {row['specialty_id']: row['specialty_name'] for row in fixture['specialty']}
    old = load_data()[['provider_id', 'provider', 'specialty', 'clinic']].drop_duplicates().sort_values('provider_id')
    actual = [(r['provider_id'], r['provider_name'], names[r['specialty_id']], r['clinic_name'])
              for r in fixture['provider'][:48]]
    assert actual == list(old.itertuples(index=False, name=None))
    assert actual[0] == ('SYN-001', 'Dr. Maya Patel', 'Primary Care', 'North Clinic')
    assert actual[-1] == ('SYN-048', 'Dr. Nico King', 'Otolaryngology', 'Lakeside Clinic')
    expected_practices = {'North Clinic': 10001, 'Central Clinic': 10006, 'South Clinic': 10011,
                          'East Clinic': 10007, 'West Clinic': 10021, 'Lakeside Clinic': 10016}
    assert all(r['practice_id'] == expected_practices[r['clinic_name']] for r in fixture['provider'][:48])


@pytest.mark.parametrize('seed,expected', [
    (42, 'cbdd0b27e41fe09f3477a88b7f15ba2d503930a7c0848dd1d081094195291799'),
    (7, 'fd30b8e9a4b816afff4997a16b53ec3bdca2fcf9ae4e5ceeb5355076f1e4e194'),
])
def test_legacy_generator_matches_pre_refactor_snapshot(seed, expected):
    # Captured from the original generator before extracting shared identities.
    assert hashlib.sha256(generate_data(seed=seed).to_csv(index=False).encode()).hexdigest() == expected


def test_approved_columns_only():
    expected = {
        'organization': 'organization_id organization_name created_at',
        'region': 'region_id organization_id region_name region_code',
        'practice': 'practice_id region_id practice_name practice_code city state practice_type opening_date active',
        'specialty': 'specialty_id specialty_name',
        'provider': 'provider_id provider_name specialty_id clinic_name practice_id',
    }
    data = generate_enterprise_reference_data()
    assert set(data) == set(expected)
    for table, columns in expected.items():
        assert all(set(row) == set(columns.split()) for row in data[table])


@pytest.mark.parametrize('table,column,value', [
    ('organization', 'organization_name', 'Different Organization'),
    ('region', 'organization_id', 999),
    ('region', 'region_name', 'Unknown'),
    ('practice', 'region_id', 999),
    ('practice', 'practice_id', 10002),
    ('practice', 'practice_code', 'P02'),
    ('practice', 'opening_date', '2030-01-01'),
    ('practice', 'active', 'true'),
    ('provider', 'provider_id', 'SYN-002'),
    ('provider', 'provider_name', 'Dr. Ethan Chen'),
    ('provider', 'practice_id', 999),
    ('provider', 'specialty_id', 999),
    ('provider', 'clinic_name', ''),
    ('provider', 'clinic_name', 'Renamed Clinic'),
    ('provider', 'patient_id', 'forbidden'),
    ('specialty', 'specialty_name', 'Renamed Specialty'),
    ('specialty', 'specialty_id', 999),
])
def test_validation_rejects_invalid_references_and_identity_changes(table, column, value):
    data = generate_enterprise_reference_data()
    data[table][0][column] = value
    with pytest.raises(ValueError):
        validate_enterprise_reference_data(data)


@pytest.mark.parametrize('table', REFERENCE_TABLES)
def test_validation_rejects_missing_rows(table):
    data = generate_enterprise_reference_data()
    data[table].pop()
    with pytest.raises(ValueError):
        validate_enterprise_reference_data(data)


def test_validation_rejects_operational_tables():
    data = generate_enterprise_reference_data()
    data['employee'] = []
    with pytest.raises(ValueError):
        validate_enterprise_reference_data(data)


def test_export_cli_repeatability_and_no_overwrite(tmp_path):
    first, second = tmp_path / 'first.json', tmp_path / 'second.json'
    command = [sys.executable, str(ROOT / 'scripts/generate_enterprise_reference_data.py'), '--output']
    for path in (first, second):
        subprocess.run(command + [str(path)], cwd=tmp_path, check=True, capture_output=True)
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text()) == generate_enterprise_reference_data()
    before = first.read_bytes()
    result = subprocess.run(command + [str(first)], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert first.read_bytes() == before


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for PostgreSQL loader tests')
    import psycopg
    from psycopg import sql
    with psycopg.connect(url) as connection:
        schema = 'oppilot_reference_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        connection.execute((ROOT / 'db/schema.sql').read_text())
        try:
            yield connection
        finally:
            connection.rollback()


def snapshot(db, tables=REFERENCE_TABLES + FACT_TABLES):
    return {table: db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall() for table in tables}


def sequences(db):
    return {table: db.execute(f'SELECT last_value, is_called FROM {table}_{table}_id_seq').fetchone()
            for table in REFERENCE_TABLES if table != 'provider'}


def test_empty_database_load_and_exact_idempotence(db):
    result = load_enterprise_reference_data(db)
    assert result['counts'] == {t: len(r) for t, r in generate_enterprise_reference_data().items()}
    before, before_sequences = snapshot(db), sequences(db)
    assert all(before[table] == [] for table in FACT_TABLES)
    assert len(before['provider']) == 150
    assert db.execute('SELECT count(*) FROM provider WHERE practice_id IS NULL').fetchone() == (0,)
    assert db.execute('SELECT count(*) FROM provider p JOIN practice pr USING (practice_id) JOIN region r USING (region_id) JOIN organization o USING (organization_id)').fetchone() == (150,)
    assert load_enterprise_reference_data(db) == result
    assert snapshot(db) == before
    assert sequences(db) == before_sequences


def test_existing_specialty_ids_legacy_providers_and_facts_preserved(db):
    from src.postgres_analytics import BASE_FROM
    names = sorted({r['specialty_name'] for r in legacy_provider_records()})
    ids = {name: 200 + i for i, name in enumerate(names)}
    for name, identifier in ids.items():
        db.execute('INSERT INTO specialty VALUES (%s, %s)', (identifier, name))
    db.execute("INSERT INTO specialty VALUES (1, 'Unrelated Specialty')")
    for row in legacy_provider_records():
        db.execute('INSERT INTO provider (provider_id, provider_name, specialty_id, clinic_name) VALUES (%s, %s, %s, %s)',
                   (row['provider_id'], row['provider_name'], ids[row['specialty_name']], row['clinic_name']))
    db.execute("INSERT INTO provider VALUES ('OTHER-1', 'Unrelated Provider', 1, 'Unrelated Clinic', NULL)")
    db.execute("INSERT INTO appointment VALUES ('SYN-001', '2025-01-02', 10, 8, 1)")
    db.execute("INSERT INTO performance VALUES ('SYN-001', '2025-01-02', 1, 8, 7, 700)")
    db.execute("INSERT INTO appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) VALUES (1, 'SYN-001', '2025-01-02', 'completed', 100)")
    query = 'SELECT p.provider_id, p.provider_name, p.clinic_name, s.specialty_name, a.available_slots, pe.completed_visits, pe.realized_revenue ' + BASE_FROM
    before = db.execute(query).fetchall()
    facts = snapshot(db, FACT_TABLES)
    result = load_enterprise_reference_data(db)
    assert result['specialty_ids'] == ids
    assert db.execute(query).fetchall() == before
    assert snapshot(db, FACT_TABLES) == facts
    assert db.execute("SELECT * FROM provider WHERE provider_id = 'OTHER-1'").fetchone() == ('OTHER-1', 'Unrelated Provider', 1, 'Unrelated Clinic', None)
    assert db.execute('SELECT count(*) FROM specialty').fetchone() == (13,)
    # Legacy loader upsert leaves the newly populated practice mapping intact.
    db.execute('''INSERT INTO provider (provider_id, provider_name, specialty_id, clinic_name)
        VALUES ('SYN-001', 'Dr. Maya Patel', %s, 'North Clinic') ON CONFLICT (provider_id)
        DO UPDATE SET provider_name = EXCLUDED.provider_name,
        specialty_id = EXCLUDED.specialty_id, clinic_name = EXCLUDED.clinic_name''', (ids['Primary Care'],))
    assert db.execute("SELECT practice_id FROM provider WHERE provider_id = 'SYN-001'").fetchone() == (10001,)
    again = snapshot(db)
    load_enterprise_reference_data(db)
    assert snapshot(db) == again


def test_specialty_numeric_collision_preserves_unrelated_specialty(db):
    db.execute("INSERT INTO specialty VALUES (1, 'Unrelated Specialty')")
    load_enterprise_reference_data(db)
    assert db.execute('SELECT specialty_name FROM specialty WHERE specialty_id = 1').fetchone() == ('Unrelated Specialty',)
    assert db.execute('SELECT count(*) FROM specialty').fetchone() == (13,)
    assert db.execute('SELECT count(*) FROM provider p JOIN specialty s USING (specialty_id) WHERE s.specialty_name = %s', ('Unrelated Specialty',)).fetchone() == (0,)


@pytest.mark.parametrize('table,column,value', [
    ('organization', 'organization_name', 'Unrelated Organization'),
    ('region', 'region_name', 'Unrelated Region'),
    ('practice', 'practice_name', 'Unrelated Practice'),
    ('provider', 'provider_name', 'Unrelated Provider'),
    ('provider', 'clinic_name', 'Different Clinic'),
    ('provider', 'practice_id', 10002),
    ('provider', 'specialty_id', 2),
])
def test_conflicting_records_fail_without_overwrite(db, table, column, value):
    from psycopg import sql
    load_enterprise_reference_data(db)
    key = f'{table}_id'
    identifier = 'SYN-001' if table == 'provider' else 10001
    db.execute(sql.SQL('UPDATE {} SET {} = %s WHERE {} = %s').format(
        sql.Identifier(table), sql.Identifier(column), sql.Identifier(key)), (value, identifier))
    before = snapshot(db)
    with pytest.raises(ReferenceDataConflict):
        load_enterprise_reference_data(db)
    assert snapshot(db) == before


def test_late_provider_conflict_rolls_back_all_new_reference_rows(db):
    db.execute("INSERT INTO specialty VALUES (1, 'Existing Specialty')")
    db.execute("INSERT INTO provider VALUES ('SYN-150', 'Existing Provider', 1, 'Existing Clinic', NULL)")
    before = snapshot(db)
    with pytest.raises(ReferenceDataConflict):
        load_enterprise_reference_data(db)
    assert snapshot(db) == before


def test_natural_key_collision_rolls_back(db):
    import psycopg
    db.execute("INSERT INTO organization VALUES (999, 'NorthStar Medical Group', '2021-01-01T00:00:00Z')")
    before = snapshot(db)
    with pytest.raises(psycopg.errors.UniqueViolation):
        load_enterprise_reference_data(db)
    assert snapshot(db) == before


def test_sequences_advance_for_future_default_inserts_without_rewind(db):
    db.execute('ALTER SEQUENCE region_region_id_seq RESTART WITH 90000')
    load_enterprise_reference_data(db)
    assert db.execute("INSERT INTO organization (organization_name) VALUES ('Other Org') RETURNING organization_id").fetchone() == (10002,)
    assert db.execute("INSERT INTO region (organization_id, region_name, region_code) VALUES (10001, 'Other Region', 'OTHER') RETURNING region_id").fetchone() == (90000,)
    assert db.execute("INSERT INTO practice (region_id, practice_name, practice_code, city, state, practice_type, opening_date) VALUES (10001, 'Other Practice', 'OTHER', 'Demo', 'NY', 'Multispecialty', '2020-01-01') RETURNING practice_id").fetchone() == (10026,)
    assert db.execute("INSERT INTO specialty (specialty_name) VALUES ('Other Specialty') RETURNING specialty_id").fetchone() == (13,)


def test_sequence_restart_and_inserts_roll_back_together(db, monkeypatch):
    import src.enterprise_reference_loader as loader
    original = loader._advance_sequence
    before, before_sequences = snapshot(db), sequences(db)
    def fail_after_first(connection, table):
        original(connection, table)
        if table == 'region':
            raise RuntimeError('simulated failure after sequence restarts')
    monkeypatch.setattr(loader, '_advance_sequence', fail_after_first)
    with pytest.raises(RuntimeError):
        loader.load_enterprise_reference_data(db)
    assert snapshot(db) == before
    assert sequences(db) == before_sequences


def test_caller_rollback_can_undo_successful_load(db):
    before = snapshot(db)
    with pytest.raises(RuntimeError), db.transaction():
        load_enterprise_reference_data(db)
        raise RuntimeError('caller aborted')
    assert snapshot(db) == before
