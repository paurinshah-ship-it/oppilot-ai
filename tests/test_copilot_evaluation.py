from datetime import date

from src.copilot_evaluation import build_cases, evaluate_case, evaluate_suite
from src.data import load_data


def test_evaluation_suite_has_one_thousand_cases_with_required_categories():
    cases = build_cases(load_data())
    assert len(cases) == 1000
    assert {"semantic", "unavailable_date", "provider_comparison", "safety", "semantic_rank", "unmeasured_metric"} <= {case.category for case in cases}
    semantic = next(case for case in cases if case.category == "semantic")
    assert semantic.expected_metric and semantic.expected_start and semantic.expected_end


def test_semantic_evaluation_checks_plan_dates_filters_calculation_and_answer():
    df = load_data()
    case = next(case for case in build_cases(df) if case.category == "semantic" and case.expected_provider)
    result = evaluate_case(case, df, today=date(2025, 12, 31))
    assert result["evaluation_result"] == "PASS"
    assert all(result[key] for key in ("metric_selected", "date_range_selected", "filters_selected",
                                       "calculation_verified", "answer_verified"))


def test_evaluation_can_run_a_small_representative_suite():
    results = evaluate_suite(load_data(), count=10)
    assert len(results) == 10
    assert all(row["evaluation_result"] == "PASS" for row in results)
