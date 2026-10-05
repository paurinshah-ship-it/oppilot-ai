"""Operational baseline invariants and real PostgreSQL bulk loading tests."""
from collections import Counter
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import uuid

import pytest

from src.enterprise_operations import (START_DATE, END_DATE, FIELDS, ROLES, dates,
    generate_enterprise_operations, generate_employees, generate_provider_capacity,
    generate_staffing_daily, validate_enterprise_operations)
from src.enterprise_reference import generate_enterprise_reference_data
from src.enterprise_reference_loader import load_enterprise_reference_data
from src.enterprise_operations_loader import load_enterprise_operations, OperationsConflict

ROOT = Path(__file__).resolve().parents[1]
SHORT_END = date(2024, 1, 7)


@pytest.fixture(scope='module')
def full():
    return generate_enterprise_operations()


@pytest.fixture(scope='module')
def small():
    return generate_enterprise_operations(START_DATE, SHORT_END)


def test_exact_counts_and_complete_daily_coverage(full):
    assert (START_DATE, END_DATE) == (date(2024, 1, 1), date(2025, 12, 31))
    assert len(dates()) == 731
    assert {t: len(rows) for t, rows in full.items()} == {'employee': 462, 'provider_capacity': 109650, 'staffing_daily': 146200}
    expected_dates = {d.isoformat() for d in dates()}
    for table, column in [('provider_capacity', 'capacity_date'), ('staffing_daily', 'staff_date')]:
        assert {r[column] for r in full[table]} == expected_dates
    assert '2024-02-29' in expected_dates
    assert set(Counter(r['provider_id'] for r in full['provider_capacity']).values()) == {731}
    assert set(Counter((r['practice_id'], r['role']) for r in full['staffing_daily']).values()) == {731}


def test_determinism_and_independent_random_state(full):
    state = random.getstate()
    assert generate_enterprise_operations() == full
    assert random.getstate() == state


def test_short_window_matches_full_slice(full, small):
    assert small['employee'] == full['employee']
    for table, column in [('provider_capacity', 'capacity_date'), ('staffing_daily', 'staff_date')]:
        assert small[table] == [r for r in full[table] if r[column] <= SHORT_END.isoformat()]
    # A late window starts with identical daily random streams, not reset patterns.
    end = date(2025, 12, 31)
    late = generate_enterprise_operations(end, end)
    assert late['provider_capacity'] == [r for r in full['provider_capacity'] if r['capacity_date'] == end.isoformat()]
    assert late['staffing_daily'] == [r for r in full['staffing_daily'] if r['staff_date'] == end.isoformat()]


def test_employee_roles_dates_ids_and_nonidentical_practices(full):
    expected_roles = {'Medical Assistant', 'RN', 'LPN', 'Front Desk', 'Scheduler', 'Practice Manager', 'Referral Coordinator', 'Billing Specialist'}
    assert set(ROLES) == expected_roles
    assert set(r['role'] for r in full['employee']) == expected_roles
    assert len({r['employee_id'] for r in full['employee']}) == 462
    assert full['employee'][0]['employee_id'] == 1000000
    reference = generate_enterprise_reference_data()
    practice = {p['practice_id']: p for p in reference['practice']}
    headcounts = Counter(r['practice_id'] for r in full['employee'])
    assert set(headcounts) == set(practice)
    assert len(set(headcounts.values())) > 1
    roles = Counter((r['practice_id'], r['role']) for r in full['employee'])
    providers = Counter(p['practice_id'] for p in reference['provider'])
    for p in practice:
        assert roles[p, 'Medical Assistant'] == providers[p] + 1
        assert roles[p, 'Practice Manager'] == 1 < roles[p, 'Front Desk']
    for row in full['employee']:
        assert .5 <= row['fte'] <= 1
        assert 15 <= row['hourly_cost'] <= 60
        assert practice[row['practice_id']]['opening_date'] <= row['hire_date'] < '2024-01-01'
        assert row['status'] == 'active' and row['termination_date'] is None


