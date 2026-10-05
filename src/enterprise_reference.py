"""Deterministic, fictional enterprise reference records; no operational facts."""
from collections import Counter
from datetime import date, timedelta
import random

from src.data import FIRST_NAMES, LAST_NAMES, SPECIALTIES, legacy_provider_records

SEED = 42
ORGANIZATION_ID = 10001
CREATED_AT = '2021-01-01T00:00:00+00:00'
REGIONS = ('Northeast', 'Mid-Atlantic', 'Southeast', 'Midwest', 'Southwest')
# New providers use ten specialties; all twelve legacy specialties are retained.
NEW_SPECIALTIES = tuple(name for name, _, _ in SPECIALTIES[:10])
# Ordered, explicit IDs are not inferred from names, geography or hash().
PRACTICES = (
    ('North Clinic', 'Boston', 'MA', 'Multispecialty'),
    ('Pinehaven Primary Care', 'Manchester', 'NH', 'Primary Care'),
    ('Cedarbrook Cardiology', 'Providence', 'RI', 'Cardiology'),
    ('Maplecrest Orthopedics', 'Portland', 'ME', 'Orthopedics'),
    ('Birchvale Medical Practice', 'Hartford', 'CT', 'Multispecialty'),
    ('Central Clinic', 'Philadelphia', 'PA', 'Multispecialty'),
    ('East Clinic', 'Newark', 'NJ', 'Multispecialty'),
    ('Stonebridge Endocrinology', 'Baltimore', 'MD', 'Endocrinology'),
    ('Meadowpoint Gastroenterology', 'Richmond', 'VA', 'Gastroenterology'),
    ('Willowcrest Neurology', 'Charleston', 'WV', 'Neurology'),
    ('South Clinic', 'Raleigh', 'NC', 'Multispecialty'),
    ('Sunmeadow Primary Care', 'Columbia', 'SC', 'Primary Care'),
    ('Magnolia Ridge Cardiology', 'Atlanta', 'GA', 'Cardiology'),
    ('Harborfield Orthopedics', 'Jacksonville', 'FL', 'Orthopedics'),
    ('Oakstream Internal Medicine', 'Nashville', 'TN', 'Internal Medicine'),
    ('Lakeside Clinic', 'Madison', 'WI', 'Multispecialty'),
    ('Prairieview Primary Care', 'Des Moines', 'IA', 'Primary Care'),
    ('Aspenfield Cardiology', 'Columbus', 'OH', 'Cardiology'),
    ('Riverstone Orthopedics', 'Grand Rapids', 'MI', 'Orthopedics'),
    ('Elmvale Medical Practice', 'Indianapolis', 'IN', 'Multispecialty'),
    ('West Clinic', 'Phoenix', 'AZ', 'Multispecialty'),
    ('Mesa Grove Primary Care', 'Albuquerque', 'NM', 'Primary Care'),
    ('Desertwind Cardiology', 'El Paso', 'TX', 'Cardiology'),
    ('Copperleaf Endocrinology', 'Las Vegas', 'NV', 'Endocrinology'),
    ('Sagefield Gastroenterology', 'Oklahoma City', 'OK', 'Gastroenterology'),
)
FIELDS = {
    'organization': ('organization_id', 'organization_name', 'created_at'),
    'region': ('region_id', 'organization_id', 'region_name', 'region_code'),
    'practice': ('practice_id', 'region_id', 'practice_name', 'practice_code', 'city',
                 'state', 'practice_type', 'opening_date', 'active'),
    'specialty': ('specialty_id', 'specialty_name'),
    'provider': ('provider_id', 'provider_name', 'specialty_id', 'clinic_name', 'practice_id'),
}


def generate_enterprise_reference_data() -> dict[str, list[dict]]:
    """Return the fixed Phase 1B fixture with stable IDs and no wall-clock values."""
    rng = random.Random(SEED)
    data = {table: [] for table in FIELDS}
    data['organization'] = [dict(organization_id=ORGANIZATION_ID,
                                 organization_name='NorthStar Medical Group', created_at=CREATED_AT)]
    for i, name in enumerate(REGIONS, 1):
        data['region'].append(dict(region_id=10000 + i, organization_id=ORGANIZATION_ID,
                                   region_name=name, region_code=f'R{i:02d}'))
    for i, (name, city, state, kind) in enumerate(PRACTICES, 1):
        data['practice'].append(dict(practice_id=10000 + i, region_id=10001 + (i - 1) // 5,
                                    practice_name=name, practice_code=f'P{i:02d}', city=city,
                                    state=state, practice_type=kind,
                                    opening_date=(date(2000, 1, 1) + timedelta(days=rng.randrange(7305))).isoformat(),
                                    active=True))
    # Matches the legacy loader's alphabetical order on an empty database.
    for i, name in enumerate(sorted(name for name, _, _ in SPECIALTIES), 1):
        data['specialty'].append(dict(specialty_id=i, specialty_name=name))
    specialty_ids = {r['specialty_name']: r['specialty_id'] for r in data['specialty']}
    practice_ids = {r['practice_name']: r['practice_id'] for r in data['practice']}
    legacy = legacy_provider_records()
    for row in legacy:
        data['provider'].append(dict(provider_id=row['provider_id'], provider_name=row['provider_name'],
                                    specialty_id=specialty_ids[row['specialty_name']], clinic_name=row['clinic_name'],
                                    practice_id=practice_ids[row['clinic_name']]))
    # Invented combinations only; no directory, NPI, credentials or people lookup.
    used_names = {r['provider_name'] for r in legacy}
    names = [f'Dr. {first} {last}' for first in FIRST_NAMES for last in LAST_NAMES
             if f'Dr. {first} {last}' not in used_names]
    rng.shuffle(names)
    multispecialty_index = 0
    for i in range(102):
        practice = data['practice'][i % 25]
        kind = practice['practice_type']
        if kind == 'Multispecialty':
            # Cycle all ten without skewing specialty-only practice assignments.
            specialty = NEW_SPECIALTIES[multispecialty_index % len(NEW_SPECIALTIES)]
            multispecialty_index += 1
        else:
            specialty = 'Primary Care' if kind == 'Internal Medicine' else kind
        data['provider'].append(dict(provider_id=f'SYN-{i + 49:03d}', provider_name=names[i],
                                    specialty_id=specialty_ids[specialty], clinic_name=practice['practice_name'],
                                    practice_id=practice['practice_id']))
    validate_enterprise_reference_data(data)
    return data


