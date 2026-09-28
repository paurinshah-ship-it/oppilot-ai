"""Local CSV staging, explicit mapping and non-imputing quality checks."""
from io import BytesIO
import hashlib
import re
import pandas as pd
from src.data import validate_data

COLUMNS = ['date', 'provider_id', 'provider', 'specialty', 'clinic', 'fte',
           'staffed_hours', 'capacity', 'booked', 'no_shows', 'visits', 'revenue']
NUMERIC = COLUMNS[5:]
ALIASES = {
    # These are operational-data aliases only. The mapping step remains
    # user-confirmed because an identifier or financial definition can differ
    # by source system.
    'date': ['service_date', 'appointment_date', 'date_of_service', 'visit_date', 'dos'],
    'provider_id': ['physician_id', 'clinician_id', 'doctor_id', 'provider_identifier'],
    'provider': ['physician', 'physician_name', 'provider_name', 'clinician_name', 'doctor_name'],
    'specialty': ['speciality', 'specialty_name', 'department'],
    'clinic': ['location', 'clinic_name', 'practice', 'practice_name', 'site', 'site_name'],
    'fte': ['provider_fte', 'fte_value'],
    'staffed_hours': ['hours_worked', 'staffed_hrs', 'scheduled_hours', 'clinical_hours'],
    'capacity': ['available_slots', 'appointment_capacity', 'total_slots', 'slots_available'],
    'booked': ['appointments_booked', 'appointments_scheduled', 'scheduled_appointments', 'scheduled'],
    'no_shows': ['no_show_count', 'no_shows', 'no_show', 'no_show_visits'],
    'visits': ['appts_completed', 'completed', 'completed_visits', 'visits_complete',
               'completed_appointments', 'appointments_completed'],
    'revenue': ['net_revenue', 'realized_revenue', 'collected_revenue'],
}

FIELD_LABELS = {
    'date': 'Date', 'provider_id': 'Provider ID', 'provider': 'Provider',
    'specialty': 'Specialty', 'clinic': 'Practice / clinic', 'fte': 'FTE',
    'staffed_hours': 'Staffed hours', 'capacity': 'Appointment capacity',
    'booked': 'Booked appointments', 'no_shows': 'No-shows',
    'visits': 'Completed visits', 'revenue': 'Realized revenue / collections',
}


def read_upload(payload):
    """Bound resource use; preserve strings until explicit contract conversion."""
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError('CSV exceeds the 20 MB limit.')
    df = pd.read_csv(BytesIO(payload), dtype=str, encoding='utf-8-sig', nrows=200001)
    if len(df) > 200000 or len(df.columns) > 100:
        raise ValueError('CSV limit: 200,000 rows and 100 columns.')
    if df.empty:
        raise ValueError('CSV has no records.')
    return df


def schema_profile(raw: pd.DataFrame) -> dict:
    """Return a stable raw-file schema signature without retaining file values."""
    columns = [str(column) for column in raw.columns]
    normalized = [re.sub(r'[^a-z0-9]+', '_', column.strip().lower()).strip('_') for column in columns]
    fingerprint = hashlib.sha256('|'.join(normalized).encode()).hexdigest()[:16]
    return {'columns': columns, 'fingerprint': fingerprint}


def schema_change(previous: dict | None, current: dict) -> str | None:
    """Describe a raw header change that should be reviewed during mapping."""
    if not previous or previous.get('fingerprint') == current.get('fingerprint'):
        return None
    before, after = set(previous.get('columns', [])), set(current.get('columns', []))
    added, removed = sorted(after - before), sorted(before - after)
    parts = []
    if added:
        parts.append('added: ' + ', '.join(added))
    if removed:
        parts.append('removed: ' + ', '.join(removed))
    return 'Raw upload schema changed since the previous activated file' + (f" ({'; '.join(parts)})" if parts else '') + '. Review each proposed mapping before activation.'


def mapping_suggestions(columns):
    """Recognize likely healthcare-operations fields for explicit user review.

    A source column is auto-proposed only when it maps to exactly one canonical
    field. Ambiguous names and unsupported semantic substitutions (for example,
    cancellations as no-shows) remain unmapped.
    """
    normalize = lambda s: re.sub(r'[^a-z0-9]+', '_', str(s).strip().lower()).strip('_')
    normalized = {column: normalize(column) for column in columns}
    matches_by_field = {}
    candidate_fields = {}
    for field in COLUMNS:
        accepted = {field, *ALIASES[field]}
        matches = [column for column, value in normalized.items() if value in accepted]
        matches_by_field[field] = matches
        for column in matches:
            candidate_fields.setdefault(column, []).append(field)
    suggestions = {}
    for field, matches in matches_by_field.items():
        selected = matches[0] if len(matches) == 1 and len(candidate_fields[matches[0]]) == 1 else None
        suggestions[field] = {
            'source_column': selected,
            'target_field': field,
            'target_label': FIELD_LABELS[field],
            'confidence': 'Exact field name' if selected and normalized[selected] == field else 'Likely healthcare operations alias' if selected else 'Needs mapping',
        }
    return suggestions


