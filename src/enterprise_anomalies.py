"""Deterministic anomaly injection for synthetic enterprise evaluation data."""
from dataclasses import dataclass
from datetime import date, timedelta
import copy
import math

from src.enterprise_appointments import DEFAULT_COUNT, generate_appointment_events
from src.enterprise_finance import generate_enterprise_finance, validate_enterprise_finance
from src.enterprise_operations import generate_enterprise_operations, validate_enterprise_operations
from src.enterprise_reference import generate_enterprise_reference_data, validate_enterprise_reference_data
from src.enterprise_referrals import FIELDS as REFERRAL_FIELDS, generate_referrals, validate_referrals

ANOMALY_TYPES = (
    'MA_STAFFING_SHORTAGE',
    'PROVIDER_PTO_CAPACITY_REDUCTION',
    'NO_SHOW_SPIKE',
    'REFERRAL_DEMAND_SURGE',
    'SCHEDULING_TEMPLATE_CAPACITY_REDUCTION',
    'REVENUE_PER_VISIT_DECLINE',
)
SEVERITIES = ('low', 'medium', 'high')
EXPECTED_DIRECTIONS = ('increase', 'decrease')
GROUND_TRUTH_FIELDS = ('anomaly_id', 'practice_id', 'start_date', 'end_date',
                       'anomaly_type', 'affected_metric', 'expected_direction',
                       'severity', 'description')


@dataclass(frozen=True)
class AnomalyDefinition:
    anomaly_id: int
    practice_id: int
    start_date: str
    end_date: str
    anomaly_type: str
    affected_metric: str
    expected_direction: str
    severity: str
    intensity: float
    description: str
    provider_id: str | None = None
    specialty_id: int | None = None


PORTFOLIO_DEMO = (
    AnomalyDefinition(900001, 10003, '2024-03-04', '2024-03-29', 'MA_STAFFING_SHORTAGE', 'actual_fte', 'decrease', 'medium', .35, 'Root cause: temporary MA staffing shortage; expected lower MA actual_fte and higher absence/overtime coverage.'),
    AnomalyDefinition(900002, 10018, '2025-02-03', '2025-02-21', 'MA_STAFFING_SHORTAGE', 'actual_fte', 'decrease', 'high', .50, 'Root cause: concentrated MA vacancy; expected lower MA actual_fte with limited agency backfill.'),
    AnomalyDefinition(900003, 10006, '2024-07-08', '2024-07-19', 'PROVIDER_PTO_CAPACITY_REDUCTION', 'clinical_hours', 'decrease', 'medium', .50, 'Root cause: provider PTO block; expected higher pto_hours and lower clinical capacity.', 'SYN-002'),
    AnomalyDefinition(900004, 10021, '2025-08-04', '2025-08-15', 'PROVIDER_PTO_CAPACITY_REDUCTION', 'clinical_hours', 'decrease', 'medium', .40, 'Root cause: provider PTO block; expected lower slots through reduced clinical hours.', 'SYN-005'),
    AnomalyDefinition(900005, 10011, '2024-10-07', '2024-10-25', 'NO_SHOW_SPIKE', 'no_show_rate', 'increase', 'high', .28, 'Root cause: appointment reminder failure; expected higher no_show share with completed events converted to no_show.'),
    AnomalyDefinition(900006, 10024, '2025-04-07', '2025-04-25', 'NO_SHOW_SPIKE', 'no_show_rate', 'increase', 'medium', .20, 'Root cause: access communication issue; expected higher no_show share without changing denominator semantics.'),
    AnomalyDefinition(900007, 10008, '2024-05-06', '2024-05-31', 'REFERRAL_DEMAND_SURGE', 'referral_volume', 'increase', 'high', 160, 'Root cause: synthetic market demand surge; expected higher referral volume for one practice/specialty.', specialty_id=4),
    AnomalyDefinition(900008, 10017, '2025-09-02', '2025-09-30', 'REFERRAL_DEMAND_SURGE', 'referral_volume', 'increase', 'medium', 120, 'Root cause: synthetic referral campaign; expected higher scheduled referral demand.', specialty_id=8),
    AnomalyDefinition(900009, 10014, '2024-11-04', '2024-11-22', 'SCHEDULING_TEMPLATE_CAPACITY_REDUCTION', 'blocked_slots', 'increase', 'medium', 3, 'Root cause: scheduling template misconfiguration; expected higher blocked slots with clinical hours unchanged.'),
    AnomalyDefinition(900010, 10022, '2025-06-02', '2025-06-27', 'REVENUE_PER_VISIT_DECLINE', 'allowed_amount', 'decrease', 'high', .22, 'Root cause: synthetic payer configuration issue; expected lower allowed and paid amounts without lower encounter volume.'),
)
PROFILES = {'portfolio_demo': PORTFOLIO_DEMO}


