"""Safe PostgreSQL queries for large synthetic appointment-event datasets.

This module deliberately aggregates in PostgreSQL and returns only grouped
results or bounded pages. It never loads the event fact table into Pandas.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any


EVENT_DIMENSIONS = {
    "provider": ("p.provider_id", "p.provider_name"),
    "specialty": ("s.specialty_name",),
    "clinic": ("p.clinic_name",),
    "month": ("DATE_TRUNC('month', e.appointment_date)::date",),
}
NO_SHOW_DENOMINATOR_STATUSES = ("completed", "no_show")
NO_SHOW_DENOMINATOR_SQL = "e.appointment_status IN ('completed', 'no_show')"
EVENT_METRICS = {
    "appointments": "COUNT(*)",
    "completed_visits": "COUNT(*) FILTER (WHERE e.appointment_status = 'completed')",
    "no_shows": "COUNT(*) FILTER (WHERE e.appointment_status = 'no_show')",
    "no_show_rate": f"COUNT(*) FILTER (WHERE e.appointment_status = 'no_show')::numeric / NULLIF(COUNT(*) FILTER (WHERE {NO_SHOW_DENOMINATOR_SQL}), 0)",
    "revenue": "SUM(e.modeled_revenue) FILTER (WHERE e.appointment_status = 'completed')",
}
EVENT_FROM = """
FROM appointment_event e
JOIN provider p ON p.provider_id = e.provider_id
JOIN specialty s ON s.specialty_id = p.specialty_id
"""


@dataclass(frozen=True)
class EventAggregateRequest:
    metric: str
    dimensions: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    provider_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventPageRequest:
    provider_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    after_appointment_id: int | None = None
    page_size: int = 100


@dataclass(frozen=True)
class CompiledScaleQuery:
    sql: str
    params: dict[str, Any]


def _aliases(dimensions):
    aliases = {
        "p.provider_id": "provider_id", "p.provider_name": "provider",
        "s.specialty_name": "specialty", "p.clinic_name": "clinic",
        "DATE_TRUNC('month', e.appointment_date)::date": "month",
    }
    return [(column, aliases[column]) for dimension in dimensions for column in EVENT_DIMENSIONS[dimension]]


def compile_event_aggregate(request: EventAggregateRequest) -> CompiledScaleQuery:
    """Compile an allowlisted grouped event query with bound filter values."""
    if request.metric not in EVENT_METRICS:
        raise ValueError("Choose a catalog event metric.")
    if len(set(request.dimensions)) != len(request.dimensions) or any(key not in EVENT_DIMENSIONS for key in request.dimensions):
        raise ValueError("Choose unique catalog event dimensions.")
    if request.start_date and request.end_date and request.start_date > request.end_date:
        raise ValueError("Start date cannot be after end date.")
    dimensions = tuple(column for key in request.dimensions for column in EVENT_DIMENSIONS[key])
    select = [f"{column} AS {alias}" for column, alias in _aliases(request.dimensions)]
    select.append(f"{EVENT_METRICS[request.metric]} AS {request.metric}")
    where, params = [], {}
    if request.start_date:
        where.append("e.appointment_date >= :start_date")
        params["start_date"] = request.start_date
    if request.end_date:
        where.append("e.appointment_date <= :end_date")
        params["end_date"] = request.end_date
    if request.provider_ids:
        where.append("e.provider_id = ANY(:provider_ids)")
        params["provider_ids"] = list(request.provider_ids)
    sql = "SELECT " + ", ".join(select) + "\n" + EVENT_FROM
    if where:
        sql += "WHERE " + " AND ".join(where) + "\n"
    if dimensions:
        sql += "GROUP BY " + ", ".join(dimensions) + "\nORDER BY " + ", ".join(dimensions)
    return CompiledScaleQuery(sql, params)


def compile_event_page(request: EventPageRequest) -> CompiledScaleQuery:
    """Compile keyset pagination; large offsets never force a table scan."""
    if not 1 <= request.page_size <= 500:
        raise ValueError("Page size must be between 1 and 500.")
    if request.after_appointment_id is not None and request.after_appointment_id < 0:
        raise ValueError("Cursor must be nonnegative.")
    where, params = [], {"page_size": request.page_size}
    for parameter, column, value in (("provider_id", "e.provider_id", request.provider_id),
                                     ("start_date", "e.appointment_date >=", request.start_date),
                                     ("end_date", "e.appointment_date <=", request.end_date)):
        if value is not None:
            where.append(f"{column} :{parameter}" if " >=" in column or " <=" in column else f"{column} = :{parameter}")
            params[parameter] = value
    if request.after_appointment_id is not None:
        where.append("e.appointment_id > :after_appointment_id")
        params["after_appointment_id"] = request.after_appointment_id
    sql = """SELECT e.appointment_id, e.appointment_date, e.provider_id, p.provider_name,
       e.appointment_status, e.modeled_revenue
""" + EVENT_FROM
    if where:
        sql += "WHERE " + " AND ".join(where) + "\n"
    sql += "ORDER BY e.appointment_id ASC LIMIT :page_size"
    return CompiledScaleQuery(sql, params)


class QueryCache:
    """Bounded in-process TTL cache for repeat aggregate requests."""

    def __init__(self, max_entries: int = 128, ttl_seconds: int = 300):
        self.max_entries, self.ttl = max_entries, timedelta(seconds=ttl_seconds)
        self._entries: OrderedDict[str, tuple[datetime, Any]] = OrderedDict()

    def _key(self, query: CompiledScaleQuery) -> str:
        payload = json.dumps({"sql": query.sql, "params": query.params}, default=str, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, query: CompiledScaleQuery):
        key = self._key(query)
        entry = self._entries.get(key)
        if not entry or datetime.now(timezone.utc) - entry[0] > self.ttl:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def put(self, query: CompiledScaleQuery, result: Any) -> None:
        key = self._key(query)
        self._entries[key] = (datetime.now(timezone.utc), result)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
