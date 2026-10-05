"""Synthetic operational baseline, independent of legacy provider-day analytics."""
from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
import math
import random

from src.data import SPECIALTIES
from src.enterprise_reference import generate_enterprise_reference_data, validate_enterprise_reference_data

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 12, 31)
SEED = 42
ROLES = ('Medical Assistant', 'RN', 'LPN', 'Front Desk', 'Scheduler',
         'Practice Manager', 'Referral Coordinator', 'Billing Specialist')
# Illustrative nominal dollars/hour, not market compensation estimates.
COST_RANGES = ((20, 29), (34, 47), (25, 34), (18, 25), (20, 28), (34, 48), (23, 31), (24, 34))
FIELDS = {
    'employee': ('employee_id', 'practice_id', 'role', 'fte', 'hourly_cost', 'hire_date', 'termination_date', 'status'),
    'provider_capacity': ('provider_id', 'capacity_date', 'scheduled_hours', 'clinical_hours',
                          'available_slots', 'blocked_slots', 'pto_hours', 'admin_hours'),
    'staffing_daily': ('practice_id', 'staff_date', 'role', 'budgeted_fte', 'scheduled_fte',
                       'actual_fte', 'overtime_hours', 'agency_hours', 'absence_hours'),
}


def _rng(*parts):
    # Stable per-entity/day streams: short windows exactly match full-run slices.
    digest = hashlib.sha256('|'.join(map(str, (SEED, *parts))).encode()).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def dates(start=START_DATE, end=END_DATE):
    if type(start) is not date or type(end) is not date or not START_DATE <= start <= end <= END_DATE:
        raise ValueError('Choose an inclusive window within 2024-01-01 through 2025-12-31')
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def generate_employees(reference=None):
    """Fixed active baseline roster: no identities beyond synthetic numeric IDs."""
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    counts = Counter(p['practice_id'] for p in reference['provider'])
    rows = []
    for practice in sorted(reference['practice'], key=lambda p: p['practice_id']):
        practice_id = practice['practice_id']
        n = counts[practice_id]
        opening = date.fromisoformat(practice['opening_date'])
        # MAs scale with provider count; larger practices have more RNs/billers.
        headcounts = (n + 1, 3 if n >= 8 else 2, 1, 3, 2, 1, 1, 2 if n >= 8 else 1)
        for role_index, (role, count) in enumerate(zip(ROLES, headcounts)):
            for slot in range(count):
                employee_id = 1_000_000 + (practice_id - 10001) * 1000 + role_index * 100 + slot
                rng = _rng('employee', employee_id)
                low, high = COST_RANGES[role_index]
                rows.append(dict(employee_id=employee_id, practice_id=practice_id, role=role,
                                 fte=1.0 if role == 'Practice Manager' else rng.choice((.6, .8, 1., 1., 1.)),
                                 hourly_cost=rng.randint(low * 100, high * 100) / 100,
                                 hire_date=(opening + timedelta(days=rng.randrange((START_DATE - opening).days))).isoformat(),
                                 termination_date=None, status='active'))
    return rows


def generate_provider_capacity(reference=None, start=START_DATE, end=END_DATE):
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    days = dates(start, end)
    specialties = {s['specialty_id']: s['specialty_name'] for s in reference['specialty']}
    rates = {name: slots / 7 for name, _, slots in SPECIALTIES}
    rows = []
    for provider in sorted(reference['provider'], key=lambda p: p['provider_id']):
        identifier = provider['provider_id']
        profile = _rng('provider_profile', identifier)
        hours = profile.choice((6.4, 8., 8., 8.))
        off_day = profile.randrange(5) if profile.random() < .15 else None
        admin_baseline = profile.choice((.75, 1., 1.25))
        slot_rate = rates[specialties[provider['specialty_id']]] * profile.choice((.9, 1., 1.1))
        for day in days:
            rng = _rng('capacity', identifier, day)
            scheduled = hours if day.weekday() < 5 and day.weekday() != off_day else 0.
            pto = scheduled if scheduled and rng.random() < .04 else 0.
            admin = min(scheduled, admin_baseline) if scheduled and not pto else 0.
            clinical = round(scheduled - pto - admin, 2)
            gross_slots = math.floor(clinical * slot_rate)
            blocked = min(gross_slots, rng.choice((0, 0, 0, 1, 2))) if gross_slots else 0
            rows.append(dict(provider_id=identifier, capacity_date=day.isoformat(), scheduled_hours=scheduled,
                             clinical_hours=clinical, available_slots=gross_slots - blocked,
                             blocked_slots=blocked, pto_hours=pto, admin_hours=admin))
    return rows


