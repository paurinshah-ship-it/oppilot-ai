"""Stream a large fictional appointment-event CSV without using Pandas.

The output intentionally has no patient columns or clinical data. It is an
ignored scale-test fixture for PostgreSQL COPY loading, not dashboard input.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "synthetic_appointments_1m.csv"


def generate(output: Path, rows: int, seed: int = 42) -> None:
    if rows < 1:
        raise ValueError("rows must be positive")
    providers = [f"SYN-{index:03d}" for index in range(1, 49)]
    rng, start = random.Random(seed), date(2021, 1, 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["appointment_id", "provider_id", "appointment_date", "appointment_status", "modeled_revenue"])
        for appointment_id in range(1, rows + 1):
            provider_id = providers[(appointment_id - 1) % len(providers)]
            appointment_date = start + timedelta(days=rng.randrange(1826))
            outcome = rng.choices(("completed", "no_show", "cancelled"), weights=(78, 11, 11), k=1)[0]
            revenue = round(rng.uniform(140, 320), 2) if outcome == "completed" else 0
            writer.writerow([appointment_id, provider_id, appointment_date.isoformat(), outcome, revenue])
            if appointment_id % 100_000 == 0:
                print(f"Generated {appointment_id:,}/{rows:,} events")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output, args.rows)
    print(f"Wrote {args.rows:,} synthetic appointment events to {args.output}")
