"""Monthly enterprise trend helpers."""
from __future__ import annotations

from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric


def get_metric_trend(metric: str, start_date=None, end_date=None, dimensions=(), **filters):
    dims = tuple(dict.fromkeys((*dimensions, "month")))
    return compile_enterprise_metric(EnterpriseMetricRequest(
        metric=metric, dimensions=dims, start_date=start_date, end_date=end_date,
        organization_ids=tuple(filters.get("organization_ids", ())),
        region_ids=tuple(filters.get("region_ids", ())),
        practice_ids=tuple(filters.get("practice_ids", ())),
        specialty_ids=tuple(filters.get("specialty_ids", ())),
        provider_ids=tuple(filters.get("provider_ids", ())),
    ))

