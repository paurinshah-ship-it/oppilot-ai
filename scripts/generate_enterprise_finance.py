"""Generate deterministic synthetic enterprise encounters and payments."""
import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_appointments import DEFAULT_COUNT, END_DATE, START_DATE
from src.enterprise_finance import FIELDS, generate_enterprise_finance, validate_enterprise_finance


def _write(path, table, rows):
    if path.exists():
        raise FileExistsError(f'{path} already exists')
    with path.open('x', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS[table], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--count', type=int, default=DEFAULT_COUNT)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--start', type=__import__('datetime').date.fromisoformat, default=START_DATE)
    parser.add_argument('--end', type=__import__('datetime').date.fromisoformat, default=END_DATE)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = generate_enterprise_finance(args.count, args.seed, start=args.start, end=args.end)
    for table, rows in data.items():
        _write(args.output_dir / f'{table}.csv', table, rows)
    manifest = {'count': args.count, 'seed': args.seed, 'start': args.start.isoformat(),
                'end': args.end.isoformat(), **validate_enterprise_finance(data)}
    manifest_path = args.output_dir / 'enterprise-finance.manifest.json'
    if manifest_path.exists():
        parser.error('manifest path must be new')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
