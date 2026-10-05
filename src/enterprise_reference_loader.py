"""Explicit, transactional reference-fixture loading; never writes fact tables."""
from datetime import date, datetime

from src.data import legacy_provider_records
from src.enterprise_reference import FIELDS, generate_enterprise_reference_data, validate_enterprise_reference_data


class ReferenceDataConflict(ValueError):
    """An existing identity differs from the approved synthetic fixture."""


def _values(table, row):
    values = dict(row)
    if table == 'organization':
        values['created_at'] = datetime.fromisoformat(values['created_at'])
    if table == 'practice':
        values['opening_date'] = date.fromisoformat(values['opening_date'])
    return tuple(values[column] for column in FIELDS[table])


def _insert_or_match(connection, table, row):
    """Table/column identifiers come exclusively from the fixed allowlist."""
    from psycopg import sql
    columns = FIELDS[table]
    values = _values(table, row)
    query = sql.SQL('SELECT {} FROM {} WHERE {} = %s').format(
        sql.SQL(', ').join(map(sql.Identifier, columns)), sql.Identifier(table), sql.Identifier(columns[0]))
    existing = connection.execute(query, (values[0],)).fetchone()
    if existing is not None:
        if existing != values:
            raise ReferenceDataConflict(f'Conflicting {table} identity: {values[0]}')
        return
    connection.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
        sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)),
        sql.SQL(', ').join(sql.Placeholder() for _ in columns)), values)


def _advance_sequence(connection, table):
    """Transactional RESTART avoids future default-ID collisions, never rewinds.

    Reference tables are already write-locked. Unlike setval, ALTER SEQUENCE
    rolls back with the transaction if a later operation fails.
    """
    from psycopg import sql
    column = FIELDS[table][0]
    sequence = connection.execute('''SELECT n.nspname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.oid = pg_get_serial_sequence(%s, %s)::regclass''', (table, column)).fetchone()
    if sequence is None:
        raise ReferenceDataConflict(f'Missing expected serial sequence for {table}')
    identifier = sql.Identifier(*sequence)
    last_value, is_called = connection.execute(sql.SQL('SELECT last_value, is_called FROM {}').format(identifier)).fetchone()
    maximum = connection.execute(sql.SQL('SELECT MAX({}) FROM {}').format(sql.Identifier(column), sql.Identifier(table))).fetchone()[0]
    next_value = last_value + 1 if is_called else last_value
    if maximum is not None and next_value <= maximum:
        connection.execute(sql.SQL('ALTER SEQUENCE {} RESTART WITH {}').format(identifier, sql.Literal(maximum + 1)))


def load_enterprise_reference_data(connection, data=None):
    """Load the approved fixture into an already initialized Phase 1A database.

    Owns one explicit transaction, or a savepoint if the caller already has a
    transaction. Commit remains the outer caller's responsibility in that case.
    No schema initialization, DELETE, TRUNCATE, or operational inserts occur.
    """
    data = generate_enterprise_reference_data() if data is None else data
    validate_enterprise_reference_data(data)
    legacy_ids = {row['provider_id'] for row in legacy_provider_records()}
    with connection.transaction():
        # Prevent check/insert races with this loader and ordinary reference
        # writers. Order is fixed for concurrent loader runs; reads continue.
        connection.execute('LOCK TABLE organization, region, practice, specialty, provider IN SHARE ROW EXCLUSIVE MODE')
        for table in ('organization', 'region', 'practice'):
            for row in data[table]:
                _insert_or_match(connection, table, row)

        stored = connection.execute('SELECT specialty_id, specialty_name FROM specialty').fetchall()
        specialty_ids = {name: identifier for identifier, name in stored}
        used_ids = {identifier for identifier, _ in stored}
        canonical_to_database = {}
        for row in data['specialty']:
            name, canonical = row['specialty_name'], row['specialty_id']
            if name not in specialty_ids:
                identifier = canonical if canonical not in used_ids else max(used_ids | {canonical}) + 1
                connection.execute('INSERT INTO specialty (specialty_id, specialty_name) VALUES (%s, %s)', (identifier, name))
                specialty_ids[name] = identifier
                used_ids.add(identifier)
            canonical_to_database[canonical] = specialty_ids[name]

        for row in data['provider']:
            mapped = dict(row, specialty_id=canonical_to_database[row['specialty_id']])
            existing = connection.execute('''SELECT provider_id, provider_name, specialty_id, clinic_name, practice_id
                FROM provider WHERE provider_id = %s''', (row['provider_id'],)).fetchone()
            expected = _values('provider', mapped)
            if existing == expected:
                continue
            if existing is not None:
                if row['provider_id'] in legacy_ids and existing[:4] == expected[:4] and existing[4] is None:
                    connection.execute('UPDATE provider SET practice_id = %s WHERE provider_id = %s',
                                       (row['practice_id'], row['provider_id']))
                else:
                    raise ReferenceDataConflict(f'Conflicting provider identity or practice: {row["provider_id"]}')
            else:
                _insert_or_match(connection, 'provider', mapped)
        for table in ('organization', 'region', 'practice', 'specialty'):
            _advance_sequence(connection, table)
    return {'counts': {table: len(rows) for table, rows in data.items()},
            'specialty_ids': {r['specialty_name']: specialty_ids[r['specialty_name']] for r in data['specialty']}}
