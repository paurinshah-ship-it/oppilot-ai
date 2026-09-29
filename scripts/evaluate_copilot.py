"""Run the 1,000-case deterministic Copilot evaluation and write CSV results.

No model or credentials are used. Expected values are independently calculated
from synthetic provider-day rows; the CSV is safe to publish as an evaluation
artifact because it contains no PHI or free-form model output.
"""
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.copilot_evaluation import evaluate_suite
from src.data import load_data


def evaluate(output_path=None, count=1000):
    rows = evaluate_suite(load_data(), count=count,
                          progress=lambda completed, total: print(f"Evaluated {completed:,}/{total:,} cases"))
    path = output_path or Path(__file__).resolve().parents[1] / "ai_evaluation.csv"
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    results = evaluate()
    failures = sum(row["evaluation_result"] == "FAIL" for row in results)
    print(f"{len(results) - failures}/{len(results)} evaluation cases passed. Results: ai_evaluation.csv")
    raise SystemExit(bool(failures))
