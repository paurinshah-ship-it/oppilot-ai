"""Reproducible, aggregate synthetic data. No patient records or PHI."""
from pathlib import Path
import random
import math
from datetime import date as calendar_date, timedelta
import pandas as pd

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "provider_performance.csv"


SPECIALTIES = [
    ("Primary Care", 155, 20), ("Cardiology", 245, 15),
    ("Dermatology", 205, 22), ("Orthopedics", 265, 16),
    ("Neurology", 250, 14), ("Gastroenterology", 240, 17),
    ("Endocrinology", 190, 18), ("Pulmonology", 225, 16),
    ("Rheumatology", 215, 15), ("Urology", 235, 18),
    ("Ophthalmology", 210, 24), ("Otolaryngology", 220, 20),
]
# Invented demo identities. No real clinician directory or patient data is used.
FIRST_NAMES = ["Maya", "Ethan", "Sofia", "Liam", "Aria", "Noah", "Isla", "Owen",
               "Zara", "Leo", "Nina", "Theo", "Elena", "Lucas", "Priya", "Miles",
               "Anika", "Felix", "Clara", "Arjun", "Leila", "Oscar", "Mira", "Hugo",
               "Ada", "Ravi", "Eva", "Jasper", "Lina", "Kai", "Nora", "Rohan",
               "Amara", "Finn", "Iris", "Kiran", "Tessa", "Eli", "Rhea", "Luca",
               "Freya", "Dev", "Cora", "Soren", "Sana", "Jude", "Vera", "Nico"]
LAST_NAMES = ["Patel", "Chen", "Rivera", "Brooks", "Shah", "Bennett", "Morgan", "Reed",
              "Hayes", "Kim", "Park", "Ellis", "Rao", "Foster", "Mehta", "Cole",
              "Singh", "Hart", "Price", "Kapoor", "Stone", "Wells", "Desai", "Lane",
              "Ross", "Malik", "Ward", "Blake", "Grant", "Lin", "Young", "Joshi",
              "James", "Scott", "Bell", "Nair", "Adams", "Clark", "Sethi", "Gray",
              "Hill", "Kumar", "West", "Fox", "Ali", "Wood", "Hall", "King"]
PROVIDER_NAMES = [f"Dr. {first} {last}" for first, last in zip(FIRST_NAMES, LAST_NAMES)]


def generate_data(seed: int = 42, start: str = "2021-01-01", days: int = 1826) -> pd.DataFrame:
    """Five complete calendar years by default: Jan 2021–Dec 2025.

    Each of 48 fictional providers has staffed weekdays minus simulated leave.
    Capacity = round(specialty daily slots × FTE); hours = 8 × FTE.
    Booking fill = provider baseline + provider annual trend × elapsed years
    + 0.04 × sin(2π × (month−1)/12) + daily noise, capped to [0, 1].
    Bookings = rounded capacity × fill. No-shows are sampled at a provider-
    specific probability; visits = bookings − no-shows.
    Revenue = visits × specialty rate × 1.025^elapsed_years × daily rate noise.
    Trends, seasonality, and 2.5% annual rate growth are simulation assumptions,
    not inferred real-world effects. All amounts are nominal synthetic dollars.
    """
    if days < 1:
        raise ValueError("days must be positive")
    end = calendar_date.fromisoformat(start) + timedelta(days=days - 1)
    rng = random.Random(seed)
    rows = []
    dates = pd.bdate_range(start, end)
    for i, name in enumerate(PROVIDER_NAMES):
        specialty, rate, daily_slots = SPECIALTIES[i % len(SPECIALTIES)]
        fill = rng.uniform(.65, .92)
        trend = rng.uniform(-.025, .025)
        no_show_rate = rng.uniform(.025, .13)
        fte = rng.choice([.8, 1.0, 1.0])
        for date in dates:
            if rng.random() < .06:
                continue
            elapsed = (date.date() - calendar_date.fromisoformat(start)).days / 365.25
            seasonal = .04 * math.sin(2 * math.pi * (date.month - 1) / 12)
            capacity = round(daily_slots * fte)
            booked = min(capacity, max(0, round(capacity * (fill + trend * elapsed + seasonal + rng.uniform(-.10, .10)))))
            no_shows = sum(rng.random() < no_show_rate for _ in range(booked))
            visits = booked - no_shows
            rows.append({"date": date.date().isoformat(), "provider_id": f"SYN-{i+1:03d}",
                         "provider": name, "specialty": specialty,
                         "clinic": ["North Clinic", "Central Clinic", "South Clinic", "East Clinic", "West Clinic", "Lakeside Clinic"][i % 6],
                         "fte": fte, "staffed_hours": 8 * fte, "capacity": capacity,
                         "booked": booked, "no_shows": no_shows, "visits": visits,
                         "revenue": round(visits * rate * (1.025 ** elapsed) * rng.uniform(.92, 1.08), 2)})
    return pd.DataFrame(rows)


def validate_data(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the provider-day contract before calculating any metrics."""
    required = {"date", "provider_id", "provider", "specialty", "clinic", "fte",
                "staffed_hours", "capacity", "booked", "no_shows", "visits", "revenue"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
    if df.empty:
        raise ValueError("The CSV contains no provider-day records.")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    numeric = ["fte", "staffed_hours", "capacity", "booked", "no_shows", "visits", "revenue"]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    if df[list(required)].isna().any().any():
        raise ValueError("Required CSV values must be present with valid dates and numbers.")
    for column in ["provider_id", "provider", "specialty", "clinic"]:
        if df[column].astype(str).str.strip().eq("").any():
            raise ValueError(f"{column} cannot be blank.")
    if not df[numeric].apply(lambda s: s.between(0, float('inf'), inclusive="left")).all().all():
        raise ValueError("Numeric values must be finite and nonnegative.")
    if (df[["capacity", "booked", "no_shows", "visits"]] % 1 != 0).any().any():
        raise ValueError("Appointment and visit counts must be whole numbers.")
    if (df.fte <= 0).any() or (df.staffed_hours <= 0).any() or (df.capacity <= 0).any():
        raise ValueError("Staffed provider-days require positive FTE, hours, and capacity.")
    if (df.booked > df.capacity).any() or (df.visits + df.no_shows != df.booked).any():
        raise ValueError("Counts must satisfy visits + no-shows = booked <= capacity.")
    if df.duplicated(["date", "provider_id"]).any():
        raise ValueError("Duplicate provider-day records would double-count KPIs.")
    if (df.groupby("provider_id")[["provider", "specialty", "clinic"]].nunique() > 1).any().any():
        raise ValueError("Each provider ID must map to one name, specialty, and clinic in this MVP.")
    return df.sort_values(["date", "provider_id"]).reset_index(drop=True)


def load_data(path: Path = DATA_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError("Run python scripts/generate_data.py first.")
    return validate_data(pd.read_csv(path))
