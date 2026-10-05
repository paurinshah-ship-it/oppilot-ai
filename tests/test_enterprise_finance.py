"""Focused Phase 1E tests for encounters and payments."""
from datetime import date
import os
from pathlib import Path
import uuid

import pytest

from src.enterprise_appointments import generate_appointment_events
from src.enterprise_finance import (MIN_ENCOUNTER_ID, PAYER_CATEGORIES,
    generate_enterprise_finance, validate_enterprise_finance)


def test_finance_generation_is_deterministic_and_only_completed_appointments():
    first = generate_enterprise_finance(count=500, seed=42)
    second = generate_enterprise_finance(count=500, seed=42)
    assert first == second
    completed = [row for row in generate_appointment_events(count=500, seed=42)
                 if row['appointment_status'] == 'completed']
    assert len(first['encounter']) == len(completed)
    assert [row['encounter_id'] for row in first['encounter'][:3]] == [
        MIN_ENCOUNTER_ID, MIN_ENCOUNTER_ID + 1, MIN_ENCOUNTER_ID + 2]
    assert {row['appointment_id'] for row in first['encounter']} == {
        row['appointment_id'] for row in completed}


def test_finance_integrity_amounts_lags_and_no_phi():
    data = generate_enterprise_finance(count=1_000, seed=17)
    summary = validate_enterprise_finance(data)
    assert summary['counts']['encounter'] == summary['counts']['payment']
    assert summary['payment_lag_days']['min'] >= 0
    assert summary['payment_lag_days']['max'] <= 90
    assert set(data['encounter'][0]).isdisjoint({'patient_id', 'patient_name', 'diagnosis', 'clinical_note', 'cpt_code'})
    assert set(data['payment'][0]).isdisjoint({'patient_id', 'patient_name'})
    encounters = {row['encounter_id']: row for row in data['encounter']}
    for payment in data['payment']:
        encounter = encounters[payment['encounter_id']]
        assert payment['payer_category'] in PAYER_CATEGORIES
        assert date.fromisoformat(payment['payment_date']) >= date.fromisoformat(encounter['encounter_date'])
        assert payment['allowed_amount'] == encounter['allowed_amount']
        assert payment['paid_amount'] >= 0
        assert payment['patient_amount'] >= 0
        assert payment['adjustment_amount'] >= 0
    for encounter in data['encounter']:
        assert encounter['work_rvu'] >= 0
        assert encounter['modeled_charge'] >= 0
        assert 0 <= encounter['allowed_amount'] <= encounter['modeled_charge']


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for PostgreSQL loader tests')
    from psycopg import sql
    from src.enterprise_reference_loader import load_enterprise_reference_data
    from src.enterprise_appointment_loader import load_appointment_events
    schema = (Path(__file__).resolve().parents[1] / 'db/schema.sql').read_text()
    with __import__('psycopg').connect(url) as connection:
        schema_name = 'oppilot_finance_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema_name)))
        try:
            connection.execute(schema)
            load_enterprise_reference_data(connection)
            load_appointment_events(connection, count=500, seed=42)
            yield connection
        finally:
            connection.rollback()


def test_finance_loader_is_idempotent_and_transactional(db):
    from src.enterprise_finance_loader import FinanceConflict, load_enterprise_finance
    first = load_enterprise_finance(db, count=500, seed=42)
    assert first['rows']['encounter'] > 0
    assert first['inserted'] == first['rows']
    assert load_enterprise_finance(db, count=500, seed=42)['inserted'] == {
        'encounter': 0, 'payment': 0}
    before = db.execute('SELECT COUNT(*) FROM encounter').fetchone()[0]
    db.execute('UPDATE encounter SET modeled_charge = modeled_charge + 1 WHERE encounter_id = %s',
               (MIN_ENCOUNTER_ID,))
    with pytest.raises(FinanceConflict):
        load_enterprise_finance(db, count=500, seed=42)
    assert db.execute('SELECT COUNT(*) FROM encounter').fetchone()[0] == before