def generate_enterprise_dataset(appointment_count=DEFAULT_COUNT, referral_count=50_000,
                                seed=42, start=None, end=None):
    reference = generate_enterprise_reference_data()
    operations = generate_enterprise_operations() if start is None or end is None else generate_enterprise_operations(start, end)
    appointments = list(generate_appointment_events(count=appointment_count, seed=seed, reference=reference))
    finance = generate_enterprise_finance(count=appointment_count, seed=seed, reference=reference)
    referrals = generate_referrals(count=referral_count, seed=seed, reference=reference)
    return {'reference': reference, 'operations': operations, 'appointment_event': appointments,
            'finance': finance, 'referral': referrals}


def ground_truth_from_definitions(definitions):
    return [dict(anomaly_id=d.anomaly_id, practice_id=d.practice_id, start_date=d.start_date,
                 end_date=d.end_date, anomaly_type=d.anomaly_type,
                 affected_metric=d.affected_metric, expected_direction=d.expected_direction,
                 severity=d.severity, description=d.description)
            for d in definitions]


def apply_anomalies(dataset, anomaly_profile='portfolio_demo'):
    if anomaly_profile not in PROFILES:
        raise ValueError('Choose a supported anomaly profile')
    anomalous = copy.deepcopy(dataset)
    definitions = PROFILES[anomaly_profile]
    for definition in definitions:
        if definition.anomaly_type == 'MA_STAFFING_SHORTAGE':
            _ma_staffing_shortage(anomalous, definition)
        elif definition.anomaly_type == 'PROVIDER_PTO_CAPACITY_REDUCTION':
            _provider_pto(anomalous, definition)
        elif definition.anomaly_type == 'NO_SHOW_SPIKE':
            _no_show_spike(anomalous, definition)
        elif definition.anomaly_type == 'REFERRAL_DEMAND_SURGE':
            _referral_surge(anomalous, definition)
        elif definition.anomaly_type == 'SCHEDULING_TEMPLATE_CAPACITY_REDUCTION':
            _template_reduction(anomalous, definition)
        elif definition.anomaly_type == 'REVENUE_PER_VISIT_DECLINE':
            _revenue_decline(anomalous, definition)
    truth = ground_truth_from_definitions(definitions)
    validate_anomalies(anomalous, truth)
    return anomalous, truth


def _in_window(row_date, definition):
    return definition.start_date <= row_date <= definition.end_date


def _practice_providers(dataset, practice_id):
    return {p['provider_id'] for p in dataset['reference']['provider'] if p['practice_id'] == practice_id}


def _ma_staffing_shortage(dataset, definition):
    for row in dataset['operations']['staffing_daily']:
        if row['practice_id'] == definition.practice_id and row['role'] == 'Medical Assistant' and _in_window(row['staff_date'], definition):
            old_actual = row['actual_fte']
            row['actual_fte'] = round(max(0, old_actual * (1 - definition.intensity)), 2)
            gap_hours = round((old_actual - row['actual_fte']) * 8, 2)
            row['absence_hours'] = round(row['absence_hours'] + gap_hours, 2)
            row['overtime_hours'] = round(min(row['actual_fte'] * 2, row['overtime_hours'] + gap_hours * .25), 2)
            row['agency_hours'] = round(min(8, row['agency_hours'] + gap_hours * .10), 2)


def _provider_pto(dataset, definition):
    providers = {definition.provider_id} if definition.provider_id else _practice_providers(dataset, definition.practice_id)
    for row in dataset['operations']['provider_capacity']:
        if row['provider_id'] in providers and _in_window(row['capacity_date'], definition) and row['clinical_hours'] > 0:
            delta = round(min(row['clinical_hours'], max(0, row['scheduled_hours'] * definition.intensity)), 2)
            row['pto_hours'] = round(row['pto_hours'] + delta, 2)
            row['clinical_hours'] = round(row['clinical_hours'] - delta, 2)
            reduction = min(row['available_slots'], max(1, math.ceil(row['available_slots'] * definition.intensity)))
            row['available_slots'] -= reduction


def _no_show_spike(dataset, definition):
    changed = set()
    for row in dataset['appointment_event']:
        if row['practice_id'] == definition.practice_id and row['appointment_status'] == 'completed' and _in_window(row['appointment_date'], definition):
            if (row['appointment_id'] + definition.anomaly_id) % 100 < int(definition.intensity * 100):
                row['appointment_status'] = 'no_show'
                row['modeled_revenue'] = 0.0
                changed.add(row['appointment_id'])
    removed_encounters = {e['encounter_id'] for e in dataset['finance']['encounter'] if e['appointment_id'] in changed}
    dataset['finance']['encounter'] = [e for e in dataset['finance']['encounter'] if e['appointment_id'] not in changed]
    dataset['finance']['payment'] = [p for p in dataset['finance']['payment'] if p['encounter_id'] not in removed_encounters]


