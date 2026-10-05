"""Load deterministic portfolio-demo ground-truth anomaly rows."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_anomaly_loader import load_ground_truth_anomalies
from src.postgres_analytics import PostgresRepository


def main():
    with PostgresRepository()._connect() as connection:
        result = load_ground_truth_anomalies(connection)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
