"""Focused Phase 1F tests for deterministic anomaly injection."""
from collections import Counter
import os
from pathlib import Path
import uuid

import pytest

from src.enterprise_anomalies import (ANOMALY_TYPES, EXPECTED_DIRECTIONS,
    PORTFOLIO_DEMO, SEVERITIES, apply_anomalies, generate_enterprise_dataset)


@pytest.fixture(scope='module')
def anomaly_pair():
    baseline = generate_enterprise_dataset(appointment_count=20_000, referral_count=5_000)
    anomalous, truth = apply_anomalies(baseline)
    return baseline, anomalous, truth


def _definition(kind):
    return next(row for row in PORTFOLIO_DEMO if row.anomaly_type == kind)


def _staffing(rows, definition):
    return [r for r in rows if r['practice_id'] == definition.practice_id
            and r['role'] == 'Medical Assistant'
            and definition.start_date <= r['staff_date'] <= definition.end_date]


def _capacity(rows, definition):
    providers = {definition.provider_id} if definition.provider_id else None
    return [r for r in rows if definition.start_date <= r['capacity_date'] <= definition.end_date
            and (providers is None or r['provider_id'] in providers)]


def _appointments(rows, definition):
    return [r for r in rows if r['practice_id'] == definition.practice_id
            and definition.start_date <= r['appointment_date'] <= definition.end_date]


def _encounters(rows, definition):
    return [r for r in rows if r['practice_id'] == definition.practice_id
            and definition.start_date <= r['encounter_date'] <= definition.end_date]


def test_portfolio_demo_truth_is_deterministic_and_catalog_valid(anomaly_pair):
    baseline, anomalous, truth = anomaly_pair
    again, truth_again = apply_anomalies(baseline)
    assert anomalous == again
    assert truth == truth_again
    assert len(truth) == 10
    assert [row['anomaly_id'] for row in truth] == list(range(900001, 900011))
    assert Counter(row['anomaly_type'] for row in truth) == Counter({
        'MA_STAFFING_SHORTAGE': 2,
        'PROVIDER_PTO_CAPACITY_REDUCTION': 2,
        'NO_SHOW_SPIKE': 2,
        'REFERRAL_DEMAND_SURGE': 2,
        'SCHEDULING_TEMPLATE_CAPACITY_REDUCTION': 1,
        'REVENUE_PER_VISIT_DECLINE': 1,
    })
    assert {row['anomaly_type'] for row in truth} == set(ANOMALY_TYPES)
    assert {row['severity'] for row in truth} <= set(SEVERITIES)
    assert {row['expected_direction'] for row in truth} <= set(EXPECTED_DIRECTIONS)


def test_baseline_is_not_mutated_when_anomalies_are_applied(anomaly_pair):
    baseline, _, _ = anomaly_pair
    clean = generate_enterprise_dataset(appointment_count=20_000, referral_count=5_000)
    assert baseline == clean


def test_ma_staffing_shortage_changes_only_ma_staffing_pattern(anomaly_pair):
    baseline, anomalous, _ = anomaly_pair
    definition = _definition('MA_STAFFING_SHORTAGE')
    before = _staffing(baseline['operations']['staffing_daily'], definition)
    after = _staffing(anomalous['operations']['staffing_daily'], definition)
    assert sum(r['actual_fte'] for r in after) < sum(r['actual_fte'] for r in before)
    assert sum(r['absence_hours'] for r in after) > sum(r['absence_hours'] for r in before)
    assert all(r['actual_fte'] >= 0 for r in after)


def test_provider_pto_and_template_capacity_anomalies_are_distinguishable(anomaly_pair):
    baseline, anomalous, _ = anomaly_pair
    pto = _definition('PROVIDER_PTO_CAPACITY_REDUCTION')
    before = _capacity(baseline['operations']['provider_capacity'], pto)
    after = _capacity(anomalous['operations']['provider_capacity'], pto)
    assert sum(r['pto_hours'] for r in after) > sum(r['pto_hours'] for r in before)
    assert sum(r['clinical_hours'] for r in after) < sum(r['clinical_hours'] for r in before)
    template = _definition('SCHEDULING_TEMPLATE_CAPACITY_REDUCTION')
    before = _capacity(baseline['operations']['provider_capacity'], template)
    after = _capacity(anomalous['operations']['provider_capacity'], template)
    assert sum(r['blocked_slots'] for r in after) > sum(r['blocked_slots'] for r in before)
    assert sum(r['clinical_hours'] for r in after) == sum(r['clinical_hours'] for r in before)
    assert all(r['available_slots'] >= 0 for r in after)


def test_no_show_spike_removes_inconsistent_finance_rows(anomaly_pair):
    baseline, anomalous, _ = anomaly_pair
    definition = _definition('NO_SHOW_SPIKE')
    before = Counter(r['appointment_status'] for r in _appointments(baseline['appointment_event'], definition))
    after = Counter(r['appointment_status'] for r in _appointments(anomalous['appointment_event'], definition))
    assert after['no_show'] > before['no_show']
    appointments = {r['appointment_id']: r for r in anomalous['appointment_event']}
    assert all(appointments[e['appointment_id']]['appointment_status'] == 'completed'
               for e in anomalous['finance']['encounter'])
    encounter_ids = {e['encounter_id'] for e in anomalous['finance']['encounter']}
    assert all(p['encounter_id'] in encounter_ids for p in anomalous['finance']['payment'])


def test_referral_surge_and_revenue_decline_metrics_move_as_expected(anomaly_pair):
    baseline, anomalous, _ = anomaly_pair
    surge = _definition('REFERRAL_DEMAND_SURGE')
    before = [r for r in baseline['referral'] if r['practice_id'] == surge.practice_id
              and r['specialty_id'] == surge.specialty_id
              and surge.start_date <= r['referral_date'] <= surge.end_date]
    after = [r for r in anomalous['referral'] if r['practice_id'] == surge.practice_id
             and r['specialty_id'] == surge.specialty_id
             and surge.start_date <= r['referral_date'] <= surge.end_date]
    assert len(after) > len(before)
    revenue = _definition('REVENUE_PER_VISIT_DECLINE')
    before = _encounters(baseline['finance']['encounter'], revenue)
    after = _encounters(anomalous['finance']['encounter'], revenue)
    assert len(after) == len(before)
    assert sum(r['allowed_amount'] for r in after) < sum(r['allowed_amount'] for r in before)
    assert all(r['allowed_amount'] >= 0 for r in after)


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for PostgreSQL loader tests')
    from psycopg import sql
    from src.enterprise_reference_loader import load_enterprise_reference_data
    schema = (Path(__file__).resolve().parents[1] / 'db/schema.sql').read_text()
    with __import__('psycopg').connect(url) as connection:
        schema_name = 'oppilot_anomalies_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema_name)))
        try:
            connection.execute(schema)
            load_enterprise_reference_data(connection)
            yield connection
        finally:
            connection.rollback()


def test_ground_truth_loader_is_idempotent_and_conflict_safe(db):
    from src.enterprise_anomaly_loader import AnomalyConflict, load_ground_truth_anomalies
    assert load_ground_truth_anomalies(db) == {'rows': 10, 'inserted': 10}
    assert load_ground_truth_anomalies(db) == {'rows': 10, 'inserted': 0}
    db.execute("UPDATE ground_truth_anomaly SET severity = 'low' WHERE anomaly_id = 900001")
    with pytest.raises(AnomalyConflict):
        load_ground_truth_anomalies(db)
