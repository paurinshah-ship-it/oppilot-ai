"""Access and appointment summary shortcuts."""
from __future__ import annotations

from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric


def get_appointment_summary(metric: str = "no_show_rate", **kwargs):
    return compile_enterprise_metric(EnterpriseMetricRequest(metric=metric, **kwargs))


def get_booking_lead_summary(metric: str = "median_booking_lead_days", **kwargs):
    if metric not in ("average_booking_lead_days", "median_booking_lead_days"):
        raise ValueError("Choose average_booking_lead_days or median_booking_lead_days.")
    return compile_enterprise_metric(EnterpriseMetricRequest(metric=metric, **kwargs))

