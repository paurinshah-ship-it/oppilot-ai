"""Deterministic operational recommendations with an optional language layer.

Python decides whether a recommendation exists, its evidence, its priority and
the only permitted next steps.  An optional model may summarize that fixed
output, but cannot create recommendations or choose actions outside each rule.
"""
import json
import os

import pandas as pd
import requests

from copilot_prompt import ACTIONS
from src.analytics import benchmark
from ai_copilot import CopilotError, build_context


RULES = {
    "no_show_above_specialty": {
        "recommendation": "Investigate no-show reduction",
        "allowed_actions": ("review_no_shows", "monitor"),
    },
    "utilization_below_target": {
        "recommendation": "Validate demand before addressing unused capacity",
        "allowed_actions": ("review_demand", "review_staffing", "monitor"),
    },
    "utilization_below_target_with_demand": {
        "recommendation": "Investigate unused capacity",
        "allowed_actions": ("review_staffing", "monitor"),
    },
    "modeled_revenue_opportunity": {
        "recommendation": "Validate modeled revenue opportunity",
        "allowed_actions": ("validate_revenue", "review_demand", "monitor"),
    },
}


def recommendation_engine(df: pd.DataFrame, target: float = .85, demand_exists=None) -> pd.DataFrame:
    """Evaluate fixed operational rules from the selected provider-day rows.

    Rule 1: provider no-show rate > weighted specialty no-show benchmark and
    provider has bookings -> investigate no-show reduction.
    Rule 2: utilization < target.  When demand_exists is True, recommend
    unused-capacity investigation; when unknown (the default dataset has no
    demand measure), recommend validating demand before operational change.
    Rule 3: a positive modeled opportunity with a known observed revenue rate
    -> validate the scenario before budgeting it.

    Recommendations are operational prompts, not causal findings, clinical
    advice, patient-access decisions, or employment decisions.  A row may
    trigger several independent recommendations; they are not additive.
    """
    columns = ["recommendation_id", "provider", "specialty", "recommendation",
               "evidence", "modeled_opportunity", "allowed_actions", "priority"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    providers = benchmark(df, target).copy()
    specialty = providers.groupby("specialty")[["no_shows", "booked"]].sum()
    providers["specialty_no_show_rate"] = providers.specialty.map(
        specialty.no_shows.div(specialty.booked.where(specialty.booked.ne(0))))
    rows = []
    for row in providers.itertuples():
        base = {"provider": row.provider, "specialty": row.specialty,
                "modeled_opportunity": float(row.opportunity)}
        if row.booked > 0 and pd.notna(row.specialty_no_show_rate) and row.no_show_rate > row.specialty_no_show_rate:
            rule = RULES["no_show_above_specialty"]
            rows.append({**base, "recommendation_id": f"no-show:{row.provider_id}",
                         "recommendation": rule["recommendation"],
                         "evidence": (f"No-show rate {row.no_show_rate:.1%} exceeds the selected "
                                      f"{row.specialty} benchmark of {row.specialty_no_show_rate:.1%} "
                                      f"({row.booked:,.0f} booked appointments)."),
                         "allowed_actions": rule["allowed_actions"], "priority": 2})
        if row.utilization < target:
            rule_name = "utilization_below_target_with_demand" if demand_exists is True else "utilization_below_target"
            rule = RULES[rule_name]
            demand_note = "Demand is marked available." if demand_exists is True else "Demand is not measured in this dataset."
            rows.append({**base, "recommendation_id": f"utilization:{row.provider_id}",
                         "recommendation": rule["recommendation"],
                         "evidence": (f"Utilization is {row.utilization:.1%} versus the selected {target:.1%} target; "
                                      f"unused capacity is {row.unused_capacity:,.0f} slots. {demand_note}"),
                         "allowed_actions": rule["allowed_actions"], "priority": 3})
        if row.revenue_rate_known and row.opportunity > 0:
            rule = RULES["modeled_revenue_opportunity"]
            rows.append({**base, "recommendation_id": f"revenue:{row.provider_id}",
                         "recommendation": rule["recommendation"],
                         "evidence": (f"Modeled gross opportunity is ${row.opportunity:,.0f}, calculated from the selected "
                                      f"utilization target and observed revenue per visit."),
                         "allowed_actions": rule["allowed_actions"], "priority": 1})
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["priority", "modeled_opportunity", "provider"], ascending=[False, False, True], kind="stable")


