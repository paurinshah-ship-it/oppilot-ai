"""Run from any directory to regenerate the fixed-seed demo dataset."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data import DATA_PATH, generate_data

if __name__ == "__main__":
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    df = generate_data()
    df.to_csv(DATA_PATH, index=False)
    print(f"Wrote {len(df):,} synthetic provider-day rows to {DATA_PATH}")
