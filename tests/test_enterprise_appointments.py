"""Focused deterministic, compatibility and transactional tests for Phase 1D."""
from datetime import date
from itertools import islice
import os
from pathlib import Path
import uuid

import pytest

from src.enterprise_appointments import (APPOINTMENT_TYPES, DEFAULT_COUNT, END_DATE,
    FIELDS, MIN_APPOINTMENT_ID, PAYER_CATEGORIES, SLOT_DURATIONS, START_DATE,
    STATUSES, generate_appointment_events, validate_appointment_events)


def test_generation_is_deterministic_and_small_mode_has_stable_ids():
    first = list(generate_appointment_events(500, seed=17))
    second = list(generate_appointment_events(500, seed=17))
    assert first == second
    assert [row['appointment_id'] for row in first[:3]] == [MIN_APPOINTMENT_ID + i for i in range(3)]
    summary = validate_appointment_events(iter(first))
    assert summary['count'] == 500
    assert sum(summary['status_counts'].values()) == 500


def test_one_million_scale_path_is_lazy_and_uses_same_prefix():
    large = generate_appointment_events(DEFAULT_COUNT, seed=42)
    sample = list(islice(large, 4))
    assert [row['appointment_id'] for row in sample] == list(range(MIN_APPOINTMENT_ID, MIN_APPOINTMENT_ID + 4))
    assert sample == list(islice(generate_appointment_events(4, seed=42), 4))


def test_event_contract_catalogs_relationships_dates_and_revenue():
    reference = __import__('src.enterprise_reference', fromlist=['generate_enterprise_reference_data']).generate_enterprise_reference_data()
    providers = {p['provider_id']: p for p in reference['provider']}
    rows = list(generate_appointment_events(2_000, seed=42, reference=reference))
    assert set(rows[0]) == set(FIELDS)
    assert set(FIELDS).isdisjoint({'patient_id', 'patient_name', 'diagnosis', 'clinical_note'})
    assert {r['appointment_status'] for r in rows} <= set(STATUSES)
    assert {r['appointment_type'] for r in rows} <= set(APPOINTMENT_TYPES)
    assert {r['payer_category'] for r in rows} <= set(PAYER_CATEGORIES)
    assert {r['slot_duration_minutes'] for r in rows} <= set(SLOT_DURATIONS)
    for row in rows:
        assert row['practice_id'] == providers[row['provider_id']]['practice_id']
        assert row['scheduled_at'].date() <= date.fromisoformat(row['appointment_date'])
        assert row['modeled_revenue'] >= 0
        assert (row['modeled_revenue'] > 0) == (row['appointment_status'] == 'completed')
    assert {'cancelled', 'cancelled_patient', 'cancelled_provider',
            'cancelled_practice', 'rescheduled'} <= {r['appointment_status'] for r in rows}


def test_invalid_generator_windows_and_provider_practice_mapping_rejected():
    with pytest.raises(ValueError):
        generate_appointment_events(1, start=date(2023, 12, 31))
    row = next(generate_appointment_events(1))
    row['practice_id'] += 1
    with pytest.raises(ValueError, match='provider/practice'):
        validate_appointment_events([row])


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for PostgreSQL loader tests')
    from psycopg import sql
    from src.enterprise_reference_loader import load_enterprise_reference_data
    schema = (Path(__file__).resolve().parents[1] / 'db/schema.sql').read_text()
    with __import__('psycopg').connect(url) as connection:
        schema_name = 'oppilot_appointments_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema_name)))
        try:
            connection.execute(schema)
            load_enterprise_reference_data(connection)
            yield connection
        finally:
            connection.rollback()


def test_loader_is_atomic_idempotent_and_preserves_legacy_event(db):
    from src.enterprise_appointment_loader import load_appointment_events
    db.execute("INSERT INTO appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) VALUES (1, 'SYN-001', '2025-01-02', 'completed', 100)")
    first = load_appointment_events(db, count=2_000, seed=42)
    assert first['inserted'] == 2_000
    assert sum(first['status_counts'].values()) == 2_000
    assert load_appointment_events(db, count=2_000, seed=42)['inserted'] == 0
    assert db.execute('SELECT COUNT(*) FROM appointment_event').fetchone() == (2_001,)
    assert db.execute('SELECT provider_id, modeled_revenue FROM appointment_event WHERE appointment_id = 1').fetchone() == ('SYN-001', 100)


def test_loader_conflict_rolls_back_staged_batch(db):
    from src.enterprise_appointment_loader import AppointmentEventConflict, load_appointment_events
    db.execute("INSERT INTO appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) VALUES (%s, 'SYN-001', '2025-01-02', 'completed', 1)", (MIN_APPOINTMENT_ID,))
    with pytest.raises(AppointmentEventConflict, match='differs'):
        load_appointment_events(db, count=20, seed=42)
    assert db.execute('SELECT COUNT(*) FROM appointment_event').fetchone() == (1,)


def test_scalable_no_show_formula_excludes_non_visit_outcomes(db):
    from src.scalable_analytics import EVENT_METRICS
    assert EVENT_METRICS['no_show_rate'] == (
        "COUNT(*) FILTER (WHERE e.appointment_status = 'no_show')::numeric / "
        "NULLIF(COUNT(*) FILTER (WHERE e.appointment_status IN ('completed', 'no_show')), 0)"
    )
    statuses = ('completed', 'no_show', 'cancelled', 'cancelled_patient',
                'cancelled_provider', 'cancelled_practice', 'rescheduled')
    for index, status in enumerate(statuses, 1):
        db.execute('''INSERT INTO appointment_event
            (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue)
            VALUES (%s, 'SYN-001', '2025-01-02', %s, %s)''', (index, status, 100 if status == 'completed' else 0))
    result = db.execute('''SELECT COUNT(*), COUNT(*) FILTER (WHERE appointment_status='completed'),
        COUNT(*) FILTER (WHERE appointment_status='no_show'),
        COUNT(*) FILTER (WHERE appointment_status='no_show')::numeric /
            NULLIF(COUNT(*) FILTER (WHERE appointment_status IN ('completed', 'no_show')), 0),
        SUM(modeled_revenue) FILTER (WHERE appointment_status='completed') FROM appointment_event''').fetchone()
    assert result[:3] == (7, 1, 1)
    assert float(result[3]) == pytest.approx(1 / 2)
    assert result[4] == 100


def test_scalable_no_show_legacy_statuses_match_previous_result(db):
    from src.scalable_analytics import EventAggregateRequest, compile_event_aggregate
    statuses = ('completed', 'completed', 'no_show', 'cancelled')
    for index, status in enumerate(statuses, 1):
        db.execute('''INSERT INTO appointment_event
            (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue)
            VALUES (%s, 'SYN-001', '2025-01-02', %s, %s)''', (index, status, 100 if status == 'completed' else 0))
    query = compile_event_aggregate(EventAggregateRequest('no_show_rate'))
    result = db.execute(query.sql, query.params).fetchone()[0]
    assert float(result) == pytest.approx(1 / 3)


def test_scalable_no_show_zero_denominator_is_null(db):
    from src.scalable_analytics import EventAggregateRequest, compile_event_aggregate
    for index, status in enumerate(('cancelled', 'cancelled_patient',
                                    'cancelled_provider', 'cancelled_practice',
                                    'rescheduled'), 1):
        db.execute('''INSERT INTO appointment_event
            (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue)
            VALUES (%s, 'SYN-001', '2025-01-02', %s, 0)''', (index, status))
    query = compile_event_aggregate(EventAggregateRequest('no_show_rate'))
    assert db.execute(query.sql, query.params).fetchone()[0] is None
