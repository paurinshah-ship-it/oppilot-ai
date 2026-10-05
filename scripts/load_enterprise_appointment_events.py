"""Transactionally load deterministic synthetic appointment events into PostgreSQL."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_appointments import DEFAULT_COUNT, END_DATE, START_DATE
from src.enterprise_appointment_loader import load_appointment_events
from src.postgres_analytics import PostgresRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=DEFAULT_COUNT)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--start', type=date.fromisoformat, default=START_DATE)
    parser.add_argument('--end', type=date.fromisoformat, default=END_DATE)
    args = parser.parse_args()
    with PostgresRepository()._connect() as connection:
        result = load_appointment_events(connection, args.count, args.seed, start=args.start, end=args.end)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
