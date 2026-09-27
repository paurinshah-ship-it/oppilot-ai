"""Local CSV staging, explicit mapping and non-imputing quality checks."""
from io import BytesIO
import re
import pandas as pd
from src.data import validate_data

COLUMNS = ['date', 'provider_id', 'provider', 'specialty', 'clinic', 'fte',
           'staffed_hours', 'capacity', 'booked', 'no_shows', 'visits', 'revenue']
NUMERIC = COLUMNS[5:]
ALIASES = {
    'date': ['service_date', 'appointment_date'],
    'provider_id': ['physician_id'], 'provider': ['physician', 'provider_name'],
    'specialty': ['speciality'], 'clinic': ['location'], 'fte': [],
    'staffed_hours': ['hours_worked'], 'capacity': ['available_slots'],
    'booked': ['appointments_booked'], 'no_shows': ['no_show_count'],
    'visits': ['appts_completed', 'completed', 'completed_visits'], 'revenue': [],
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


def suggest_mapping(columns):
    """Only unique recognized aliases are suggested; ambiguous fields stay empty.

    Deliberately no collections/revenue or cancellations/no-shows equivalence.
    """
    normalize = lambda s: re.sub(r'[^a-z0-9]+', '_', s.strip().lower()).strip('_')
    result = {}
    for field in COLUMNS:
        matches = [c for c in columns if normalize(c) in [field] + ALIASES[field]]
        result[field] = matches[0] if len(matches) == 1 else None
    return result


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
    add('Duplicate provider/date rows', d.duplicated(['provider_id', 'date'], keep=False).sum(), 'Duplicates would double-count activity')
    add('Utilization over 100%', (d.visits > d.capacity).sum(), 'Completed visits must not exceed capacity')
    invalid = (d.booked > d.capacity) | (d.visits + d.no_shows != d.booked) | (d[['capacity','booked','no_shows','visits']] % 1 != 0).any(axis=1)
    add('Appointment counts', invalid.sum(), 'Whole counts: visits + no-shows = booked <= capacity; cancellations are not a supported measure')
    add('Staffing values', (d[['fte','staffed_hours','capacity']] <= 0).any(axis=1).sum(), 'Staffed days require positive FTE, hours and capacity')
    conflicts = d.groupby('provider_id')[['provider','specialty','clinic']].nunique().gt(1).any(axis=1)
    add('Provider identity consistency', conflicts.sum(), 'Each ID has one name, specialty and clinic')
    if d.date.notna().any():
        gaps = pd.bdate_range(d.date.min(), d.date.max()).difference(pd.DatetimeIndex(d.date.dropna().unique()))
        add('Unobserved weekdays across dataset', len(gaps), 'May be holidays or unscheduled days; completeness cannot be established without a staffing roster', True)
        provider_gaps = sum(len(pd.bdate_range(g.date.min(), g.date.max()).difference(pd.DatetimeIndex(g.date.dropna().unique()))) for _, g in d.dropna(subset=['date']).groupby('provider_id'))
        add('Unobserved provider weekdays', provider_gaps, 'Within each provider\'s observed bounds; may be leave or unscheduled days, not proven missing records', True)
    return pd.DataFrame(checks)


def activate_upload(state, raw, mapping, confirmed):
    """Transaction: validation completes before any active session state changes."""
    if not confirmed:
        raise ValueError('Confirm this is synthetic or verified non-PHI aggregate provider-day data and the mappings are correct.')
    candidate = validate_data(project_columns(raw, mapping))
    state['uploaded_data'] = candidate
    state['dataset_revision'] = state.get('dataset_revision', 0) + 1
    return candidate
