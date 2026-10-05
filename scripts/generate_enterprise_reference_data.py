"""Export the deterministic Phase 1B reference fixture as JSON; no database access."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.enterprise_reference import generate_enterprise_reference_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New JSON output path; existing files are never overwritten')
    args = parser.parse_args()
    data = generate_enterprise_reference_data()
    # Exclusive creation protects the existing provider-day CSV and other files.
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write('\n')
    print('Generated synthetic reference data: ' + ', '.join(f'{len(rows)} {table}' for table, rows in data.items()))


if __name__ == '__main__':
    main()
