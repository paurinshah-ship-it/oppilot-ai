"""PostgreSQL storage and allowlisted analytics SQL for the synthetic demo.

The Copilot never receives permission to submit SQL.  It creates a semantic
request using catalog metric and dimension keys; this module validates those
keys and interpolates only fixed SQL fragments.  User values are bound as
parameters.  PostgreSQL is the system of record when ``DATABASE_URL`` is set;
Pandas remains a presentation/dataframe adapter for Streamlit and Plotly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DATABASE_URL_ENV = "DATABASE_URL"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


@dataclass(frozen=True)
class AnalyticsRequest:
    """A restricted analytical representation, never a raw SQL container."""

    metric: str
    dimensions: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    providers: tuple[str, ...] = ()
    specialties: tuple[str, ...] = ()
    clinics: tuple[str, ...] = ()
    target_utilization: float = 0.85


@dataclass(frozen=True)
class CompiledAnalyticsQuery:
    sql: str
    params: dict[str, Any]
    request: AnalyticsRequest


# These are deliberately complete SQL expressions, not names obtained from a
# question.  Ratios use sums of raw measures so grouping never averages rates.
METRIC_SQL = {
    "completed_visits": "SUM(pe.completed_visits)",
    "capacity": "SUM(a.available_slots)",
    "utilization": "SUM(pe.completed_visits)::numeric / NULLIF(SUM(a.available_slots), 0)",
    "no_show_rate": "SUM(a.no_shows)::numeric / NULLIF(SUM(a.booked_appointments), 0)",
    "revenue": "SUM(pe.realized_revenue)",
    "revenue_per_visit": "SUM(pe.realized_revenue) / NULLIF(SUM(pe.completed_visits), 0)",
    "productivity": "SUM(pe.completed_visits) / NULLIF(SUM(pe.staffed_hours), 0)",
    "unused_capacity": "SUM(a.available_slots) - SUM(pe.completed_visits)",
    "revenue_opportunity": (
        "SUM(GREATEST(0, :target_utilization * provider_totals.capacity - provider_totals.visits) "
        "* provider_totals.revenue / NULLIF(provider_totals.visits, 0))"
    ),
}

DIMENSION_SQL = {
    "provider": ("p.provider_id", "p.provider_name"),
    "specialty": ("s.specialty_name",),
    "clinic": ("p.clinic_name",),
    "month": ("DATE_TRUNC('month', pe.performance_date)::date",),
}

BASE_FROM = """
FROM performance pe
JOIN appointment a ON a.provider_id = pe.provider_id AND a.appointment_date = pe.performance_date
JOIN provider p ON p.provider_id = pe.provider_id
JOIN specialty s ON s.specialty_id = p.specialty_id
"""


def database_url() -> str | None:
    """Return configured connection URL without exposing it in UI or logs."""
    value = os.getenv(DATABASE_URL_ENV, "").strip()
    return value or None


def postgres_configured() -> bool:
    return database_url() is not None


def _validate_request(request: AnalyticsRequest) -> None:
    if request.metric not in METRIC_SQL:
        raise ValueError("Metric is not in the allowlisted PostgreSQL analytics catalog.")
    if len(set(request.dimensions)) != len(request.dimensions) or any(d not in DIMENSION_SQL for d in request.dimensions):
        raise ValueError("Dimensions must be unique catalog dimensions.")
    if request.start_date and request.end_date and request.start_date > request.end_date:
        raise ValueError("Start date cannot be after end date.")
    if not 0 <= request.target_utilization <= 1:
        raise ValueError("Target utilization must be between zero and one.")


def compile_analytics_sql(request: AnalyticsRequest) -> CompiledAnalyticsQuery:
    """Compile a validated request to one parameterized read-only SQL query."""
    _validate_request(request)
    dimensions = tuple(column for key in request.dimensions for column in DIMENSION_SQL[key])
    select_dimensions = [f"{column} AS {alias}" for column, alias in _dimension_aliases(request.dimensions)]
    params: dict[str, Any] = {"target_utilization": request.target_utilization}
    where: list[str] = []
    if request.start_date:
        where.append("pe.performance_date >= :start_date")
        params["start_date"] = request.start_date
    if request.end_date:
        where.append("pe.performance_date <= :end_date")
        params["end_date"] = request.end_date
    for parameter, column, values in (
        ("provider_ids", "p.provider_id", request.providers),
        ("specialty_names", "s.specialty_name", request.specialties),
        ("clinic_names", "p.clinic_name", request.clinics),
    ):
        if values:
            where.append(f"{column} = ANY(:{parameter})")
            params[parameter] = list(values)
    if request.metric == "revenue_opportunity":
        return _compile_opportunity_sql(request, dimensions, select_dimensions, where, params)
    metric_sql = METRIC_SQL[request.metric]
    select = ",\n       ".join(select_dimensions + [f"{metric_sql} AS {request.metric}"])
    sql = f"SELECT {select}\n{BASE_FROM}"
    if where:
        sql += "WHERE " + " AND ".join(where) + "\n"
    if dimensions:
        sql += "GROUP BY " + ", ".join(dimensions) + "\nORDER BY " + ", ".join(dimensions)
    return CompiledAnalyticsQuery(sql=sql, params=params, request=request)


def _compile_opportunity_sql(request, dimensions, select_dimensions, where, params):
    """Compile the established per-provider opportunity formula safely.

    Rates are calculated per provider before dimension rollup.  This matches the
    existing metric definition and avoids applying one average revenue rate to
    all providers.
    """
    group_columns = list(dimensions) + ["p.provider_id"]
    provider_dimensions = ",\n       ".join(select_dimensions)
    if provider_dimensions:
        provider_dimensions += ",\n       "
    inner = (
        "WITH provider_totals AS (\n"
        f"SELECT {provider_dimensions}p.provider_id,\n"
        "       SUM(a.available_slots) AS capacity, SUM(pe.completed_visits) AS visits,\n"
        "       SUM(pe.realized_revenue) AS revenue\n"
        f"{BASE_FROM}"
    )
    if where:
        inner += "WHERE " + " AND ".join(where) + "\n"
    inner += "GROUP BY " + ", ".join(group_columns) + "\n)\n"
    output_dimensions = [alias for _, alias in _dimension_aliases(request.dimensions)]
    select = ", ".join(output_dimensions + [
        "SUM(GREATEST(0, :target_utilization * capacity - visits) * revenue / NULLIF(visits, 0)) AS revenue_opportunity"
    ])
    sql = inner + "SELECT " + select + "\nFROM provider_totals\n"
    if output_dimensions:
        sql += "GROUP BY " + ", ".join(output_dimensions) + "\nORDER BY " + ", ".join(output_dimensions)
    return CompiledAnalyticsQuery(sql=sql, params=params, request=request)


def _dimension_aliases(dimensions: Iterable[str]) -> list[tuple[str, str]]:
    aliases = {"p.provider_id": "provider_id", "p.provider_name": "provider", "s.specialty_name": "specialty",
               "p.clinic_name": "clinic", "DATE_TRUNC('month', pe.performance_date)::date": "month"}
    return [(column, aliases[column]) for key in dimensions for column in DIMENSION_SQL[key]]


def request_from_semantic_plan(plan: dict[str, Any], metric: str, *, target_utilization: float,
                               provider_ids: Iterable[str] = (), fallback_start: date | None = None,
                               fallback_end: date | None = None) -> AnalyticsRequest:
    """Translate an existing deterministic Copilot plan to a SQL-safe request.

    Only catalog keys survive this boundary.  The plan is never treated as SQL
    text, and provider IDs originate from the dashboard's already-scoped data.
    """
    period = plan.get("date_range", {})
    if period.get("status") == "ok":
        start_date, end_date = period.get("effective_start"), period.get("effective_end")
    else:
        # No natural-language period means preserve the dashboard's current
        # filtered period; never expand a scoped question to all database rows.
        start_date, end_date = fallback_start, fallback_end
    dimensions = tuple(plan.get("dimensions", ()))
    return AnalyticsRequest(
        metric=metric,
        dimensions=dimensions,
        start_date=start_date,
        end_date=end_date,
        providers=tuple(sorted(set(provider_ids))),
        target_utilization=target_utilization,
    )


class PostgresRepository:
    """Small psycopg adapter. It imports lazily so CSV fallback stays usable."""

    def __init__(self, url: str | None = None):
        self.url = url or database_url()
        if not self.url:
            raise ValueError("DATABASE_URL is required for PostgreSQL storage.")

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] to use PostgreSQL storage.") from exc
        return psycopg.connect(self.url)

    def initialize_schema(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(SCHEMA_PATH.read_text())

    def provider_day_frame(self) -> pd.DataFrame:
        """Read the validated dashboard contract from normalized PostgreSQL tables."""
        sql = """
        SELECT pe.performance_date AS date, p.provider_id, p.provider_name AS provider,
               s.specialty_name AS specialty, p.clinic_name AS clinic, pe.fte, pe.staffed_hours,
               a.available_slots AS capacity, a.booked_appointments AS booked, a.no_shows,
               pe.completed_visits AS visits, pe.realized_revenue AS revenue
        """ + BASE_FROM + "ORDER BY pe.performance_date, p.provider_id"
        with self._connect() as connection:
            return pd.read_sql_query(sql, connection)

    def execute(self, request: AnalyticsRequest) -> pd.DataFrame:
        compiled = compile_analytics_sql(request)
        with self._connect() as connection:
            return pd.read_sql_query(compiled.sql, connection, params=compiled.params)


def load_dashboard_data() -> pd.DataFrame:
    """Return normalized PostgreSQL data when configured, otherwise demo CSV.

    The fallback keeps the repository runnable for portfolio demonstrations.
    Deployments set DATABASE_URL and use PostgreSQL as the source of record.
    """
    if postgres_configured():
        return PostgresRepository().provider_day_frame()
    from src.data import load_data
    return load_data()
