"""Grounded executive brief with a fail-closed synthetic-only API boundary."""
import hashlib
from functools import lru_cache
import json
import os

import pandas as pd
import requests

from copilot_prompt import ACTIONS, GUARDRAIL_NOTICE, RESPONSE_SCHEMA, SYSTEM_PROMPT
from src.analytics import benchmark, calculate_kpis, detect_opportunities
from src.data import generate_data, validate_data


class CopilotError(ValueError):
    """Safe message suitable for the UI; never includes credentials or API bodies."""


@lru_cache(maxsize=1)
def _canonical_data():
    """Private in-memory reference avoids regenerating five years on every rerun."""
    return validate_data(generate_data())


def build_context(df, target):
    """Only accept exact subsets of the bundled synthetic generator's default data.

    Reject added fields and changed values BEFORE any API call. Recompute metrics
    locally and send only aggregate allowlisted metrics and generated aliases.
    No raw rows, user prompts, dates, clinic names, or patient data are transmitted.
    This is deliberately a demo-only provenance gate, not a PHI detector.
    """
    canonical = _canonical_data()
    if set(df.columns) != set(canonical.columns):
        raise CopilotError("AI briefs accept only the bundled synthetic dataset schema.")
    try:
        selected = validate_data(df)
        keys = ["date", "provider_id"]
        expected = canonical.merge(selected[keys], on=keys, how="inner")
        pd.testing.assert_frame_equal(
            selected[canonical.columns].reset_index(drop=True),
            expected[canonical.columns].reset_index(drop=True),
            check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-12)
    except (ValueError, AssertionError, TypeError):
        raise CopilotError("AI briefs are restricted to unchanged bundled synthetic records.") from None
    providers = benchmark(selected, target).sort_values(["utilization", "provider_id"], ascending=[False, True])
    kpis = calculate_kpis(selected)
    strongest = providers[providers.utilization == providers.utilization.max()]
    weakest = providers[providers.utilization == providers.utilization.min()]
    describe = lambda rows: [
        {"provider": row.provider, "utilization": round(row.utilization, 6),
         "visits_per_hour": round(row.visits_per_hour, 6)}
        for row in rows.itertuples()]
    detected = detect_opportunities(providers, target)
    context = {
        "data_type": "verified synthetic aggregates",
        "kpis": kpis, "target": float(target),
        "ranking_basis": "completed visits divided by staffed capacity; ties retained; not clinical quality",
        "strongest": describe(strongest), "weakest": describe(weakest),
        "opportunity": float(providers.opportunity.sum()),
        "unknown_revenue_rates": int((~providers.revenue_rate_known).sum()),
        "unbooked_slots": int(providers.unbooked_slots.sum()),
        "no_shows": int(providers.no_shows.sum()),
        "flagged_providers": int(len(detected)),
        "below_target": int((providers.utilization < target).sum()),
        "provider_count": int(len(providers)),
        "top_opportunities": [
            {"provider": row.provider, "opportunity": float(row.opportunity), "signals": row.signals}
            for row in detected.head(3).itertuples()],
    }
    return context


def context_key(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, allow_nan=False).encode()).hexdigest()


def configuration_ready():
    return bool(os.getenv("OPENAI_API_KEY", "").strip() and os.getenv("OPENAI_MODEL", "").strip())


def _request_actions(context):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()
    if not key or not model:
        raise CopilotError("Set OPENAI_API_KEY and OPENAI_MODEL in the server environment, then restart Streamlit.")
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "instructions": SYSTEM_PROMPT,
                  "input": json.dumps({"metrics": context, "action_catalog": ACTIONS}, allow_nan=False),
                  "store": False, "max_output_tokens": 800,
                  "text": {"format": {"type": "json_schema", "name": "executive_actions",
                                      "strict": True, "schema": RESPONSE_SCHEMA}}},
            timeout=(10, 45), allow_redirects=False)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "completed":
            raise ValueError("Incomplete response")
        content = [part for item in body.get("output", []) if item.get("type") == "message"
                   for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in content):
            raise ValueError("Refused")
        output = json.loads("".join(part["text"] for part in content if part.get("type") == "output_text"))
        ids = output.get("action_ids")
        if (set(output) != {"action_ids"} or not isinstance(ids, list) or
                not 2 <= len(ids) <= 4 or any(not isinstance(i, str) or i not in ACTIONS for i in ids) or
                len(set(ids)) != len(ids)):
            raise ValueError("Invalid output")
        return ids
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        raise CopilotError("The AI brief could not be generated. Check server configuration or retry; no unverified AI output was displayed.") from None


def generate_brief(df, target, use_ai=True):
    """Facts always come from calculations; AI can only prioritize approved actions."""
    context = build_context(df, target)  # gate applies even to preview
    actions = _request_actions(context) if use_ai else ["review_demand", "review_staffing", "validate_revenue", "monitor"]
    def ranking(rows):
        return "; ".join(f"{r['provider']}: {r['utilization']:.1%} utilization, "
                         f"{r['visits_per_hour']:.2f} visits/staffed hour" for r in rows)
    sections = {
        "Strongest performance": ranking(context["strongest"]),
        "Weakest performance": ranking(context["weakest"]),
        "Major operational opportunities": (
            f"{context['below_target']} of {context['provider_count']} providers are below the "
            f"{context['target']:.0%} target. Unused capacity includes {context['unbooked_slots']:,} "
            f"unbooked slots and {context['no_shows']:,} no-shows. "
            f"{context['flagged_providers']} providers trigger operational review rules."),
        "Revenue opportunity": (
            f"${context['opportunity']:,.0f} modeled gross revenue opportunity over the selected period. "
            f"{context['unknown_revenue_rates']} providers have no observed revenue rate and contribute "
            "zero to this estimate; their monetary opportunity is unknown."),
        "Recommended management actions": "\n".join(f"• {ACTIONS[action]}" for action in actions),
    }
    return {"mode": "AI-prioritized actions with calculated findings" if use_ai else "Local preview — no AI call",
            "sections": sections, "guardrails": GUARDRAIL_NOTICE,
            "context_key": context_key(context)}
