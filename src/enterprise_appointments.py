"""Deterministic, synthetic event-grain enterprise appointment baseline.

Streaming generation keeps the million-event path bounded by provider fixtures,
not by event count. Events have no patient or clinical attributes.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import math
import random

from src.data import SPECIALTIES
from src.enterprise_reference import generate_enterprise_reference_data, validate_enterprise_reference_data

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)
DEFAULT_COUNT = 1_000_000
MIN_APPOINTMENT_ID = 2_000_001
STATUSES = ('completed', 'no_show', 'cancelled', 'cancelled_patient', 'cancelled_provider', 'cancelled_practice', 'rescheduled')
APPOINTMENT_TYPES = ('new_patient', 'follow_up', 'annual', 'procedure', 'consult', 'urgent', 'telehealth')
PAYER_CATEGORIES = ('Commercial', 'Medicare', 'Medicaid', 'Self Pay', 'Other')
SLOT_DURATIONS = (15, 20, 30, 45, 60)
FIELDS = ('appointment_id', 'provider_id', 'appointment_date', 'appointment_status', 'modeled_revenue',
          'practice_id', 'appointment_type', 'scheduled_at', 'slot_duration_minutes', 'payer_category')
LEGACY_FIELDS = FIELDS[:5]

TYPE_WEIGHTS = {
    'Primary Care': (('new_patient', 22), ('follow_up', 34), ('annual', 18), ('urgent', 8), ('telehealth', 18)),
    'Cardiology': (('new_patient', 12), ('follow_up', 38), ('procedure', 14), ('consult', 22), ('urgent', 5), ('telehealth', 9)),
    'Dermatology': (('new_patient', 20), ('follow_up', 30), ('procedure', 15), ('consult', 15), ('urgent', 5), ('telehealth', 15)),
    'Orthopedics': (('new_patient', 17), ('follow_up', 35), ('procedure', 16), ('consult', 23), ('urgent', 5), ('telehealth', 4)),
    'Neurology': (('new_patient', 17), ('follow_up', 37), ('consult', 25), ('urgent', 6), ('telehealth', 15)),
    'Gastroenterology': (('new_patient', 16), ('follow_up', 34), ('procedure', 20), ('consult', 21), ('urgent', 4), ('telehealth', 5)),
    'Endocrinology': (('new_patient', 23), ('follow_up', 40), ('annual', 16), ('consult', 8), ('telehealth', 13)),
    'Pulmonology': (('new_patient', 19), ('follow_up', 36), ('consult', 18), ('urgent', 7), ('telehealth', 20)),
    'Rheumatology': (('new_patient', 19), ('follow_up', 39), ('consult', 24), ('urgent', 4), ('telehealth', 14)),
    'Urology': (('new_patient', 18), ('follow_up', 34), ('procedure', 18), ('consult', 20), ('urgent', 5), ('telehealth', 5)),
    'Ophthalmology': (('new_patient', 12), ('follow_up', 29), ('annual', 34), ('procedure', 18), ('urgent', 2), ('telehealth', 5)),
    'Otolaryngology': (('new_patient', 18), ('follow_up', 31), ('procedure', 14), ('consult', 24), ('urgent', 5), ('telehealth', 8)),
}
LEAD_DAYS = {'urgent': (1, 3), 'follow_up': (7, 35), 'new_patient': (14, 60),
             'annual': (14, 60), 'procedure': (7, 42), 'consult': (21, 75), 'telehealth': (2, 21)}
DURATIONS = {'new_patient': (30, 45, 60), 'follow_up': (15, 20, 30), 'annual': (30, 45),
             'procedure': (30, 45, 60), 'consult': (30, 45, 60), 'urgent': (15, 20, 30),
             'telehealth': (15, 20, 30)}
PAYER_WEIGHTS = (('Commercial', 52), ('Medicare', 23), ('Medicaid', 14), ('Self Pay', 7), ('Other', 4))
# Splitting the old 11% cancellation share preserves aggregate status weights.
STATUS_WEIGHTS = (('completed', 78), ('no_show', 11), ('cancelled', 5.5),
                  ('cancelled_patient', 3.3), ('cancelled_provider', 1.32),
                  ('cancelled_practice', .66), ('rescheduled', .22))


def _business_dates(start=START_DATE, end=END_DATE):
    if type(start) is not date or type(end) is not date or not START_DATE <= start <= end <= END_DATE:
        raise ValueError('Choose an inclusive window within 2024-01-01 through 2025-12-31')
    return [start + timedelta(days=i) for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5]


def _reference_maps(reference):
    specialties = {s['specialty_id']: s['specialty_name'] for s in reference['specialty']}
    providers = sorted(reference['provider'], key=lambda p: p['provider_id'])
    provider_lookup = {p['provider_id']: p for p in providers}
    specialty_by_provider = {p['provider_id']: specialties[p['specialty_id']] for p in providers}
    practice_by_provider = {p['provider_id']: p['practice_id'] for p in providers}
    return providers, provider_lookup, specialty_by_provider, practice_by_provider


def _event(index, rng, providers, practice_by_provider, specialty_by_provider, daily_rates, service_dates):
    provider = providers[index % len(providers)]
    appointment_date = service_dates[rng.randrange(len(service_dates))]
    specialty = specialty_by_provider[provider['provider_id']]
    appt_type = rng.choices([x[0] for x in TYPE_WEIGHTS[specialty]],
                            weights=[x[1] for x in TYPE_WEIGHTS[specialty]], k=1)[0]
    low, high = LEAD_DAYS[appt_type]
    scheduled_date = appointment_date - timedelta(days=rng.randint(low, high))
    hour = rng.randint(8, 16)
    minute = rng.choice((0, 15, 30, 45)) if hour < 16 else rng.choice((0, 15))
    scheduled_at = datetime.combine(scheduled_date, time(hour, minute), tzinfo=timezone.utc)
    status = rng.choices([x[0] for x in STATUS_WEIGHTS], weights=[x[1] for x in STATUS_WEIGHTS], k=1)[0]
    revenue = round(daily_rates[specialty] * rng.uniform(.9, 1.1), 2) if status == 'completed' else 0.0
    return dict(appointment_id=MIN_APPOINTMENT_ID + index, provider_id=provider['provider_id'],
                appointment_date=appointment_date.isoformat(), appointment_status=status,
                modeled_revenue=revenue, practice_id=practice_by_provider[provider['provider_id']],
                appointment_type=appt_type, scheduled_at=scheduled_at,
                slot_duration_minutes=rng.choice(DURATIONS[appt_type]),
                payer_category=rng.choices([x[0] for x in PAYER_WEIGHTS], weights=[x[1] for x in PAYER_WEIGHTS], k=1)[0])


def generate_appointment_events(count=DEFAULT_COUNT, seed=42, reference=None, start=START_DATE, end=END_DATE):
    """Stream stable synthetic events. Use ``itertools.islice`` for small samples."""
    if type(count) is not int or not 1 <= count <= DEFAULT_COUNT:
        raise ValueError(f'count must be between 1 and {DEFAULT_COUNT:,}')
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    providers, _, specialty_by_provider, practice_by_provider = _reference_maps(reference)
    if not providers:
        raise ValueError('At least one enterprise provider is required')
    service_dates = _business_dates(start, end)
    rates = {name: rate for name, rate, _ in SPECIALTIES}
    rng = random.Random(seed)
    return (_event(i, rng, providers, practice_by_provider, specialty_by_provider, rates, service_dates)
            for i in range(count))


def _validate_row(row, reference, expected_id=None, provider_lookup=None):
    if not isinstance(row, dict) or set(row) != set(FIELDS):
        raise ValueError('Appointment event fields do not match the approved schema')
    if type(row['appointment_id']) is not int or row['appointment_id'] < MIN_APPOINTMENT_ID:
        raise ValueError('Invalid synthetic appointment ID')
    if expected_id is not None and row['appointment_id'] != expected_id:
        raise ValueError('Appointment IDs must be unique and sequential')
    if provider_lookup is None:
        provider_lookup = {p['provider_id']: p for p in reference['provider']}
    provider = provider_lookup.get(row['provider_id'])
    if provider is None or provider['practice_id'] != row['practice_id']:
        raise ValueError('Invalid or inconsistent provider/practice relationship')
    if row['appointment_status'] not in STATUSES:
        raise ValueError('Invalid appointment status')
    if row['appointment_type'] not in APPOINTMENT_TYPES:
        raise ValueError('Invalid appointment type')
    if row['payer_category'] not in PAYER_CATEGORIES:
        raise ValueError('Invalid payer category')
    appt_date = date.fromisoformat(row['appointment_date'])
    if appt_date.weekday() >= 5:
        raise ValueError('Enterprise appointments must fall on weekdays')
    scheduled = row['scheduled_at']
    if not isinstance(scheduled, datetime) or scheduled.tzinfo is None or scheduled.utcoffset() != timedelta(0):
        raise ValueError('scheduled_at must be a UTC timestamp')
    if scheduled.date() >= appt_date:
        raise ValueError('scheduled_at must precede appointment_date')
    if type(row['slot_duration_minutes']) is not int or row['slot_duration_minutes'] not in SLOT_DURATIONS:
        raise ValueError('Invalid slot duration')
    revenue = row['modeled_revenue']
    if type(revenue) not in (int, float) or not math.isfinite(revenue) or revenue < 0:
        raise ValueError('modeled_revenue must be finite and nonnegative')
    if row['appointment_status'] != 'completed' and revenue != 0:
        raise ValueError('Only completed appointments have modeled revenue')
    return row


def validate_appointment_events(rows, reference=None):
    """Validate any iterable once; returns count and exact generated distribution."""
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    provider_lookup = {p['provider_id']: p for p in reference['provider']}
    ids, statuses = set(), Counter()
    for row in rows:
        _validate_row(row, reference, provider_lookup=provider_lookup)
        if row['appointment_id'] in ids:
            raise ValueError('Duplicate appointment_id')
        ids.add(row['appointment_id'])
        statuses[row['appointment_status']] += 1
    if not ids:
        raise ValueError('At least one appointment event is required')
    return {'count': len(ids), 'status_counts': dict(statuses)}
