"""Financial enterprise tool shortcuts with semantic guardrails."""
from __future__ import annotations

from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric


FINANCIAL_METRICS = ("modeled_revenue", "modeled_charges", "allowed_amount",
                     "paid_amount", "patient_amount", "adjustment_amount",
                     "revenue_per_completed_visit", "allowed_amount_per_encounter",
                     "paid_amount_per_encounter")


def get_financial_summary(metric: str = "paid_amount", **kwargs):
    if metric not in FINANCIAL_METRICS:
        raise ValueError("Choose a financial metric; paid_amount is not profit and modeled_revenue is not collections.")
    return compile_enterprise_metric(EnterpriseMetricRequest(metric=metric, **kwargs))