def test_capacity_hours_slots_variation_and_weekends(full):
    reference = generate_enterprise_reference_data()
    assert {r['provider_id'] for r in full['provider_capacity']} == {r['provider_id'] for r in reference['provider']}
    assert len({(r['provider_id'], r['capacity_date']) for r in full['provider_capacity']}) == 109650
    patterns = set()
    pto_days = 0
    for row in full['provider_capacity']:
        for column in FIELDS['provider_capacity'][2:]:
            assert row[column] >= 0
        assert row['scheduled_hours'] == pytest.approx(row['clinical_hours'] + row['pto_hours'] + row['admin_hours'])
        assert row['scheduled_hours'] <= 8
        assert row['available_slots'] + row['blocked_slots'] <= row['clinical_hours'] * 5
        if date.fromisoformat(row['capacity_date']).weekday() >= 5:
            assert all(row[k] == 0 for k in FIELDS['provider_capacity'][2:])
        elif row['scheduled_hours']:
            patterns.add((row['scheduled_hours'], row['admin_hours'], row['available_slots']))
        pto_days += row['pto_hours'] > 0
    assert len(patterns) > 10
    assert 0 < pto_days < len(full['provider_capacity']) * .06


def test_staffing_reconciles_and_natural_variation_present(full):
    rows = full['staffing_daily']
    assert len({(r['practice_id'], r['staff_date'], r['role']) for r in rows}) == len(rows)
    assert {r['role'] for r in rows} == set(ROLES)
    agency_days = 0
    for row in rows:
        assert all(row[k] >= 0 for k in FIELDS['staffing_daily'][3:])
        assert row['actual_fte'] <= row['scheduled_fte'] <= row['budgeted_fte']
        assert row['absence_hours'] == pytest.approx((row['scheduled_fte'] - row['actual_fte']) * 8)
        assert row['overtime_hours'] + row['agency_hours'] <= (row['budgeted_fte'] - row['actual_fte']) * 8 + 1e-7
        if date.fromisoformat(row['staff_date']).weekday() >= 5:
            assert all(row[k] == 0 for k in FIELDS['staffing_daily'][3:])
        agency_days += row['agency_hours'] > 0
    assert 0 < agency_days < len(rows) * .05
    assert any(r['overtime_hours'] > 0 for r in rows)
    assert any(r['actual_fte'] < r['scheduled_fte'] < r['budgeted_fte'] for r in rows)


def test_exact_allowed_fields_no_personal_or_anomaly_fields(small):
    expected = {
        'employee': 'employee_id practice_id role fte hourly_cost hire_date termination_date status',
        'provider_capacity': 'provider_id capacity_date scheduled_hours clinical_hours available_slots blocked_slots pto_hours admin_hours',
        'staffing_daily': 'practice_id staff_date role budgeted_fte scheduled_fte actual_fte overtime_hours agency_hours absence_hours',
    }
    assert set(small) == set(expected)
    for table, fields in expected.items():
        assert all(set(row) == set(fields.split()) for row in small[table])


@pytest.mark.parametrize('start,end', [(date(2023,12,31), END_DATE), (START_DATE, date(2026,1,1)),
                                     (END_DATE, START_DATE), ('2024-01-01', END_DATE)])
def test_invalid_windows_rejected(start, end):
    with pytest.raises(ValueError):
        dates(start, end)


@pytest.mark.parametrize('table,column,value', [
    ('employee', 'employee_id', 42), ('employee', 'practice_id', 999),
    ('employee', 'role', 'Surgeon'), ('employee', 'fte', -1), ('employee', 'fte', float('nan')),
    ('employee', 'hourly_cost', float('inf')), ('employee', 'hire_date', 'bad-date'),
    ('employee', 'termination_date', '2000-01-01'), ('employee', 'status', 'terminated'),
    ('employee', 'email', 'forbidden'),
    ('provider_capacity', 'provider_id', 'UNKNOWN'), ('provider_capacity', 'capacity_date', '2023-12-31'),
    ('provider_capacity', 'clinical_hours', 100), ('provider_capacity', 'pto_hours', -1),
    ('provider_capacity', 'available_slots', -1), ('provider_capacity', 'blocked_slots', .5),
    ('provider_capacity', 'admin_hours', .001),
    ('staffing_daily', 'practice_id', 999), ('staffing_daily', 'staff_date', '2026-01-01'),
    ('staffing_daily', 'role', 'Surgeon'), ('staffing_daily', 'actual_fte', 100),
    ('staffing_daily', 'absence_hours', -1), ('staffing_daily', 'agency_hours', 100),
    ('staffing_daily', 'overtime_hours', 100), ('staffing_daily', 'budgeted_fte', float('nan')),
])
def test_invalid_operational_values_rejected(small, table, column, value):
    data = deepcopy(small)
    data[table][0][column] = value
    with pytest.raises(ValueError):
        validate_enterprise_operations(data, start=START_DATE, end=SHORT_END)


