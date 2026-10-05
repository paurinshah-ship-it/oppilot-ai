"""Export synthetic employee/capacity/staffing CSVs into a new directory."""
import argparse
import csv
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_operations import START_DATE, END_DATE, FIELDS, generate_enterprise_operations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='Must not already exist')
    parser.add_argument('--start', type=date.fromisoformat, default=START_DATE)
    parser.add_argument('--end', type=date.fromisoformat, default=END_DATE)
    args = parser.parse_args()
    data = generate_enterprise_operations(args.start, args.end)
    args.output_dir.mkdir(exist_ok=False)
    for table, rows in data.items():
        with (args.output_dir / f'{table}.csv').open('x', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS[table], lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
    manifest = {'start': args.start.isoformat(), 'end': args.end.isoformat(),
                'rows': {table: len(rows) for table, rows in data.items()}, 'synthetic_only': True}
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
