"""Weighted metrics and explicit scenario assumptions."""
import pandas as pd


def calculate_kpis(df: pd.DataFrame) -> dict:
    """Visits = sum(visits); capacity = sum(capacity); revenue = sum(revenue).
    Utilization = sum(visits) / sum(capacity).
    Productivity = sum(visits) / sum(staffed_hours).
    Unused capacity = sum(capacity) − sum(visits).
    Sum additive measures first; ratios are never averages of daily rates.

    Productivity means completed visits per staffed hour. Zero denominators
    return 0 for empty selections; the UI displays an empty-state message.
    """
    visits = int(df.visits.sum())
    capacity = int(df.capacity.sum())
    hours = float(df.staffed_hours.sum())
    return {"visits": visits, "capacity": capacity,
            "revenue": float(df.revenue.sum()),
            "utilization": visits / capacity if capacity else 0.0,
            "productivity": visits / hours if hours else 0.0,
            "unused_capacity": capacity - visits}


def monthly_performance(df: pd.DataFrame) -> pd.DataFrame:
    """For each calendar month, sum visits, capacity, and revenue."""
    return (df.assign(month=df.date.dt.to_period("M").dt.to_timestamp())
            .groupby("month", as_index=False)[["visits", "capacity", "revenue"]].sum())


def benchmark(df: pd.DataFrame, target: float = .85) -> pd.DataFrame:
    """Aggregate by provider over the filtered period.

    All source measures are summed before division.
    utilization = visits / capacity; visits_per_hour = visits / staffed_hours.
    unused_capacity = capacity − visits.
    unbooked_slots = capacity − booked; no_shows = booked − visits.
    booking_rate = booked / capacity; no_show_rate = no_shows / booked.
    revenue_per_visit = revenue / visits (0 fallback when no visits).
    recoverable_visits = max(0, target × capacity − visits).
    opportunity = recoverable_visits × revenue_per_visit; no cost adjustment.
    peer_utilization = specialty total visits / specialty total capacity,
    including self within current filters.
    peer_productivity = specialty total visits / specialty total staffed hours.
    utilization_gap_pp = 100 × (provider utilization − peer utilization).
    productivity_index = provider productivity / specialty productivity.
    Zero denominators yield 0; singleton peer groups are flagged separately.
    """
    if not 0 <= target <= 1:
        raise ValueError("Target utilization must be between 0 and 1.")
    out = df.groupby(["provider_id", "provider", "specialty", "clinic"], as_index=False).agg(
        visits=("visits", "sum"), capacity=("capacity", "sum"), booked=("booked", "sum"),
        revenue=("revenue", "sum"), staffed_hours=("staffed_hours", "sum"))
    out["utilization"] = out.visits.div(out.capacity.where(out.capacity.ne(0))).fillna(0)
    out["visits_per_hour"] = out.visits.div(out.staffed_hours.where(out.staffed_hours.ne(0))).fillna(0)
    out["unused_capacity"] = out.capacity - out.visits
    out["revenue_per_visit"] = out.revenue.div(out.visits.where(out.visits.ne(0))).fillna(0)
    out["recoverable_visits"] = (target * out.capacity - out.visits).clip(lower=0)
    out["opportunity"] = out.recoverable_visits * out.revenue_per_visit
    out["unbooked_slots"] = out.capacity - out.booked
    out["no_shows"] = out.booked - out.visits
    out["booking_rate"] = out.booked.div(out.capacity.where(out.capacity.ne(0))).fillna(0)
    out["no_show_rate"] = out.no_shows.div(out.booked.where(out.booked.ne(0))).fillna(0)
    out["revenue_rate_known"] = out.visits.gt(0)
    peers = out.groupby("specialty")[["visits", "capacity", "staffed_hours"]].sum()
    out["peer_utilization"] = out.specialty.map(peers.visits.div(peers.capacity.where(peers.capacity.ne(0))).fillna(0))
    out["peer_productivity"] = out.specialty.map(
        peers.visits.div(peers.staffed_hours.where(peers.staffed_hours.ne(0))).fillna(0))
    out["peer_count"] = out.specialty.map(out.groupby("specialty").provider_id.nunique())
    out["utilization_gap_pp"] = 100 * (out.utilization - out.peer_utilization)
    out["productivity_index"] = out.visits_per_hour.div(
        out.peer_productivity.where(out.peer_productivity.ne(0))).fillna(0)
    return out.sort_values("opportunity", ascending=False)



def detect_opportunities(providers: pd.DataFrame, target: float = .85) -> pd.DataFrame:
    """Return actionable scenario flags; thresholds are illustrative, not standards.

    Below target: utilization < target.
    Booking gap: unbooked_slots / capacity >= 0.15.
    No-show gap: no_shows / booked >= 0.10.
    Peer gap: utilization_gap_pp <= −5 and at least 2 selected specialty peers.
    Monetary values use benchmark opportunity; flags do not add new opportunity
    amounts, so overlapping flags are never double-counted.
    """
    out = providers.copy()
    def flags(row):
        reasons = []
        if row.utilization < target:
            reasons.append("Below utilization target")
        if row.capacity and row.unbooked_slots / row.capacity >= .15:
            reasons.append("Unbooked slots ≥15%")
        if row.no_show_rate >= .10:
            reasons.append("No-shows ≥10%")
        if row.peer_count >= 2 and row.utilization_gap_pp <= -5:
            reasons.append("Utilization ≥5 pp below specialty")
        if not row.revenue_rate_known:
            reasons.append("Revenue rate unavailable")
        return "; ".join(reasons)
    out["signals"] = out.apply(flags, axis=1) if not out.empty else ""
    return out[out.signals.ne("")].sort_values("opportunity", ascending=False)


def answer(question: str, providers: pd.DataFrame, target: float) -> str:
    """Deterministic starter copilot; no external AI service or data transmission."""
    q = question.lower()
    if providers.empty:
        return "No data matches the current filters. Broaden your selection."
    if any(word in q for word in ["opportunity", "improve", "unused"]):
        top = providers.iloc[0]
        return (f"Estimated revenue opportunity is ${providers.opportunity.sum():,.0f} at a "
                f"{target:.0%} completed-visit utilization target. {top['provider']} has the largest "
                f"modeled gap (${top.opportunity:,.0f}). Review scheduling demand and staffing before acting.")
    if any(word in q for word in ["benchmark", "best", "top", "productive"]):
        top = providers.sort_values("visits_per_hour", ascending=False).iloc[0]
        return (f"{top['provider']} has the highest visits per staffed hour ({top.visits_per_hour:.2f}) "
                f"in this selection. Compare within specialties; visit complexity differs.")
    if any(word in q for word in ["visits", "revenue", "summary", "summarize", "performance", "utilization"]):
        kpis = calculate_kpis(providers)
        return (f"This selection has {providers.visits.sum():,.0f} completed visits, "
                f"${providers.revenue.sum():,.0f} synthetic revenue, and "
                f"{kpis['utilization']:.1%} weighted utilization.")
    return "I can answer about summary metrics, visits, revenue, utilization, benchmarks, or opportunity. Try: Where is the largest opportunity?"
