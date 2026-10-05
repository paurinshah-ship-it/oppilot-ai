"""Phase 1G deterministic enterprise tool-layer tests."""
from datetime import date

import pytest

from src.tools.enterprise_comparisons import PeriodComparisonRequest, change_summary, compare_periods
from src.tools.enterprise_metrics import DIMENSIONS, METRICS, metric_catalog
from src.tools.enterprise_queries import EnterpriseMetricRequest, compile_enterprise_metric, structured_result
from src.tools.enterprise_rankings import RankingRequest, rank_entities
from src.tools.enterprise_trends import get_metric_trend


REQUIRED_METRICS = {
    'appointments', 'completed_visits', 'no_shows', 'no_show_rate',
    'cancellations', 'rescheduled', 'appointment_completion_rate',
    'available_slots', 'blocked_slots', 'blocked_slot_rate', 'clinical_hours',
    'scheduled_hours', 'pto_hours', 'admin_hours', 'budgeted_fte',
    'scheduled_fte', 'actual_fte', 'staffing_gap_fte', 'absence_hours',
    'overtime_hours', 'agency_hours', 'referrals_received',
    'referrals_scheduled', 'referrals_completed', 'referrals_lost',
    'referrals_expired', 'referral_conversion_rate', 'modeled_revenue',
    'modeled_charges', 'allowed_amount', 'paid_amount', 'patient_amount',
    'adjustment_amount', 'revenue_per_completed_visit',
    'allowed_amount_per_encounter', 'paid_amount_per_encounter',
    'visits_per_clinical_hour', 'visits_per_provider',
    'capacity_utilization', 'average_booking_lead_days',
    'median_booking_lead_days',
}


def test_metric_catalog_and_dimensions_cover_phase_1g_requirements():
    assert REQUIRED_METRICS <= set(METRICS)
    assert set(DIMENSIONS) == {'organization', 'region', 'practice', 'specialty', 'provider', 'month'}
    formulas = {row['metric']: row['formula'] for row in metric_catalog()}
    assert formulas['no_show_rate'] == 'no_show / (completed + no_show)'
    assert formulas['staffing_gap_fte'] == 'budgeted_fte - actual_fte'
    assert formulas['referral_conversion_rate'] == 'completed referrals / received referrals'
    assert 'not profit' in METRICS['paid_amount'].formula


def test_query_compiler_uses_allowlists_bound_filters_and_weighted_rate_sql():
    compiled = compile_enterprise_metric(EnterpriseMetricRequest(
        metric='no_show_rate', dimensions=('region', 'practice'), start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 31), region_ids=(10001,), practice_ids=(10003,)))
    assert "e.appointment_status IN ('completed', 'no_show')" in compiled.sql
    assert "AVG(" not in compiled.sql
    assert "ANY(:region_ids)" in compiled.sql
    assert compiled.params['region_ids'] == [10001]
    assert compiled.params['practice_ids'] == [10003]
    assert ':start_date' in compiled.sql and ':end_date' in compiled.sql


def test_zero_denominator_and_financial_semantics_are_safe_sql():
    for metric in ('blocked_slot_rate', 'referral_conversion_rate',
                   'allowed_amount_per_encounter', 'paid_amount_per_encounter',
                   'revenue_per_completed_visit'):
        compiled = compile_enterprise_metric(EnterpriseMetricRequest(metric=metric))
        assert 'NULLIF' in compiled.sql
    assert 'profit' not in compile_enterprise_metric(EnterpriseMetricRequest(metric='paid_amount')).sql.lower()
    assert 'collections' not in compile_enterprise_metric(EnterpriseMetricRequest(metric='modeled_revenue')).sql.lower()


@pytest.mark.parametrize('metric_request', [
    EnterpriseMetricRequest(metric='DROP TABLE appointment_event'),
    EnterpriseMetricRequest(metric='no_show_rate', dimensions=('practice;DROP TABLE provider',)),
    EnterpriseMetricRequest(metric='staffing_gap_fte', dimensions=('provider',)),
    EnterpriseMetricRequest(metric='no_show_rate', start_date=date(2025, 2, 1), end_date=date(2025, 1, 1)),
])
def test_invalid_metric_dimension_sql_injection_and_dates_fail_closed(metric_request):
    with pytest.raises(ValueError):
        compile_enterprise_metric(metric_request)


def test_ground_truth_anomaly_is_not_accessible_to_agent_facing_tools():
    for metric in REQUIRED_METRICS:
        compiled = compile_enterprise_metric(EnterpriseMetricRequest(metric=metric, dimensions=()))
        assert 'ground_truth_anomaly' not in compiled.sql.lower()
    with pytest.raises(ValueError):
        compile_enterprise_metric(EnterpriseMetricRequest(metric='ground_truth_anomaly'))


def test_structured_result_includes_definition_period_scope_and_counts():
    compiled = compile_enterprise_metric(EnterpriseMetricRequest(
        metric='no_show_rate', dimensions=('practice',), start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)))
    result = structured_result(compiled, {'practice_id': 10001, 'practice': 'North Clinic',
                                          'value': .125, 'numerator': 5, 'denominator': 40,
                                          'entity_count': 1})
    assert result.metric == 'no_show_rate'
    assert result.formula == 'no_show / (completed + no_show)'
    assert result.period == {'start': '2025-01-01', 'end': '2025-01-31'}
    assert result.scope['practice_id'] == 10001
    assert result.numerator == 5 and result.denominator == 40


def test_comparison_uses_percentage_points_for_rates_and_percent_for_amounts():
    rate = compare_periods(PeriodComparisonRequest(metric='no_show_rate'))
    amount = compare_periods(PeriodComparisonRequest(metric='paid_amount'))
    assert rate['change_kind'] == 'percentage_point_change'
    assert amount['change_kind'] == 'percent_change'
    assert change_summary(.20, .15, 'no_show_rate')['percentage_point_change'] == pytest.approx(.05)
    assert change_summary(120, 100, 'paid_amount')['percent_change'] == pytest.approx(.20)


def test_monthly_trend_and_ranking_are_deterministic_and_bounded():
    trend = get_metric_trend('referral_conversion_rate', dimensions=('practice',))
    assert 'month' in trend.request.dimensions
    assert "DATE_TRUNC('month'" in trend.sql
    ranking = rank_entities(RankingRequest('staffing_gap_fte', ('practice',), limit=10))
    assert 'ORDER BY value DESC NULLS LAST' in ranking.sql
    assert ranking.params['limit'] == 10
    assert 'ground_truth_anomaly' not in ranking.sql.lower()


def test_booking_lead_metrics_use_scheduled_at_and_do_not_call_it_wait_time():
    median = compile_enterprise_metric(EnterpriseMetricRequest(metric='median_booking_lead_days'))
    assert 'scheduled_at' in median.sql
    assert 'PERCENTILE_CONT' in median.sql
    assert 'wait time' not in METRICS['median_booking_lead_days'].formula.lower()
