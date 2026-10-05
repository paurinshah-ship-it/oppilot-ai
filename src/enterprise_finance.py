"""Synthetic encounter and payment facts derived from completed appointments."""
from collections import Counter
from datetime import date, timedelta
import math
import random

from src.enterprise_appointments import (DEFAULT_COUNT, PAYER_CATEGORIES,
    START_DATE, END_DATE, generate_appointment_events)
from src.enterprise_reference import generate_enterprise_reference_data, validate_enterprise_reference_data

MIN_ENCOUNTER_ID = 3_000_001
MIN_PAYMENT_ID = 4_000_001
VISIT_TYPES = ('new_patient', 'follow_up', 'annual', 'procedure', 'consult', 'urgent', 'telehealth')
FIELDS = {
    'encounter': ('encounter_id', 'appointment_id', 'provider_id', 'practice_id',
                  'encounter_date', 'visit_type', 'work_rvu', 'modeled_charge', 'allowed_amount'),
    'payment': ('payment_id', 'encounter_id', 'payment_date', 'payer_category',
                'allowed_amount', 'paid_amount', 'patient_amount', 'adjustment_amount'),
}
RVU_RANGES = {
    'new_patient': (1.6, 3.2), 'follow_up': (.7, 1.8), 'annual': (1.2, 2.1),
    'procedure': (2.4, 5.8), 'consult': (1.8, 3.6), 'urgent': (1.1, 2.4),
    'telehealth': (.6, 1.5),
}
PAYER_ALLOWED_FACTORS = {'Commercial': (.48, .68), 'Medicare': (.36, .52),
                         'Medicaid': (.28, .43), 'Self Pay': (.22, .58), 'Other': (.30, .60)}
PAYER_LAGS = {'Commercial': (14, 45), 'Medicare': (12, 38), 'Medicaid': (21, 60),
              'Self Pay': (0, 90), 'Other': (7, 75)}
PAYER_PATIENT_SHARE = {'Commercial': (.05, .22), 'Medicare': (.02, .12),
                       'Medicaid': (0, .04), 'Self Pay': (.45, 1.0), 'Other': (.08, .30)}


def _rng(seed, *parts):
    return random.Random('|'.join(map(str, (seed, *parts))))


def _encounter_from_event(event, encounter_id, seed):
    rng = _rng(seed, 'encounter', event['appointment_id'])
    low, high = RVU_RANGES[event['appointment_type']]
    work_rvu = round(rng.uniform(low, high), 3)
    modeled_charge = round(work_rvu * rng.uniform(185, 275), 2)
    factor_low, factor_high = PAYER_ALLOWED_FACTORS[event['payer_category']]
    allowed = round(min(modeled_charge, modeled_charge * rng.uniform(factor_low, factor_high)), 2)
    return dict(encounter_id=encounter_id, appointment_id=event['appointment_id'],
                provider_id=event['provider_id'], practice_id=event['practice_id'],
                encounter_date=event['appointment_date'], visit_type=event['appointment_type'],
                work_rvu=work_rvu, modeled_charge=modeled_charge, allowed_amount=allowed)


def _payment_from_encounter(encounter, event, payment_id, seed):
    rng = _rng(seed, 'payment', encounter['encounter_id'])
    low, high = PAYER_LAGS[event['payer_category']]
    payment_date = date.fromisoformat(encounter['encounter_date']) + timedelta(days=rng.randint(low, high))
    share_low, share_high = PAYER_PATIENT_SHARE[event['payer_category']]
    patient = round(encounter['allowed_amount'] * rng.uniform(share_low, share_high), 2)
    paid = round(max(0, encounter['allowed_amount'] - patient), 2)
    adjustment = round(max(0, encounter['modeled_charge'] - encounter['allowed_amount']), 2)
    return dict(payment_id=payment_id, encounter_id=encounter['encounter_id'],
                payment_date=payment_date.isoformat(), payer_category=event['payer_category'],
                allowed_amount=encounter['allowed_amount'], paid_amount=paid,
                patient_amount=patient, adjustment_amount=adjustment)


