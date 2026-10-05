"""Deterministic synthetic referral demand at practice/specialty grain."""
from collections import Counter
from datetime import date, timedelta
import hashlib
import random

from src.enterprise_operations import START_DATE, END_DATE, dates
from src.enterprise_reference import generate_enterprise_reference_data, validate_enterprise_reference_data

DEFAULT_COUNT = 50_000
MIN_REFERRAL_ID = 5_000_001
STATUSES = ('received', 'scheduled', 'completed', 'expired', 'lost')
SOURCES = ('internal', 'external_primary_care', 'specialist', 'self_referred',
           'hospital_discharge', 'other')
FIELDS = ('referral_id', 'practice_id', 'specialty_id', 'referral_date',
          'scheduled_date', 'referral_source', 'status')
STATUS_WEIGHTS = (('received', 12), ('scheduled', 26), ('completed', 42),
                  ('expired', 10), ('lost', 10))
SOURCE_WEIGHTS = (('internal', 34), ('external_primary_care', 28), ('specialist', 16),
                  ('self_referred', 10), ('hospital_discharge', 8), ('other', 4))


def _rng(seed, *parts):
    digest = hashlib.sha256('|'.join(map(str, (seed, *parts))).encode()).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def generate_referrals(count=DEFAULT_COUNT, seed=42, reference=None, start=START_DATE, end=END_DATE):
    if type(count) is not int or not 1 <= count <= 250_000:
        raise ValueError('count must be between 1 and 250,000')
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    days = dates(start, end)
    practices = sorted(reference['practice'], key=lambda p: p['practice_id'])
    specialties = sorted(reference['specialty'], key=lambda s: s['specialty_id'])
    rows = []
    for index in range(count):
        rng = _rng(seed, 'referral', index)
        practice = practices[(index + rng.randrange(len(practices))) % len(practices)]
        specialty = specialties[(index * 3 + rng.randrange(len(specialties))) % len(specialties)]
        referral_date = days[rng.randrange(len(days))]
        status = rng.choices([x[0] for x in STATUS_WEIGHTS], weights=[x[1] for x in STATUS_WEIGHTS], k=1)[0]
        scheduled_date = None
        if status in ('scheduled', 'completed'):
            scheduled_date = referral_date + timedelta(days=rng.randint(3, 55))
        source = rng.choices([x[0] for x in SOURCE_WEIGHTS], weights=[x[1] for x in SOURCE_WEIGHTS], k=1)[0]
        rows.append(dict(referral_id=MIN_REFERRAL_ID + index, practice_id=practice['practice_id'],
                         specialty_id=specialty['specialty_id'], referral_date=referral_date.isoformat(),
                         scheduled_date=None if scheduled_date is None else scheduled_date.isoformat(),
                         referral_source=source, status=status))
    validate_referrals(rows, reference, start, end)
    return rows


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_referrals(rows, reference=None, start=START_DATE, end=END_DATE):
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    _require(isinstance(rows, list) and rows, 'At least one referral row is required')
    practices = {p['practice_id'] for p in reference['practice']}
    specialties = {s['specialty_id'] for s in reference['specialty']}
    ids, statuses = set(), Counter()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == set(FIELDS), 'Unexpected referral fields')
        _require(type(row['referral_id']) is int and row['referral_id'] >= MIN_REFERRAL_ID, 'Invalid referral_id')
        _require(row['referral_id'] not in ids, 'Duplicate referral_id')
        ids.add(row['referral_id'])
        _require(row['practice_id'] in practices and row['specialty_id'] in specialties, 'Invalid referral reference')
        referral_date = date.fromisoformat(row['referral_date'])
        _require(start <= referral_date <= end, 'Referral date outside generation window')
        if row['scheduled_date'] is not None:
            _require(date.fromisoformat(row['scheduled_date']) >= referral_date, 'Scheduled date precedes referral')
        _require(row['referral_source'] in SOURCES and row['status'] in STATUSES, 'Invalid referral catalog value')
        _require(row['status'] not in ('scheduled', 'completed') or row['scheduled_date'] is not None,
                 'Converted referrals require scheduled_date')
        statuses[row['status']] += 1
    return {'count': len(rows), 'status_counts': dict(statuses)}
