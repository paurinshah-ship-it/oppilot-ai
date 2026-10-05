from datetime import date

import pytest

from src.scalable_analytics import (EventAggregateRequest, EventPageRequest, QueryCache,
                                    compile_event_aggregate, compile_event_page)


def test_event_aggregate_is_grouped_and_parameterized():
    query = compile_event_aggregate(EventAggregateRequest(
        "no_show_rate", ("month", "specialty"), date(2025, 1, 1), date(2025, 12, 31), ("SYN-001",),
    ))
    assert "COUNT(*) FILTER" in query.sql
    assert "e.appointment_status IN ('completed', 'no_show')" in query.sql
    assert "e.appointment_status <> 'cancelled'" not in query.sql
    assert "GROUP BY DATE_TRUNC('month', e.appointment_date)::date, s.specialty_name" in query.sql
    assert "= ANY(:provider_ids)" in query.sql
    assert query.params["provider_ids"] == ["SYN-001"]


def test_event_pagination_uses_cursor_not_offset():
    query = compile_event_page(EventPageRequest(after_appointment_id=250_000, page_size=100))
    assert "e.appointment_id > :after_appointment_id" in query.sql
    assert "OFFSET" not in query.sql
    assert "LIMIT :page_size" in query.sql


@pytest.mark.parametrize("query_request", [
    EventAggregateRequest("DROP TABLE appointment_event"),
    EventPageRequest(page_size=501),
])
def test_scale_queries_reject_unsafe_or_unbounded_requests(query_request):
    compiler = compile_event_aggregate if isinstance(query_request, EventAggregateRequest) else compile_event_page
    with pytest.raises(ValueError):
        compiler(query_request)


def test_query_cache_returns_repeat_aggregate_result():
    query = compile_event_aggregate(EventAggregateRequest("appointments", ("clinic",)))
    cache = QueryCache(max_entries=1)
    cache.put(query, [{"clinic": "North Clinic", "appointments": 12}])
    assert cache.get(query) == [{"clinic": "North Clinic", "appointments": 12}]
