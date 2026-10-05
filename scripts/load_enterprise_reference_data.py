"""Explicitly load the fixed synthetic reference fixture using DATABASE_URL.

Apply db/schema.sql first. This command does not load operational facts.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.enterprise_reference_loader import load_enterprise_reference_data
from src.postgres_analytics import PostgresRepository


def main():
    repository = PostgresRepository()
    with repository._connect() as connection:
        result = load_enterprise_reference_data(connection)
    print('Synthetic reference fixture loaded: ' + ', '.join(f'{count} {table}' for table, count in result['counts'].items()))


if __name__ == '__main__':
    main()
