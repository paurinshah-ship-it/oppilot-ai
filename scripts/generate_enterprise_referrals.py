"""Generate deterministic synthetic enterprise referrals."""
import argparse
import csv
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_operations import START_DATE, END_DATE
from src.enterprise_referrals import DEFAULT_COUNT, FIELDS, generate_referrals, validate_referrals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=DEFAULT_COUNT)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--start', type=date.fromisoformat, default=START_DATE)
    parser.add_argument('--end', type=date.fromisoformat, default=END_DATE)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output path must be new')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = generate_referrals(args.count, args.seed, start=args.start, end=args.end)
    with args.output.open('x', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    manifest = {'count': args.count, 'seed': args.seed, 'start': args.start.isoformat(),
                'end': args.end.isoformat(), **validate_referrals(rows)}
    manifest_path = args.output.with_suffix(args.output.suffix + '.manifest.json')
    if manifest_path.exists():
        parser.error('manifest path must be new')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
