"""Generate deterministic portfolio-demo anomalous enterprise data summary."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.enterprise_anomalies import apply_anomalies, generate_enterprise_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--appointment-count', type=int, default=10_000)
    parser.add_argument('--referral-count', type=int, default=5_000)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    baseline = generate_enterprise_dataset(args.appointment_count, args.referral_count, args.seed)
    anomalous, truth = apply_anomalies(baseline)
    summary = {
        'appointment_count': args.appointment_count,
        'referral_count': args.referral_count,
        'truth_count': len(truth),
        'anomaly_types': [row['anomaly_type'] for row in truth],
        'anomalous_counts': {
            'appointment_event': len(anomalous['appointment_event']),
            'encounter': len(anomalous['finance']['encounter']),
            'payment': len(anomalous['finance']['payment']),
            'referral': len(anomalous['referral']),
            'ground_truth_anomaly': len(truth),
        },
    }
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