def _local_explanations(recommendations: pd.DataFrame) -> dict:
    """Safe no-credential explanation; rule evidence and actions are unchanged."""
    return {row.recommendation_id: {
        "summary": "This is a measured operational pattern for review; it does not establish cause or a required action.",
        "action_ids": list(row.allowed_actions), "mode": "Local rule explanation",
    } for row in recommendations.itertuples()}


def explain_recommendations(recommendations: pd.DataFrame, use_ai: bool = False,
                            source_df: pd.DataFrame | None = None, target: float = .85) -> dict:
    """Use an LLM only to summarize deterministic evidence in bounded language.

    The model receives no raw records or user text. It returns one explanation
    per code-generated ID and may select only the action IDs already permitted
    by that rule. Numeric evidence and actions are always rendered by Python.
    """
    if recommendations.empty or not use_ai:
        return _local_explanations(recommendations)
    if source_df is None:
        raise CopilotError("AI recommendation explanations require verified bundled synthetic data.")
    # Same fail-closed provenance boundary used by the executive brief.  No
    # user uploads, raw rows, user text, clinic names, or dates cross the API.
    build_context(source_df, target)
    key, model = os.getenv("OPENAI_API_KEY", "").strip(), os.getenv("OPENAI_MODEL", "").strip()
    if not key or not model:
        return _local_explanations(recommendations)
    selected = recommendations.head(10)
    ids = selected.recommendation_id.tolist()
    payload = [{"recommendation_id": row.recommendation_id,
                "recommendation": row.recommendation,
                "evidence": row.evidence,
                "allowed_action_ids": list(row.allowed_actions)} for row in selected.itertuples()]
    schema = {"type": "object", "properties": {"explanations": {"type": "array", "minItems": len(ids), "maxItems": len(ids), "items": {
        "type": "object", "properties": {
            "recommendation_id": {"type": "string", "enum": ids},
            "summary": {"type": "string", "minLength": 1, "maxLength": 280},
            "action_ids": {"type": "array", "minItems": 1, "maxItems": 3,
                           "items": {"type": "string", "enum": list(ACTIONS)}},
        }, "required": ["recommendation_id", "summary", "action_ids"], "additionalProperties": False}}},
        "required": ["explanations"], "additionalProperties": False}
    instructions = ("Summarize only each supplied, code-generated recommendation. Do not add recommendations, "
                    "numbers, provider claims, causes, diagnoses, clinical advice, employment advice, or new next steps. "
                    "Use cautious operational language. Each action_ids list must be a subset of that row's allowed_action_ids.")
    try:
        response = requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "instructions": instructions,
                  "input": json.dumps({"recommendations": payload}), "store": False, "max_output_tokens": 900,
                  "text": {"format": {"type": "json_schema", "name": "recommendation_explanations", "strict": True, "schema": schema}}},
            timeout=(10, 45), allow_redirects=False)
        response.raise_for_status()
        content = [part for item in response.json().get("output", []) if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text"]
        output = json.loads("".join(part["text"] for part in content))
        entries = output["explanations"]
        if set(item.get("recommendation_id") for item in entries) != set(ids):
            raise ValueError("Missing recommendation explanation")
        allowed = {row.recommendation_id: set(row.allowed_actions) for row in selected.itertuples()}
        result = {}
        for item in entries:
            text = item["summary"].strip()
            prohibited = ("$", "%", "should", "must", "recommend", "cause", "because",
                          "diagnos", "treat", "fire", "terminat")
            if any(token in text.lower() for token in prohibited) or any(char.isdigit() for char in text):
                raise ValueError("Model added numeric evidence")
            actions = item["action_ids"]
            if not actions or not set(actions).issubset(allowed[item["recommendation_id"]]):
                raise ValueError("Model selected an unapproved action")
            result[item["recommendation_id"]] = {"summary": text, "action_ids": actions, "mode": "AI language summary"}
        return result
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise CopilotError("Recommendation explanations could not be generated. Deterministic recommendations remain available.") from None
