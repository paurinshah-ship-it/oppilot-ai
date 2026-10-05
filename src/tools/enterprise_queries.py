"""Safe deterministic enterprise SQL compiler and structured result helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.tools.enterprise_metrics import DIMENSIONS, FORBIDDEN_TABLES, METRICS, MetricDefinition


@dataclass(frozen=True)
class EnterpriseMetricRequest:
    metric: str
    dimensions: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    organization_ids: tuple[int, ...] = ()
    region_ids: tuple[int, ...] = ()
    practice_ids: tuple[int, ...] = ()
    specialty_ids: tuple[int, ...] = ()
    provider_ids: tuple[str, ...] = ()
    limit: int = 500


@dataclass(frozen=True)
class CompiledEnterpriseQuery:
    sql: str
    params: dict[str, Any]
    request: EnterpriseMetricRequest
    definition: MetricDefinition


@dataclass(frozen=True)
class EnterpriseMetricResult:
    metric: str
    value: float | int | None
    unit: str
    formula: str
    period: dict[str, str | None]
    scope: dict[str, Any] = field(default_factory=dict)
    numerator: float | int | None = None
    denominator: float | int | None = None
    entity_count: int | None = None


DIMENSION_SQL = {
    "organization": ("o.organization_id", "o.organization_name"),
    "region": ("r.region_id", "r.region_name"),
    "practice": ("pr.practice_id", "pr.practice_name"),
    "specialty": ("s.specialty_id", "s.specialty_name"),
    "provider": ("p.provider_id", "p.provider_name"),
    "month": ("DATE_TRUNC('month', {date_column})::date",),
}
ALIASES = {
    "o.organization_id": "organization_id", "o.organization_name": "organization",
    "r.region_id": "region_id", "r.region_name": "region",
    "pr.practice_id": "practice_id", "pr.practice_name": "practice",
    "s.specialty_id": "specialty_id", "s.specialty_name": "specialty",
    "p.provider_id": "provider_id", "p.provider_name": "provider",
}
FROM_SQL = {
    "appointment": ("appointment_event e", "e.appointment_date", "JOIN provider p ON p.provider_id = e.provider_id JOIN specialty s ON s.specialty_id = p.specialty_id JOIN practice pr ON pr.practice_id = e.practice_id JOIN region r ON r.region_id = pr.region_id JOIN organization o ON o.organization_id = r.organization_id"),
    "capacity": ("provider_capacity pc", "pc.capacity_date", "JOIN provider p ON p.provider_id = pc.provider_id JOIN specialty s ON s.specialty_id = p.specialty_id JOIN practice pr ON pr.practice_id = p.practice_id JOIN region r ON r.region_id = pr.region_id JOIN organization o ON o.organization_id = r.organization_id"),
    "staffing": ("staffing_daily sd", "sd.staff_date", "JOIN practice pr ON pr.practice_id = sd.practice_id JOIN region r ON r.region_id = pr.region_id JOIN organization o ON o.organization_id = r.organization_id LEFT JOIN provider p ON false LEFT JOIN specialty s ON false"),
    "referral": ("referral rf", "rf.referral_date", "JOIN practice pr ON pr.practice_id = rf.practice_id JOIN specialty s ON s.specialty_id = rf.specialty_id JOIN region r ON r.region_id = pr.region_id JOIN organization o ON o.organization_id = r.organization_id LEFT JOIN provider p ON false"),
    "finance": ("encounter en JOIN payment py ON py.encounter_id = en.encounter_id", "en.encounter_date", "JOIN provider p ON p.provider_id = en.provider_id JOIN specialty s ON s.specialty_id = p.specialty_id JOIN practice pr ON pr.practice_id = en.practice_id JOIN region r ON r.region_id = pr.region_id JOIN organization o ON o.organization_id = r.organization_id"),
    "productivity": ("provider_capacity pc LEFT JOIN appointment_event e ON e.provider_id = pc.provider_id AND e.appointment_date = pc.capacity_date", "pc.capacity_date", "JOIN provider p ON p.provider_id = pc.provider_id JOIN specialty s ON s.specialty_id = p.specialty_id JOIN practice pr ON pr.practice_id = p.practice_id JOIN region r ON r.region_id = pr.region_id JOIN organization o ON o.organization_id = r.organization_id"),
}
SOURCE_DIMENSIONS = {
    "appointment": set(DIMENSIONS),
    "capacity": set(DIMENSIONS),
    "productivity": set(DIMENSIONS),
    "finance": set(DIMENSIONS),
    "staffing": {"organization", "region", "practice", "month"},
    "referral": {"organization", "region", "practice", "specialty", "month"},
}


def _validate_request(request: EnterpriseMetricRequest) -> MetricDefinition:
    if request.metric not in METRICS:
        raise ValueError("Metric is not in the enterprise tool catalog.")
    definition = METRICS[request.metric]
    if len(set(request.dimensions)) != len(request.dimensions) or any(d not in DIMENSIONS for d in request.dimensions):
        raise ValueError("Dimensions must be unique enterprise catalog dimensions.")
    if any(d not in SOURCE_DIMENSIONS[definition.source] for d in request.dimensions):
        raise ValueError("Dimension is not supported for this metric source.")
    if request.start_date and request.end_date and request.start_date > request.end_date:
        raise ValueError("Start date cannot be after end date.")
    if not 1 <= request.limit <= 5000:
        raise ValueError("Limit must be between 1 and 5000.")
    return definition


def compile_enterprise_metric(request: EnterpriseMetricRequest) -> CompiledEnterpriseQuery:
    definition = _validate_request(request)
    table, date_column, joins = FROM_SQL[definition.source]
    select_dimensions, group_dimensions = [], []
    for dimension in request.dimensions:
        for column in DIMENSION_SQL[dimension]:
            rendered = column.format(date_column=date_column)
            alias = "month" if dimension == "month" else ALIASES[rendered]
            select_dimensions.append(f"{rendered} AS {alias}")
            group_dimensions.append(rendered)
    metric_columns = [f"{definition.expression} AS value"]
    if definition.numerator:
        metric_columns.append(f"{definition.numerator} AS numerator")
    if definition.denominator:
        metric_columns.append(f"{definition.denominator} AS denominator")
    metric_columns.append("COUNT(DISTINCT pr.practice_id) AS entity_count")
    where, params = [], {"limit": request.limit}
    if request.start_date:
        where.append(f"{date_column} >= :start_date")
        params["start_date"] = request.start_date
    if request.end_date:
        where.append(f"{date_column} <= :end_date")
        params["end_date"] = request.end_date
    for name, column, values in (
        ("organization_ids", "o.organization_id", request.organization_ids),
        ("region_ids", "r.region_id", request.region_ids),
        ("practice_ids", "pr.practice_id", request.practice_ids),
        ("specialty_ids", "s.specialty_id", request.specialty_ids),
        ("provider_ids", "p.provider_id", request.provider_ids),
    ):
        if values:
            where.append(f"{column} = ANY(:{name})")
            params[name] = list(values)
    select = ", ".join(select_dimensions + metric_columns)
    sql = f"SELECT {select}\nFROM {table}\n{joins}\n"
    if where:
        sql += "WHERE " + " AND ".join(where) + "\n"
    if group_dimensions:
        sql += "GROUP BY " + ", ".join(group_dimensions) + "\nORDER BY " + ", ".join(group_dimensions) + "\n"
    sql += "LIMIT :limit"
    _assert_safe_sql(sql)
    return CompiledEnterpriseQuery(sql, params, request, definition)


def _assert_safe_sql(sql: str) -> None:
    lowered = sql.lower()
    if any(table in lowered for table in FORBIDDEN_TABLES):
        raise ValueError("Ground truth tables are not available to agent-facing tools.")
    for token in (";", "--", "/*", "*/", " drop ", " delete ", " update ", " insert ", " alter "):
        if token in lowered:
            raise ValueError("Compiled enterprise SQL failed safety validation.")


def structured_result(compiled: CompiledEnterpriseQuery, row: dict[str, Any]) -> EnterpriseMetricResult:
    scope = {key: row[key] for key in row if key not in {"value", "numerator", "denominator", "entity_count"}}
    return EnterpriseMetricResult(
        metric=compiled.request.metric,
        value=row.get("value"),
        unit=compiled.definition.unit,
        formula=compiled.definition.formula,
        period={"start": None if compiled.request.start_date is None else compiled.request.start_date.isoformat(),
                "end": None if compiled.request.end_date is None else compiled.request.end_date.isoformat()},
        scope=scope,
        numerator=row.get("numerator"),
        denominator=row.get("denominator"),
        entity_count=row.get("entity_count"),
    )

