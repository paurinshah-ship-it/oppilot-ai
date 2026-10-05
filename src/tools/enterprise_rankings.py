"""Deterministic ranking query helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.tools.enterprise_metrics import METRICS
from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric


@dataclass(frozen=True)
class RankingRequest:
    metric: str
    dimensions: tuple[str, ...]
    start_date: date | None = None
    end_date: date | None = None
    descending: bool = True
    limit: int = 10


def rank_entities(request: RankingRequest):
    if request.metric not in METRICS:
        raise ValueError("Choose a catalog metric.")
    if not request.dimensions:
        raise ValueError("Rankings require at least one dimension.")
    compiled = compile_enterprise_metric(EnterpriseMetricRequest(
        request.metric, request.dimensions, request.start_date, request.end_date,
        limit=request.limit))
    order = "DESC" if request.descending else "ASC"
    body = compiled.sql.rsplit("LIMIT :limit", 1)[0]
    sql = f"SELECT * FROM (\n{body}) ranked\nORDER BY value {order} NULLS LAST, " + ", ".join(request.dimensions) + "\nLIMIT :limit"
    return type(compiled)(sql, compiled.params, compiled.request, compiled.definition)
