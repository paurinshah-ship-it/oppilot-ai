"""Allowlisted enterprise metric and dimension catalog."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDefinition:
    label: str
    source: str
    expression: str
    unit: str
    formula: str
    numerator: str | None = None
    denominator: str | None = None
    rate: bool = False


DIMENSIONS = ("organization", "region", "practice", "specialty", "provider", "month")
FORBIDDEN_TABLES = ("ground_truth_anomaly",)

METRICS: dict[str, MetricDefinition] = {
    "appointments": MetricDefinition("Appointments", "appointment", "COUNT(*)", "count", "count(appointment_event)"),
    "completed_visits": MetricDefinition("Completed visits", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')", "count", "completed appointment events"),
    "no_shows": MetricDefinition("No-shows", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status = 'no_show')", "count", "no_show appointment events"),
    "no_show_rate": MetricDefinition("No-show rate", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status = 'no_show')::numeric / NULLIF(COUNT(*) FILTER (WHERE e.appointment_status IN ('completed', 'no_show')), 0)", "rate", "no_show / (completed + no_show)", "COUNT(*) FILTER (WHERE e.appointment_status = 'no_show')", "COUNT(*) FILTER (WHERE e.appointment_status IN ('completed', 'no_show'))", True),
    "cancellations": MetricDefinition("Cancellations", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status IN ('cancelled', 'cancelled_patient', 'cancelled_provider', 'cancelled_practice'))", "count", "all cancellation statuses"),
    "rescheduled": MetricDefinition("Rescheduled", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status = 'rescheduled')", "count", "rescheduled appointment events"),
    "appointment_completion_rate": MetricDefinition("Appointment completion rate", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')::numeric / NULLIF(COUNT(*) FILTER (WHERE e.appointment_status IN ('completed', 'no_show')), 0)", "rate", "completed / (completed + no_show)", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')", "COUNT(*) FILTER (WHERE e.appointment_status IN ('completed', 'no_show'))", True),
    "modeled_revenue": MetricDefinition("Modeled revenue", "appointment", "SUM(e.modeled_revenue) FILTER (WHERE e.appointment_status = 'completed')", "currency", "sum appointment_event.modeled_revenue for completed events"),
    "average_booking_lead_days": MetricDefinition("Average booking lead days", "appointment", "AVG(EXTRACT(EPOCH FROM ((e.appointment_date::timestamp AT TIME ZONE 'UTC') - e.scheduled_at)) / 86400)", "days", "average appointment_date - scheduled_at; booking lead time only"),
    "median_booking_lead_days": MetricDefinition("Median booking lead days", "appointment", "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM ((e.appointment_date::timestamp AT TIME ZONE 'UTC') - e.scheduled_at)) / 86400)", "days", "median appointment_date - scheduled_at; booking lead time only"),
    "available_slots": MetricDefinition("Available slots", "capacity", "SUM(pc.available_slots)", "count", "sum(provider_capacity.available_slots)"),
    "blocked_slots": MetricDefinition("Blocked slots", "capacity", "SUM(pc.blocked_slots)", "count", "sum(provider_capacity.blocked_slots)"),
    "blocked_slot_rate": MetricDefinition("Blocked slot rate", "capacity", "SUM(pc.blocked_slots)::numeric / NULLIF(SUM(pc.available_slots + pc.blocked_slots), 0)", "rate", "blocked_slots / (available_slots + blocked_slots)", "SUM(pc.blocked_slots)", "SUM(pc.available_slots + pc.blocked_slots)", True),
    "clinical_hours": MetricDefinition("Clinical hours", "capacity", "SUM(pc.clinical_hours)", "hours", "sum(provider_capacity.clinical_hours)"),
    "scheduled_hours": MetricDefinition("Scheduled hours", "capacity", "SUM(pc.scheduled_hours)", "hours", "sum(provider_capacity.scheduled_hours)"),
    "pto_hours": MetricDefinition("PTO hours", "capacity", "SUM(pc.pto_hours)", "hours", "sum(provider_capacity.pto_hours)"),
    "admin_hours": MetricDefinition("Admin hours", "capacity", "SUM(pc.admin_hours)", "hours", "sum(provider_capacity.admin_hours)"),
    "visits_per_clinical_hour": MetricDefinition("Visits per clinical hour", "productivity", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')::numeric / NULLIF(SUM(pc.clinical_hours), 0)", "decimal", "completed_visits / clinical_hours", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')", "SUM(pc.clinical_hours)", True),
    "visits_per_provider": MetricDefinition("Visits per provider", "appointment", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')::numeric / NULLIF(COUNT(DISTINCT e.provider_id), 0)", "decimal", "completed_visits / distinct providers"),
    "capacity_utilization": MetricDefinition("Capacity utilization", "productivity", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')::numeric / NULLIF(SUM(pc.available_slots), 0)", "rate", "completed_visits / available_slots", "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')", "SUM(pc.available_slots)", True),
    "budgeted_fte": MetricDefinition("Budgeted FTE", "staffing", "SUM(sd.budgeted_fte)", "fte", "sum(staffing_daily.budgeted_fte)"),
    "scheduled_fte": MetricDefinition("Scheduled FTE", "staffing", "SUM(sd.scheduled_fte)", "fte", "sum(staffing_daily.scheduled_fte)"),
    "actual_fte": MetricDefinition("Actual FTE", "staffing", "SUM(sd.actual_fte)", "fte", "sum(staffing_daily.actual_fte)"),
    "staffing_gap_fte": MetricDefinition("Staffing gap FTE", "staffing", "SUM(sd.budgeted_fte) - SUM(sd.actual_fte)", "fte", "budgeted_fte - actual_fte"),
    "absence_hours": MetricDefinition("Absence hours", "staffing", "SUM(sd.absence_hours)", "hours", "sum(staffing_daily.absence_hours)"),
    "overtime_hours": MetricDefinition("Overtime hours", "staffing", "SUM(sd.overtime_hours)", "hours", "sum(staffing_daily.overtime_hours)"),
    "agency_hours": MetricDefinition("Agency hours", "staffing", "SUM(sd.agency_hours)", "hours", "sum(staffing_daily.agency_hours)"),
    "referrals_received": MetricDefinition("Referrals received", "referral", "COUNT(*)", "count", "count(referral)"),
    "referrals_scheduled": MetricDefinition("Referrals scheduled", "referral", "COUNT(*) FILTER (WHERE rf.status = 'scheduled')", "count", "scheduled referrals"),
    "referrals_completed": MetricDefinition("Referrals completed", "referral", "COUNT(*) FILTER (WHERE rf.status = 'completed')", "count", "completed referrals"),
    "referrals_lost": MetricDefinition("Referrals lost", "referral", "COUNT(*) FILTER (WHERE rf.status = 'lost')", "count", "lost referrals"),
    "referrals_expired": MetricDefinition("Referrals expired", "referral", "COUNT(*) FILTER (WHERE rf.status = 'expired')", "count", "expired referrals"),
    "referral_conversion_rate": MetricDefinition("Referral conversion rate", "referral", "COUNT(*) FILTER (WHERE rf.status = 'completed')::numeric / NULLIF(COUNT(*), 0)", "rate", "completed referrals / received referrals", "COUNT(*) FILTER (WHERE rf.status = 'completed')", "COUNT(*)", True),
    "modeled_charges": MetricDefinition("Modeled charges", "finance", "SUM(en.modeled_charge)", "currency", "sum(encounter.modeled_charge)"),
    "allowed_amount": MetricDefinition("Allowed amount", "finance", "SUM(en.allowed_amount)", "currency", "sum(encounter.allowed_amount)"),
    "paid_amount": MetricDefinition("Paid amount", "finance", "SUM(py.paid_amount)", "currency", "sum(payment.paid_amount); not profit"),
    "patient_amount": MetricDefinition("Patient amount", "finance", "SUM(py.patient_amount)", "currency", "sum(payment.patient_amount)"),
    "adjustment_amount": MetricDefinition("Adjustment amount", "finance", "SUM(py.adjustment_amount)", "currency", "sum(payment.adjustment_amount)"),
    "revenue_per_completed_visit": MetricDefinition("Revenue per completed visit", "appointment", "SUM(e.modeled_revenue) FILTER (WHERE e.appointment_status = 'completed') / NULLIF(COUNT(*) FILTER (WHERE e.appointment_status = 'completed'), 0)", "currency", "modeled_revenue / completed_visits"),
    "allowed_amount_per_encounter": MetricDefinition("Allowed amount per encounter", "finance", "SUM(en.allowed_amount) / NULLIF(COUNT(*), 0)", "currency", "allowed_amount / encounters"),
    "paid_amount_per_encounter": MetricDefinition("Paid amount per encounter", "finance", "SUM(py.paid_amount) / NULLIF(COUNT(*), 0)", "currency", "paid_amount / encounters; not profit"),
}


def metric_catalog() -> list[dict[str, str]]:
    return [{"metric": key, "label": m.label, "unit": m.unit, "formula": m.formula}
            for key, m in sorted(METRICS.items())]
