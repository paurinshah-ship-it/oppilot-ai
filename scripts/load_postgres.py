"""Load the validated synthetic provider-day demo data into PostgreSQL.

Set DATABASE_URL first, then run: python scripts/load_postgres.py
The source contains aggregate fictional operations records, not PHI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import load_data
from src.postgres_analytics import PostgresRepository


def main() -> None:
    data = load_data()
    repo = PostgresRepository()
    repo.initialize_schema()
    specialties = sorted(data.specialty.unique())
    with repo._connect() as connection, connection.cursor() as cursor:
        for specialty in specialties:
            cursor.execute("INSERT INTO specialty (specialty_name) VALUES (%s) ON CONFLICT (specialty_name) DO NOTHING", (specialty,))
        cursor.execute("SELECT specialty_id, specialty_name FROM specialty")
        specialty_ids = {name: identifier for identifier, name in cursor.fetchall()}
        providers = data[["provider_id", "provider", "specialty", "clinic"]].drop_duplicates()
        for row in providers.itertuples(index=False):
            cursor.execute(
                """INSERT INTO provider (provider_id, provider_name, specialty_id, clinic_name)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (provider_id) DO UPDATE SET provider_name = EXCLUDED.provider_name,
                   specialty_id = EXCLUDED.specialty_id, clinic_name = EXCLUDED.clinic_name""",
                (row.provider_id, row.provider, specialty_ids[row.specialty], row.clinic),
            )
        for row in data.itertuples(index=False):
            cursor.execute(
                """INSERT INTO appointment (provider_id, appointment_date, available_slots, booked_appointments, no_shows)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (provider_id, appointment_date) DO UPDATE SET available_slots = EXCLUDED.available_slots,
                   booked_appointments = EXCLUDED.booked_appointments, no_shows = EXCLUDED.no_shows""",
                (row.provider_id, row.date, int(row.capacity), int(row.booked), int(row.no_shows)),
            )
            cursor.execute(
                """INSERT INTO performance (provider_id, performance_date, fte, staffed_hours, completed_visits, realized_revenue)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (provider_id, performance_date) DO UPDATE SET fte = EXCLUDED.fte,
                   staffed_hours = EXCLUDED.staffed_hours, completed_visits = EXCLUDED.completed_visits,
                   realized_revenue = EXCLUDED.realized_revenue""",
                (row.provider_id, row.date, float(row.fte), float(row.staffed_hours), int(row.visits), float(row.revenue)),
            )
    print(f"Loaded {len(data):,} aggregate provider-day records into PostgreSQL.")


if __name__ == "__main__":
    main()
