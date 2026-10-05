"""Stream deterministic synthetic enterprise appointment events to CSV."""
import argparse
import csv
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_appointments import (DEFAULT_COUNT, END_DATE, FIELDS, START_DATE,
    generate_appointment_events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New CSV file path')
    parser.add_argument('--count', type=int, default=DEFAULT_COUNT)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--start', type=date.fromisoformat, default=START_DATE)
    parser.add_argument('--end', type=date.fromisoformat, default=END_DATE)
    args = parser.parse_args()
    rows = generate_appointment_events(args.count, args.seed, start=args.start, end=args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output.with_suffix(args.output.suffix + '.manifest.json')
    if args.output.exists() or manifest_path.exists():
        parser.error('output CSV and manifest paths must both be new')
    status_counts = {}
    with args.output.open('x', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            status = row['appointment_status']
            status_counts[status] = status_counts.get(status, 0) + 1
            writer.writerow({key: value.isoformat() if isinstance(value, datetime) else value
                             for key, value in row.items()})
    manifest = {'count': args.count, 'seed': args.seed, 'start': args.start.isoformat(),
                'end': args.end.isoformat(), 'status_counts': status_counts,
                'synthetic_only': True, 'csv': str(args.output)}
    with manifest_path.open('x', encoding='utf-8') as file:
        file.write(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