def generate_staffing_daily(reference=None, employees=None, start=START_DATE, end=END_DATE):
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    employees = generate_employees(reference) if employees is None else employees
    _validate_employees(employees, reference)
    days = dates(start, end)
    roster = defaultdict(list)
    for employee in employees:
        roster[employee['practice_id'], employee['role']].append(employee)
    rows = []
    for practice in sorted(reference['practice'], key=lambda p: p['practice_id']):
        for role in ROLES:
            group = sorted(roster[practice['practice_id'], role], key=lambda e: e['employee_id'])
            # Budget uses the contracted baseline roster; FTE is an 8-hour day.
            budget_units = sum(round(e['fte'] * 100) for e in group)
            for day in days:
                rng = _rng('staffing', practice['practice_id'], role, day)
                scheduled_units = 0
                absence_units = 0
                if day.weekday() < 5:
                    for employee in group:
                        if employee['hire_date'] > day.isoformat() or (employee['termination_date'] is not None and employee['termination_date'] <= day.isoformat()):
                            continue
                        # Routine planned leave (3%) and unplanned absence (2%).
                        if rng.random() >= .03:
                            units = round(employee['fte'] * 100)
                            scheduled_units += units
                            if rng.random() < .02:
                                absence_units += units
                budget = budget_units / 100 if day.weekday() < 5 else 0.
                scheduled = scheduled_units / 100
                actual = (scheduled_units - absence_units) / 100
                absence = absence_units * 8 / 100
                gap_hours = round((budget - actual) * 8, 2)
                # Replacement hours are separate from regular-staff actual_fte.
                overtime = round(min(gap_hours * rng.choice((0., .25, .5)), actual * 2), 2)
                remaining = round(max(0., gap_hours - overtime), 2)
                agency = round(min(8., remaining), 2) if remaining and role in ('Medical Assistant', 'RN', 'LPN') and rng.random() < .08 else 0.
                rows.append(dict(practice_id=practice['practice_id'], staff_date=day.isoformat(), role=role,
                                 budgeted_fte=budget, scheduled_fte=scheduled, actual_fte=actual,
                                 overtime_hours=overtime, agency_hours=agency, absence_hours=absence))
    return rows


def generate_enterprise_operations(start=START_DATE, end=END_DATE):
    reference = generate_enterprise_reference_data()
    employees = generate_employees(reference)
    data = {'employee': employees,
            'provider_capacity': generate_provider_capacity(reference, start, end),
            'staffing_daily': generate_staffing_daily(reference, employees, start, end)}
    validate_enterprise_operations(data, reference, start, end)
    return data


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _rows(rows, table, key_columns, numeric_columns):
    _require(isinstance(rows, list), f'{table} must be a list')
    seen = set()
    for row in rows:
        _require(isinstance(row, dict) and set(row) == set(FIELDS[table]), f'Unexpected {table} fields')
        key = tuple(row[column] for column in key_columns)
        _require(key not in seen, f'Duplicate {table} key')
        seen.add(key)
        for column in numeric_columns:
            value = row[column]
            _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                     f'Invalid {table}.{column}')
            _require(abs(value * 100 - round(value * 100)) < 1e-7, f'Precision exceeds schema for {table}.{column}')
    return seen


