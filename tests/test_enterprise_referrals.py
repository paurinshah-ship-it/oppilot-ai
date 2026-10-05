"""Focused Phase 1E tests for synthetic referral demand."""
import os
from pathlib import Path
import uuid

import pytest

from src.enterprise_referrals import (SOURCES, STATUSES, generate_referrals,
    validate_referrals)


def test_referral_generation_is_deterministic_and_catalog_valid():
    first = generate_referrals(count=1_000, seed=42)
    second = generate_referrals(count=1_000, seed=42)
    assert first == second
    summary = validate_referrals(first)
    assert summary['count'] == 1_000
    assert set(summary['status_counts']) <= set(STATUSES)
    assert set(STATUSES) <= {row['status'] for row in generate_referrals(count=5_000, seed=42)}
    assert {row['referral_source'] for row in first} <= set(SOURCES)


def test_referral_references_dates_and_no_phi():
    rows = generate_referrals(count=1_000, seed=7)
    assert set(rows[0]).isdisjoint({'patient_id', 'patient_name', 'referring_physician', 'diagnosis'})
    pairs = {(row['practice_id'], row['specialty_id']) for row in rows}
    assert len(pairs) > 100
    for row in rows:
        if row['scheduled_date'] is not None:
            assert row['scheduled_date'] >= row['referral_date']
        assert row['status'] not in ('scheduled', 'completed') or row['scheduled_date'] is not None


@pytest.fixture
def db():
    url = os.getenv('OPPILOT_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set OPPILOT_TEST_DATABASE_URL for PostgreSQL loader tests')
    from psycopg import sql
    from src.enterprise_reference_loader import load_enterprise_reference_data
    schema = (Path(__file__).resolve().parents[1] / 'db/schema.sql').read_text()
    with __import__('psycopg').connect(url) as connection:
        schema_name = 'oppilot_referrals_' + uuid.uuid4().hex
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema_name)))
        connection.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema_name)))
        try:
            connection.execute(schema)
            load_enterprise_reference_data(connection)
            yield connection
        finally:
            connection.rollback()


def test_referral_loader_is_idempotent_and_transactional(db):
    from src.enterprise_referral_loader import ReferralConflict, load_enterprise_referrals
    first = load_enterprise_referrals(db, count=1_000, seed=42)
    assert first == {'rows': 1_000, 'inserted': 1_000}
    assert load_enterprise_referrals(db, count=1_000, seed=42) == {'rows': 1_000, 'inserted': 0}
    original = db.execute('SELECT status FROM referral WHERE referral_id = 5000001').fetchone()[0]
    replacement = 'lost' if original != 'lost' else 'expired'
    db.execute('UPDATE referral SET status = %s WHERE referral_id = 5000001', (replacement,))
    with pytest.raises(ReferralConflict):
        load_enterprise_referrals(db, count=1_000, seed=42)