@pytest.mark.parametrize('table', list(FIELDS))
def test_duplicates_rejected(small, table):
    data = deepcopy(small)
    data[table][1] = dict(data[table][0])
    with pytest.raises(ValueError):
        validate_enterprise_operations(data, start=START_DATE, end=SHORT_END)


@pytest.mark.parametrize('table', ['provider_capacity', 'staffing_daily'])
def test_missing_day_rejected(small, table):
    data = deepcopy(small)
    data[table].pop()
    with pytest.raises(ValueError):
        validate_enterprise_operations(data, start=START_DATE, end=SHORT_END)


def test_csv_export_and_no_overwrite(tmp_path):
    output = tmp_path / 'export'
    command = [sys.executable, str(ROOT / 'scripts/generate_enterprise_operations.py'),
               '--output-dir', str(output), '--start', '2024-01-01', '--end', '2024-01-07']
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    assert json.loads((output / 'manifest.json').read_text())['rows'] == {'employee': 462, 'provider_capacity': 1050, 'staffing_daily': 1400}
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert subprocess.run(command, cwd=tmp_path, capture_output=True).returncode != 0
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for real PostgreSQL bulk-loader tests')
    import psycopg
    from psycopg import sql
    with psycopg.connect(url) as connection:
        schema = 'oppilot_operations_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        connection.execute((ROOT / 'db/schema.sql').read_text())
        try:
            yield connection
        finally:
            connection.rollback()


@pytest.fixture
def ready(db):
    load_enterprise_reference_data(db)
    return db


def counts(db):
    return {t: db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in FIELDS}


def snapshot(db):
    return {t: db.execute(f'SELECT * FROM {t} ORDER BY 1, 2').fetchall() for t in FIELDS}


def test_full_bulk_load_and_identical_rerun(ready, full):
    result = load_enterprise_operations(ready, full)
    expected = {'employee': 462, 'provider_capacity': 109650, 'staffing_daily': 146200}
    assert counts(ready) == expected
    assert result['inserted'] == expected
    before = ready.execute('SELECT last_value, is_called FROM employee_employee_id_seq').fetchone()
    assert load_enterprise_operations(ready, full)['inserted'] == dict.fromkeys(FIELDS, 0)
    assert ready.execute('SELECT last_value, is_called FROM employee_employee_id_seq').fetchone() == before
    assert ready.execute('SELECT min(capacity_date), max(capacity_date) FROM provider_capacity').fetchone() == (START_DATE, END_DATE)
    assert ready.execute('SELECT count(*) FROM ground_truth_anomaly').fetchone() == (0,)


def test_overlapping_development_windows_are_safe(ready, small):
    load_enterprise_operations(ready, small, START_DATE, SHORT_END)
    next_end = date(2024,1,9)
    other = generate_enterprise_operations(date(2024,1,5), next_end)
    result = load_enterprise_operations(ready, other, date(2024,1,5), next_end)
    assert result['inserted'] == {'employee': 0, 'provider_capacity': 300, 'staffing_daily': 400}
    assert counts(ready) == {'employee': 462, 'provider_capacity': 1350, 'staffing_daily': 1800}


def test_missing_or_changed_references_rejected(db, small):
    with pytest.raises(OperationsConflict):
        load_enterprise_operations(db, small, START_DATE, SHORT_END)
    assert counts(db) == dict.fromkeys(FIELDS, 0)
    load_enterprise_reference_data(db)
    db.execute("UPDATE provider SET practice_id = 10002 WHERE provider_id = 'SYN-001'")
    with pytest.raises(OperationsConflict):
        load_enterprise_operations(db, small, START_DATE, SHORT_END)
    assert counts(db) == dict.fromkeys(FIELDS, 0)


