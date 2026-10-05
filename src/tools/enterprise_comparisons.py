"""Deterministic comparison helpers for enterprise metric results."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.tools.enterprise_metrics import METRICS
from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric


@dataclass(frozen=True)
class PeriodComparisonRequest:
    metric: str
    dimensions: tuple[str, ...] = ()
    current_start: date | None = None
    current_end: date | None = None
    comparison_start: date | None = None
    comparison_end: date | None = None
    practice_ids: tuple[int, ...] = ()


def compare_periods(request: PeriodComparisonRequest):
    if request.metric not in METRICS:
        raise ValueError("Choose a catalog metric.")
    current = compile_enterprise_metric(EnterpriseMetricRequest(
        request.metric, request.dimensions, request.current_start, request.current_end,
        practice_ids=request.practice_ids))
    comparison = compile_enterprise_metric(EnterpriseMetricRequest(
        request.metric, request.dimensions, request.comparison_start, request.comparison_end,
        practice_ids=request.practice_ids))
    change_kind = "percentage_point_change" if METRICS[request.metric].rate else "percent_change"
    return {"current": current, "comparison": comparison, "change_kind": change_kind}


def change_summary(current, comparison, metric):
    absolute = None if current is None or comparison is None else current - comparison
    percent = None
    pp = None
    if METRICS[metric].rate:
        pp = None if absolute is None else absolute
    elif comparison not in (None, 0) and absolute is not None:
        percent = absolute / comparison
    return {"current_value": current, "comparison_value": comparison,
            "absolute_change": absolute, "percent_change": percent,
            "percentage_point_change": pp}