def _referral_surge(dataset, definition):
    next_id = max(row['referral_id'] for row in dataset['referral']) + 1
    start = date.fromisoformat(definition.start_date)
    days = (date.fromisoformat(definition.end_date) - start).days + 1
    for i in range(int(definition.intensity)):
        referral_date = start + timedelta(days=i % days)
        scheduled = referral_date + timedelta(days=7 + i % 21)
        dataset['referral'].append(dict(referral_id=next_id + i, practice_id=definition.practice_id,
                                        specialty_id=definition.specialty_id, referral_date=referral_date.isoformat(),
                                        scheduled_date=scheduled.isoformat(), referral_source='external_primary_care',
                                        status='scheduled' if i % 3 else 'completed'))


def _template_reduction(dataset, definition):
    providers = _practice_providers(dataset, definition.practice_id)
    for row in dataset['operations']['provider_capacity']:
        if row['provider_id'] in providers and _in_window(row['capacity_date'], definition) and row['available_slots'] > 0:
            delta = min(row['available_slots'], int(definition.intensity))
            row['available_slots'] -= delta
            row['blocked_slots'] += delta


def _revenue_decline(dataset, definition):
    encounters = []
    for row in dataset['finance']['encounter']:
        if row['practice_id'] == definition.practice_id and _in_window(row['encounter_date'], definition):
            row['allowed_amount'] = round(max(0, row['allowed_amount'] * (1 - definition.intensity)), 2)
            encounters.append(row['encounter_id'])
    encounter_lookup = {e['encounter_id']: e for e in dataset['finance']['encounter']}
    for row in dataset['finance']['payment']:
        if row['encounter_id'] in encounters:
            allowed = encounter_lookup[row['encounter_id']]['allowed_amount']
            row['allowed_amount'] = allowed
            total = row['paid_amount'] + row['patient_amount']
            scale = 0 if total == 0 else min(1, allowed / total)
            row['paid_amount'] = round(row['paid_amount'] * scale, 2)
            row['patient_amount'] = round(max(0, allowed - row['paid_amount']), 2)


def validate_anomaly_definitions(definitions, reference=None):
    reference = generate_enterprise_reference_data() if reference is None else reference
    validate_enterprise_reference_data(reference)
    practices = {p['practice_id'] for p in reference['practice']}
    ids = set()
    for definition in definitions:
        if definition.anomaly_id in ids:
            raise ValueError('Duplicate anomaly_id')
        ids.add(definition.anomaly_id)
        if definition.practice_id not in practices:
            raise ValueError('Invalid anomaly practice')
        if definition.anomaly_type not in ANOMALY_TYPES:
            raise ValueError('Invalid anomaly_type')
        if definition.severity not in SEVERITIES or definition.expected_direction not in EXPECTED_DIRECTIONS:
            raise ValueError('Invalid anomaly catalog value')
        if date.fromisoformat(definition.end_date) < date.fromisoformat(definition.start_date):
            raise ValueError('Invalid anomaly date range')


def validate_anomalies(dataset, truth):
    validate_anomaly_definitions(PROFILES['portfolio_demo'], dataset['reference'])
    validate_enterprise_operations(dataset['operations'], dataset['reference'])
    validate_enterprise_finance(dataset['finance'], dataset['reference'])
    validate_referrals(dataset['referral'], dataset['reference'])
    appointments = {row['appointment_id']: row for row in dataset['appointment_event']}
    for encounter in dataset['finance']['encounter']:
        appointment = appointments.get(encounter['appointment_id'])
        if appointment is None or appointment['appointment_status'] != 'completed':
            raise ValueError('Encounter must reference a completed appointment')
        if (appointment['provider_id'], appointment['practice_id'], appointment['appointment_date']) != (
                encounter['provider_id'], encounter['practice_id'], encounter['encounter_date']):
            raise ValueError('Encounter and appointment scope mismatch')
    if len(truth) != len(PROFILES['portfolio_demo']):
        raise ValueError('Ground truth count mismatch')
    for row in truth:
        if set(row) != set(GROUND_TRUTH_FIELDS):
            raise ValueError('Unexpected ground truth fields')
        if row['anomaly_type'] not in ANOMALY_TYPES:
            raise ValueError('Invalid ground truth anomaly type')
        if row['severity'] not in SEVERITIES or row['expected_direction'] not in EXPECTED_DIRECTIONS:
            raise ValueError('Invalid ground truth catalog value')
