from datetime import date

import pytest

from src.postgres_analytics import AnalyticsRequest, compile_analytics_sql, request_from_semantic_plan


def test_compiles_parameterized_catalog_query_without_user_text_in_sql():
    request = AnalyticsRequest(
        metric="utilization", dimensions=("specialty", "month"),
        start_date=date(2025, 7, 1), end_date=date(2025, 7, 31),
        specialties=("Cardiology'; DROP TABLE provider; --",),
    )
    compiled = compile_analytics_sql(request)
    assert "SUM(pe.completed_visits)::numeric / NULLIF(SUM(a.available_slots), 0)" in compiled.sql
    assert "= ANY(:specialty_names)" in compiled.sql
    assert "DROP TABLE" not in compiled.sql
    assert compiled.params["specialty_names"] == ["Cardiology'; DROP TABLE provider; --"]
    assert compiled.params["start_date"] == date(2025, 7, 1)


def test_compiles_provider_metric_with_fixed_grouping_and_dates():
    compiled = compile_analytics_sql(AnalyticsRequest(
        metric="no_show_rate", dimensions=("provider",), providers=("SYN-001",),
    ))
    assert "p.provider_id AS provider_id" in compiled.sql
    assert "p.provider_name AS provider" in compiled.sql
    assert "GROUP BY p.provider_id, p.provider_name" in compiled.sql
    assert compiled.params["provider_ids"] == ["SYN-001"]


def test_compiles_revenue_opportunity_at_provider_grain_before_rollup():
    compiled = compile_analytics_sql(AnalyticsRequest(
        metric="revenue_opportunity", dimensions=("specialty",), target_utilization=.85,
    ))
    assert "WITH provider_totals AS" in compiled.sql
    assert "GROUP BY s.specialty_name, p.provider_id" in compiled.sql
    assert "GREATEST(0, :target_utilization * capacity - visits)" in compiled.sql


def test_translates_semantic_plan_to_catalog_request_not_sql():
    plan = {"dimensions": ["specialty"], "date_range": {
        "status": "ok", "effective_start": date(2025, 7, 1), "effective_end": date(2025, 7, 31),
    }}
    request = request_from_semantic_plan(plan, "utilization", target_utilization=.85, provider_ids=["SYN-001"])
    assert request.metric == "utilization"
    assert request.dimensions == ("specialty",)
    assert request.providers == ("SYN-001",)

    fallback = request_from_semantic_plan({"dimensions": [], "date_range": {"status": "no_date_requested"}},
                                          "revenue", target_utilization=.85,
                                          fallback_start=date(2025, 1, 1), fallback_end=date(2025, 12, 31))
    assert (fallback.start_date, fallback.end_date) == (date(2025, 1, 1), date(2025, 12, 31))


@pytest.mark.parametrize("kwargs", [
    {"metric": "revenue; DELETE FROM provider"},
    {"metric": "revenue", "dimensions": ("provider; DROP",)},
    {"metric": "revenue", "start_date": date(2025, 2, 1), "end_date": date(2025, 1, 1)},
])
def test_rejects_non_catalog_requests(kwargs):
    with pytest.raises(ValueError):
        compile_analytics_sql(AnalyticsRequest(**kwargs))