def _validate_employees(rows, reference):
    _require(450 <= len(rows) <= 500, 'Expected 450–500 employees')
    _rows(rows, 'employee', ('employee_id',), ('fte', 'hourly_cost'))
    practices = {p['practice_id']: p for p in reference['practice']}
    for row in rows:
        _require(type(row['employee_id']) is int and 1_000_000 <= row['employee_id'] < 1_025_000, 'Invalid synthetic employee ID')
        _require(row['practice_id'] in practices and row['role'] in ROLES, 'Invalid employee practice/role')
        _require(.5 <= row['fte'] <= 1 and 15 <= row['hourly_cost'] <= 60, 'Implausible FTE or hourly cost')
        hire = date.fromisoformat(row['hire_date'])
        termination = None if row['termination_date'] is None else date.fromisoformat(row['termination_date'])
        _require(row['status'] in ('active', 'on_leave', 'terminated'), 'Invalid employee status')
        _require((row['status'] == 'terminated') == (termination is not None), 'Status/date mismatch')
        _require(termination is None or termination >= hire, 'Termination precedes hire')
        _require(date.fromisoformat(practices[row['practice_id']]['opening_date']) <= hire < START_DATE, 'Hire outside active baseline')
    _require({(r['practice_id'], r['role']) for r in rows} == {(p, role) for p in practices for role in ROLES},
             'Every practice must have every operational role')


def validate_enterprise_operations(data, reference=None, start=START_DATE, end=END_DATE):
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    days = {d.isoformat() for d in dates(start, end)}
    _require(isinstance(data, dict) and set(data) == set(FIELDS), 'Expected only employee, capacity and staffing')
    _validate_employees(data['employee'], reference)
    providers = {p['provider_id'] for p in reference['provider']}
    practices = {p['practice_id'] for p in reference['practice']}
    capacity_fields = FIELDS['provider_capacity'][2:]
    keys = _rows(data['provider_capacity'], 'provider_capacity', ('provider_id', 'capacity_date'), capacity_fields)
    _require(len(keys) == len(providers) * len(days), 'Incomplete capacity coverage')
    for row in data['provider_capacity']:
        _require(row['provider_id'] in providers and row['capacity_date'] in days, 'Invalid capacity provider/date')
        _require(abs(row['scheduled_hours'] - sum(row[k] for k in ('clinical_hours', 'admin_hours', 'pto_hours'))) < 1e-7, 'Capacity hours do not balance')
        _require(row['scheduled_hours'] <= 8, 'Capacity exceeds eight-hour baseline')
        slots = row['available_slots'] + row['blocked_slots']
        _require(all(type(row[k]) is int for k in ('available_slots', 'blocked_slots')), 'Slots must be integers')
        _require(slots <= math.ceil(row['clinical_hours'] * 5), 'Slots exceed plausible clinical capacity')
        if date.fromisoformat(row['capacity_date']).weekday() >= 5:
            _require(all(row[k] == 0 for k in capacity_fields), 'Baseline weekends must be closed')
    staffing_fields = FIELDS['staffing_daily'][3:]
    keys = _rows(data['staffing_daily'], 'staffing_daily', ('practice_id', 'staff_date', 'role'), staffing_fields)
    _require(len(keys) == len(practices) * len(days) * len(ROLES), 'Incomplete staffing coverage')
    budgets = defaultdict(float)
    for employee in data['employee']:
        budgets[employee['practice_id'], employee['role']] += employee['fte']
    for row in data['staffing_daily']:
        _require(row['practice_id'] in practices and row['staff_date'] in days and row['role'] in ROLES, 'Invalid staffing key')
        weekday = date.fromisoformat(row['staff_date']).weekday() < 5
        expected_budget = round(budgets[row['practice_id'], row['role']], 2) if weekday else 0
        _require(abs(row['budgeted_fte'] - expected_budget) < 1e-7, 'Budget does not match employee roster')
        _require(row['actual_fte'] <= row['scheduled_fte'] <= row['budgeted_fte'], 'Invalid staffing FTE relationship')
        _require(abs((row['scheduled_fte'] - row['actual_fte']) * 8 - row['absence_hours']) < 1e-7, 'Absence does not reconcile')
        gap = (row['budgeted_fte'] - row['actual_fte']) * 8
        _require(row['overtime_hours'] <= row['actual_fte'] * 2 + 1e-7, 'Excessive overtime')
        _require(row['agency_hours'] <= 8 and row['overtime_hours'] + row['agency_hours'] <= gap + 1e-7, 'Replacement hours exceed gap')
        if not weekday:
            _require(all(row[k] == 0 for k in staffing_fields), 'Baseline weekends must be closed')
