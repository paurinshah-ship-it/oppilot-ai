"""Bulk-load the ignored synthetic appointment-event fixture with PostgreSQL COPY.

Run after scripts/load_postgres.py and generate_appointment_events.py. COPY
keeps the one-million-row import in PostgreSQL rather than creating a Pandas
dataframe in the application process.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.postgres_analytics import PostgresRepository
from scripts.generate_appointment_events import DEFAULT_OUTPUT


def main() -> None:
    if not DEFAULT_OUTPUT.exists():
        raise FileNotFoundError(f"Generate the fixture first: {DEFAULT_OUTPUT}")
    repository = PostgresRepository()
    repository.initialize_schema()
    with repository._connect() as connection, connection.cursor() as cursor:
        with DEFAULT_OUTPUT.open("r") as source, cursor.copy(
            "COPY appointment_event (appointment_id, provider_id, appointment_date, appointment_status, modeled_revenue) "
            "FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
        ) as copy:
            while chunk := source.read(1024 * 1024):
                copy.write(chunk)
    print(f"Loaded {DEFAULT_OUTPUT.name} with PostgreSQL COPY.")


if __name__ == "__main__":
    main()