def generate_encounter_payment_pairs(count=DEFAULT_COUNT, seed=42, reference=None,
                                     start=START_DATE, end=END_DATE):
    """Stream one encounter and one payment for each completed appointment event."""
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    encounter_offset = 0
    for event in generate_appointment_events(count=count, seed=seed, reference=reference, start=start, end=end):
        if event['appointment_status'] != 'completed':
            continue
        encounter = _encounter_from_event(event, MIN_ENCOUNTER_ID + encounter_offset, seed)
        payment = _payment_from_encounter(encounter, event, MIN_PAYMENT_ID + encounter_offset, seed)
        encounter_offset += 1
        yield encounter, payment


def generate_enterprise_finance(count=DEFAULT_COUNT, seed=42, reference=None,
                                start=START_DATE, end=END_DATE):
    rows = {'encounter': [], 'payment': []}
    for encounter, payment in generate_encounter_payment_pairs(count, seed, reference, start, end):
        rows['encounter'].append(encounter)
        rows['payment'].append(payment)
    validate_enterprise_finance(rows, reference)
    return rows


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _validate_row_shape(table, rows, keys):
    seen = set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == set(FIELDS[table]), f'Unexpected {table} fields')
        key = tuple(row[k] for k in keys)
        _require(key not in seen, f'Duplicate {table} key')
        seen.add(key)
    return seen


def validate_enterprise_finance(data, reference=None):
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    _require(isinstance(data, dict) and set(data) == set(FIELDS), 'Expected encounter and payment rows')
    _validate_row_shape('encounter', data['encounter'], ('encounter_id',))
    appointment_ids = _validate_row_shape('encounter', data['encounter'], ('appointment_id',))
    payment_ids = _validate_row_shape('payment', data['payment'], ('payment_id',))
    _require(len(data['payment']) == len(data['encounter']) == len(payment_ids), 'Expected one payment per encounter')
    providers = {p['provider_id']: p for p in reference['provider']}
    encounters = {e['encounter_id']: e for e in data['encounter']}
    _require(len(appointment_ids) == len(data['encounter']), 'Expected one encounter per appointment')
    for row in data['encounter']:
        _require(type(row['encounter_id']) is int and row['encounter_id'] >= MIN_ENCOUNTER_ID, 'Invalid encounter_id')
        _require(type(row['appointment_id']) is int, 'Invalid appointment_id')
        provider = providers.get(row['provider_id'])
        _require(provider is not None and provider['practice_id'] == row['practice_id'], 'Invalid encounter provider/practice')
        _require(row['visit_type'] in VISIT_TYPES, 'Invalid visit_type')
        for column in ('work_rvu', 'modeled_charge', 'allowed_amount'):
            value = row[column]
            _require(type(value) in (int, float) and math.isfinite(value) and value >= 0, f'Invalid {column}')
        _require(row['allowed_amount'] <= row['modeled_charge'] + 1e-7, 'Allowed amount exceeds modeled charge')
    for row in data['payment']:
        _require(type(row['payment_id']) is int and row['payment_id'] >= MIN_PAYMENT_ID, 'Invalid payment_id')
        encounter = encounters.get(row['encounter_id'])
        _require(encounter is not None, 'Invalid payment encounter')
        _require(row['payer_category'] in PAYER_CATEGORIES, 'Invalid payer_category')
        _require(date.fromisoformat(row['payment_date']) >=
                 date.fromisoformat(encounter['encounter_date']), 'Payment precedes encounter')
        for column in ('allowed_amount', 'paid_amount', 'patient_amount', 'adjustment_amount'):
            value = row[column]
            _require(type(value) in (int, float) and math.isfinite(value) and value >= 0, f'Invalid payment {column}')
        _require(abs(row['allowed_amount'] - encounter['allowed_amount']) < .005, 'Payment allowed amount mismatch')
        _require(row['paid_amount'] + row['patient_amount'] <= row['allowed_amount'] + .015, 'Payment exceeds allowed amount')
    return {'counts': {table: len(rows) for table, rows in data.items()},
            'payment_lag_days': _payment_lag_stats(data)}


def _payment_lag_stats(data):
    encounters = {e['encounter_id']: e for e in data['encounter']}
    lags = [(date.fromisoformat(p['payment_date']) -
             date.fromisoformat(encounters[p['encounter_id']]['encounter_date'])).days
            for p in data['payment']]
    if not lags:
        return {'min': None, 'max': None, 'mean': None}
    return {'min': min(lags), 'max': max(lags), 'mean': round(sum(lags) / len(lags), 2)}