def suggest_mapping(columns):
    """Backward-compatible field-to-column proposals for the activation flow."""
    details = mapping_suggestions(columns)
    return {field: item['source_column'] for field, item in details.items()}


def project_columns(raw, mapping):
    if any(not mapping.get(c) for c in COLUMNS):
        raise ValueError('Map every required field before validation. Missing measures cannot be inferred.')
    selected = [mapping[c] for c in COLUMNS]
    if len(set(selected)) != len(selected):
        raise ValueError('Each source column may map to only one field.')
    if not set(selected) <= set(raw.columns):
        raise ValueError('Mapping refers to a missing source column.')
    df = raw[selected].copy()
    df.columns = COLUMNS
    for col in COLUMNS[:5]:
        df[col] = df[col].astype('string').str.strip()
    # Dates are intentionally ISO-only; ambiguous 01/02 dates are not guessed.
    df['date'] = pd.to_datetime(df.date, format='%Y-%m-%d', errors='coerce')
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def quality_checks(df):
    """Counts are affected rows, except date gaps (calendar weekdays).

    Gaps are advisory: no staffing roster exists to prove missing observations.
    Never fill missing values, drop duplicate rows, or reinterpret financial data.
    """
    checks = []
    def add(name, count, detail, advisory=False):
        checks.append({'Check': name, 'Status': ('Review' if advisory else 'Error') if count else 'Pass',
                       'Count': int(count), 'Detail': detail})
    missing = set(COLUMNS) - set(df.columns)
    add('Required columns', len(missing), ', '.join(sorted(missing)) or 'All required columns present')
    if missing:
        return pd.DataFrame(checks)
    d = df.copy()
    d['date'] = pd.to_datetime(d.date, errors='coerce')
    for col in NUMERIC:
        d[col] = pd.to_numeric(d[col], errors='coerce')
    add('Required values', d[COLUMNS].isna().any(axis=1).sum(), 'Null or invalid dates / numeric values; no imputation')
    add('Provider names and identifiers', d[COLUMNS[1:5]].fillna('').astype(str).apply(lambda s: s.str.strip().eq('')).any(axis=1).sum(), 'Names, IDs, specialties and clinics must be nonblank')
    add('Negative / infinite values', ((d[NUMERIC] < 0) | d[NUMERIC].isin([float('inf'), -float('inf')])).any(axis=1).sum(), 'All measures must be finite and nonnegative')
    add('Negative realized revenue / collections', (d.revenue < 0).sum(), 'Negative financial values are not valid for this realized-revenue metric')
    add('Duplicate provider/date rows', d.duplicated(['provider_id', 'date'], keep=False).sum(), 'Duplicates would double-count activity')
    over_capacity = d.visits > d.capacity
    add('Completed visits above capacity', over_capacity.sum(), 'Completed visits must not exceed available appointment capacity')
    add('Utilization over 100%', over_capacity.sum(), 'Utilization is visits ÷ capacity and cannot exceed 100%')
    invalid = (d.booked > d.capacity) | (d.visits + d.no_shows != d.booked) | (d[['capacity','booked','no_shows','visits']] % 1 != 0).any(axis=1)
    add('Appointment counts', invalid.sum(), 'Whole counts: visits + no-shows = booked <= capacity; cancellations are not a supported measure')
    add('Staffing values', (d[['fte','staffed_hours','capacity']] <= 0).any(axis=1).sum(), 'Staffed days require positive FTE, hours and capacity')
    conflicts = d.groupby('provider_id')[['provider','specialty','clinic']].nunique().gt(1).any(axis=1)
    add('Provider identity consistency', conflicts.sum(), 'Each ID has one name, specialty and clinic')
    if d.date.notna().any():
        gaps = pd.bdate_range(d.date.min(), d.date.max()).difference(pd.DatetimeIndex(d.date.dropna().unique()))
        add('Missing dates / unobserved weekdays across dataset', len(gaps), 'May be holidays or unscheduled days; completeness cannot be established without a staffing roster', True)
        provider_gaps = sum(len(pd.bdate_range(g.date.min(), g.date.max()).difference(pd.DatetimeIndex(g.date.dropna().unique()))) for _, g in d.dropna(subset=['date']).groupby('provider_id'))
        add('Potential missing provider-day records', provider_gaps, 'Within each provider\'s observed bounds; may be leave or unscheduled days, not proven missing records', True)
    return pd.DataFrame(checks)


def activate_upload(state, raw, mapping, confirmed):
    """Transaction: validation completes before any active session state changes."""
    if not confirmed:
        raise ValueError('Confirm this is synthetic or verified non-PHI aggregate provider-day data and the mappings are correct.')
    candidate = validate_data(project_columns(raw, mapping))
    state['uploaded_data'] = candidate
    state['dataset_revision'] = state.get('dataset_revision', 0) + 1
    return candidate