@pytest.mark.parametrize('table,column', [('employee', 'hourly_cost'), ('provider_capacity', 'admin_hours'), ('staffing_daily', 'agency_hours')])
def test_conflicts_rejected_without_overwrite(ready, small, table, column):
    load_enterprise_operations(ready, small, START_DATE, SHORT_END)
    ready.execute(f'UPDATE {table} SET {column} = {column} + 1')
    before = snapshot(ready)
    with pytest.raises(OperationsConflict):
        load_enterprise_operations(ready, small, START_DATE, SHORT_END)
    assert snapshot(ready) == before


def test_late_copy_failure_rolls_back_all_tables(ready, small, monkeypatch):
    import src.enterprise_operations_loader as loader
    original = loader._copy_rows
    def fail(cursor, stage, table, rows):
        original(cursor, stage, table, rows)
        if table == 'staffing_daily':
            raise RuntimeError('simulated bulk copy failure')
    monkeypatch.setattr(loader, '_copy_rows', fail)
    with pytest.raises(RuntimeError):
        loader.load_enterprise_operations(ready, small, START_DATE, SHORT_END)
    assert counts(ready) == dict.fromkeys(FIELDS, 0)


def test_sequence_and_data_rollback_together(ready, small, monkeypatch):
    import src.enterprise_operations_loader as loader
    original = loader._advance_employee_sequence
    before = ready.execute('SELECT last_value, is_called FROM employee_employee_id_seq').fetchone()
    def fail(connection):
        original(connection)
        raise RuntimeError('simulated post-sequence failure')
    monkeypatch.setattr(loader, '_advance_employee_sequence', fail)
    with pytest.raises(RuntimeError):
        loader.load_enterprise_operations(ready, small, START_DATE, SHORT_END)
    assert counts(ready) == dict.fromkeys(FIELDS, 0)
    assert ready.execute('SELECT last_value, is_called FROM employee_employee_id_seq').fetchone() == before


def test_preserves_reference_legacy_and_unrelated_rows(ready, small):
    untouched = ('organization', 'region', 'practice', 'specialty', 'provider', 'appointment', 'performance',
                 'appointment_event', 'encounter', 'referral', 'payment', 'ground_truth_anomaly')
    ready.execute("INSERT INTO appointment VALUES ('SYN-001', '2025-01-02', 10, 8, 1)")
    ready.execute("INSERT INTO performance VALUES ('SYN-001', '2025-01-02', 1, 8, 7, 700)")
    ready.execute("INSERT INTO appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) VALUES (1, 'SYN-001', '2025-01-02', 'completed', 100)")
    ready.execute("INSERT INTO employee VALUES (42, 10001, 'Other role', 1, 20, '2020-01-01', NULL, 'active')")
    ready.execute("INSERT INTO provider_capacity VALUES ('SYN-001', '2023-01-01', 8, 7, 20, 0, 0, 1)")
    ready.execute("INSERT INTO staffing_daily VALUES (10001, '2023-01-01', 'RN', 2, 2, 2, 0, 0, 0)")
    before = {t: ready.execute(f'SELECT * FROM {t} ORDER BY 1, 2').fetchall() for t in untouched}
    load_enterprise_operations(ready, small, START_DATE, SHORT_END)
    assert {t: ready.execute(f'SELECT * FROM {t} ORDER BY 1, 2').fetchall() for t in untouched} == before
    assert counts(ready) == {'employee': 463, 'provider_capacity': 1051, 'staffing_daily': 1401}
    maximum = ready.execute('SELECT max(employee_id) FROM employee').fetchone()[0]
    assert ready.execute("INSERT INTO employee (practice_id, role, fte, hourly_cost, hire_date, status) VALUES (10001, 'Other', 1, 20, '2020-01-01', 'active') RETURNING employee_id").fetchone() == (maximum + 1,)


def test_outer_transaction_can_rollback_success(ready, small):
    with pytest.raises(RuntimeError), ready.transaction():
        load_enterprise_operations(ready, small, START_DATE, SHORT_END)
        raise RuntimeError('outer caller aborted')
    assert counts(ready) == dict.fromkeys(FIELDS, 0)
