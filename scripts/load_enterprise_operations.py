"""Explicitly bulk-load synthetic operations; schema and Phase 1B must exist."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_operations import START_DATE, END_DATE, generate_enterprise_operations
from src.enterprise_operations_loader import load_enterprise_operations
from src.postgres_analytics import PostgresRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=START_DATE)
    parser.add_argument('--end', type=date.fromisoformat, default=END_DATE)
    args = parser.parse_args()
    data = generate_enterprise_operations(args.start, args.end)
    with PostgresRepository()._connect() as connection:
        result = load_enterprise_operations(connection, data, args.start, args.end)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