def validate_enterprise_reference_data(data: dict) -> None:
    """Validate counts, approved columns, referential integrity and legacy identity."""
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    require(isinstance(data, dict) and set(data) == set(FIELDS), 'Expected only the five reference tables')
    counts = {'organization': 1, 'region': 5, 'practice': 25, 'specialty': 12, 'provider': 150}
    for table, columns in FIELDS.items():
        require(isinstance(data[table], list) and len(data[table]) == counts[table], f'Invalid {table} count')
        for row in data[table]:
            require(isinstance(row, dict) and set(row) == set(columns), f'Unexpected {table} fields')
            for column, value in row.items():
                if column == 'active':
                    require(type(value) is bool, 'active must be boolean')
                elif column.endswith('_id') and column != 'provider_id':
                    require(type(value) is int and value > 0, f'Invalid {table}.{column}')
                else:
                    require(isinstance(value, str) and bool(value.strip()), f'Empty or invalid {table}.{column}')
        ids = [r[f'{table}_id'] for r in data[table]]
        require(len(ids) == len(set(ids)), f'Duplicate {table} IDs')
    require(data['organization'] == [dict(organization_id=ORGANIZATION_ID,
                organization_name='NorthStar Medical Group', created_at=CREATED_AT)], 'Unexpected organization')
    regions = {r['region_id']: r for r in data['region']}
    require({(r['region_id'], r['region_code'], r['region_name']) for r in regions.values()} ==
            {(10000 + i, f'R{i:02d}', name) for i, name in enumerate(REGIONS, 1)}, 'Unexpected region identities')
    require(all(r['organization_id'] == ORGANIZATION_ID for r in regions.values()), 'Invalid region organization')
    practices = {r['practice_id']: r for r in data['practice']}
    require(set(practices) == set(range(10001, 10026)), 'Unexpected practice IDs')
    require(Counter(r['region_id'] for r in practices.values()) == Counter({i: 5 for i in regions}), 'Expected five practices per region')
    for i, expected in enumerate(PRACTICES, 1):
        row = practices[10000 + i]
        require(tuple(row[k] for k in ('practice_name', 'city', 'state', 'practice_type')) == expected,
                'Unexpected practice identity')
        require(row['region_id'] == 10001 + (i - 1) // 5 and row['practice_code'] == f'P{i:02d}', 'Invalid practice assignment/code')
        require(date.fromisoformat(row['opening_date']) < date(2021, 1, 1), 'Practice must open before demo period')
    specialties = {r['specialty_id']: r['specialty_name'] for r in data['specialty']}
    require(specialties == dict(enumerate(sorted(name for name, _, _ in SPECIALTIES), 1)), 'Legacy specialties must be preserved')
    providers = {r['provider_id']: r for r in data['provider']}
    require(set(providers) == {f'SYN-{i:03d}' for i in range(1, 151)}, 'Unexpected provider IDs')
    require(len({r['provider_name'] for r in providers.values()}) == 150, 'Duplicate provider names')
    require({r['practice_id'] for r in providers.values()} == set(practices), 'Every practice must have providers')
    for row in providers.values():
        require(row['practice_id'] in practices, 'Invalid provider practice')
        require(row['specialty_id'] in specialties, 'Invalid provider specialty')
        require(row['clinic_name'] == practices[row['practice_id']]['practice_name'], 'Clinic/practice label mismatch')
    allowed_names = {f'Dr. {first} {last}' for first in FIRST_NAMES for last in LAST_NAMES}
    for row in data['provider']:
        require(row['provider_name'] in allowed_names, 'Provider name must use the fictional name vocabulary')
        if int(row['provider_id'].split('-')[1]) > 48:
            kind = practices[row['practice_id']]['practice_type']
            allowed = NEW_SPECIALTIES if kind == 'Multispecialty' else ('Primary Care' if kind == 'Internal Medicine' else kind,)
            require(specialties[row['specialty_id']] in allowed, 'Specialty incompatible with practice type')
    for legacy in legacy_provider_records():
        row = providers[legacy['provider_id']]
        require((row['provider_name'], specialties[row['specialty_id']], row['clinic_name']) ==
                (legacy['provider_name'], legacy['specialty_name'], legacy['clinic_name']), 'Legacy provider identity changed')
