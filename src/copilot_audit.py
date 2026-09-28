"""Local, session-scoped audit records for deterministic copilot turns.

The audit trail stores only aggregate provider-day provenance already available
to the dashboard. It is kept in Streamlit session state, is never sent to an
AI service, and uses row references/fingerprints rather than copying source
records into a second data store.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pandas as pd
import streamlit as st


def _json_safe(value):
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def _source_rows(source_df: pd.DataFrame, response: dict) -> dict:
    """Return compact, reproducible references to rows used by an answer."""
    records = response.get("grounding_details", [])
    masks = []
    for record in records:
        start, end = record.get("start"), record.get("end")
        if start and end:
            masks.append(source_df.date.dt.date.between(start, end))
    if masks:
        mask = masks[0].copy()
        for next_mask in masks[1:]:
            mask |= next_mask
        rows = source_df.loc[mask]
    else:
        rows = source_df.iloc[0:0]
    row_ids = [str(index) for index in rows.index]
    fingerprint_columns = [column for column in ("date", "provider_id", "visits", "capacity", "revenue") if column in rows]
    fingerprint = hashlib.sha256(rows[fingerprint_columns].to_csv(index=True).encode()).hexdigest()[:16] if fingerprint_columns else None
    return {
        "record_count": len(rows),
        "provider_count": int(rows.provider_id.nunique()) if "provider_id" in rows else 0,
        "row_reference": "dataframe index in the selected aggregate provider-day dataset",
        "row_ids": row_ids,
        "fingerprint": fingerprint,
    }


def calculation_path(response: dict) -> dict:
    """Expose the deterministic route without reverse-engineering prose."""
    parsed = response.get("date_range") or {}
    plan = response.get("query_plan")
    result = response.get("calculated_result")
    if plan:
        calculation = "Structured query plan executed by Python on provider-day rows before aggregation."
    elif result:
        calculation = "Allowlisted semantic metric calculation executed by Python on provider-day rows."
    elif response.get("grounding_details"):
        calculation = "Rule-based copilot route calculated from grounded provider-day aggregate metrics."
    else:
        calculation = "No metric calculation was performed; the request was refused or lacked available data."
    return {
        "date_interpretation": parsed,
        "calculation": calculation,
        "query_plan": plan,
        "calculated_result": result,
        "metric_breakdown": response.get("calculation_breakdown"),
        "grounding": response.get("grounding_details", []),
    }


def record_query(session_state, question: str, response: dict, source_df: pd.DataFrame,
                 filters: dict, surface: str) -> dict:
    """Append one local audit event and attach its id to the chat response."""
    audit = session_state.setdefault("copilot_audit", [])
    audit_id = len(audit) + 1
    status = response.get("status", "unknown")
    entry = {
        "audit_id": audit_id,
        "surface": surface,
        "question": question,
        "decision": "allowed" if status in ("answered", "limited") else "refused",
        "status": status,
        "filters": filters,
        "calculation_path": calculation_path(response),
        "source_rows": _source_rows(source_df, response),
        "response": response.get("text", ""),
    }
    entry = _json_safe(entry)
    audit.append(entry)
    response["audit_id"] = audit_id
    return entry


def render_calculation_path(entry: dict) -> None:
    """Render a readable per-answer provenance panel for the Streamlit UI."""
    with st.expander("Why did the copilot give this answer?"):
        st.caption(f"Audit event #{entry['audit_id']} · {entry['surface']} · {entry['decision']} ({entry['status']})")
        st.markdown(f"**Calculation performed:** {entry['calculation_path']['calculation']}")
        st.json({
            "filters": entry["filters"],
            "date_interpretation": entry["calculation_path"]["date_interpretation"],
            "query_plan": entry["calculation_path"]["query_plan"],
            "calculated_result": entry["calculation_path"]["calculated_result"],
            "metric_breakdown": entry["calculation_path"]["metric_breakdown"],
            "source_rows": entry["source_rows"],
        })


def render_audit_trail(session_state) -> None:
    """Render a compact session audit index and local JSON export."""
    audit = session_state.get("copilot_audit", [])
    with st.expander("Copilot audit trail", expanded=False):
        st.caption("Stored locally for this browser session. No queries, source rows, or responses are sent to an AI service.")
        if not audit:
            st.caption("No copilot queries in this session.")
            return
        index = pd.DataFrame([{
            "Audit #": item["audit_id"], "Surface": item["surface"], "Decision": item["decision"],
            "Status": item["status"], "Source rows": item["source_rows"]["record_count"], "Question": item["question"],
        } for item in reversed(audit)])
        st.dataframe(index, hide_index=True, width="stretch")
        st.download_button("Download local audit trail", json.dumps(audit, indent=2), "copilot_audit.json", "application/json")
