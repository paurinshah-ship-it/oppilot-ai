"""Evidence-only enterprise summary helpers."""
from __future__ import annotations

from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric


def get_practice_snapshot(practice_id: int, metric: str = "completed_visits", start_date=None, end_date=None):
    return compile_enterprise_metric(EnterpriseMetricRequest(metric=metric, dimensions=("practice",),
                                                            start_date=start_date, end_date=end_date,
                                                            practice_ids=(practice_id,)))


def get_provider_capacity_summary(**kwargs):
    return compile_enterprise_metric(EnterpriseMetricRequest(metric="blocked_slot_rate", **kwargs))


def get_staffing_summary(**kwargs):
    return compile_enterprise_metric(EnterpriseMetricRequest(metric="staffing_gap_fte", **kwargs))


def get_referral_summary(**kwargs):
    return compile_enterprise_metric(EnterpriseMetricRequest(metric="referral_conversion_rate", **kwargs))

