"""Transactional loading for deterministic ground-truth anomaly rows."""
from datetime import date

from src.enterprise_anomalies import GROUND_TRUTH_FIELDS, ground_truth_from_definitions, validate_anomaly_definitions


class AnomalyConflict(ValueError):
    """Stored ground-truth anomaly differs from the deterministic fixture."""


def load_ground_truth_anomalies(connection, definitions=None):
    from psycopg import sql
    from src.enterprise_anomalies import PORTFOLIO_DEMO
    definitions = PORTFOLIO_DEMO if definitions is None else definitions
    validate_anomaly_definitions(definitions)
    rows = ground_truth_from_definitions(definitions)
    inserted = 0
    with connection.transaction():
        connection.execute('LOCK TABLE practice, ground_truth_anomaly IN SHARE ROW EXCLUSIVE MODE')
        for row in rows:
            values = tuple(date.fromisoformat(row[column]) if column in ('start_date', 'end_date') else row[column]
                           for column in GROUND_TRUTH_FIELDS)
            existing = connection.execute(sql.SQL('SELECT {} FROM ground_truth_anomaly WHERE anomaly_id = %s').format(
                sql.SQL(', ').join(map(sql.Identifier, GROUND_TRUTH_FIELDS))), (row['anomaly_id'],)).fetchone()
            if existing is not None:
                if existing != values:
                    raise AnomalyConflict(f'Conflicting ground_truth_anomaly row: {row["anomaly_id"]}')
                continue
            connection.execute(sql.SQL('INSERT INTO ground_truth_anomaly ({}) VALUES ({})').format(
                sql.SQL(', ').join(map(sql.Identifier, GROUND_TRUTH_FIELDS)),
                sql.SQL(', ').join(sql.Placeholder() for _ in GROUND_TRUTH_FIELDS)), values)
            inserted += 1
    return {'rows': len(rows), 'inserted': inserted}
