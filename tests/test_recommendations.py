import json
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from src.recommendations import recommendation_engine, explain_recommendations


def rows():
    return pd.DataFrame([
        {"provider_id": "a", "provider": "Dr. A", "specialty": "X", "clinic": "One", "date": "2025-01-01",
         "visits": 50, "capacity": 100, "booked": 70, "revenue": 5000, "staffed_hours": 40},
        {"provider_id": "b", "provider": "Dr. B", "specialty": "X", "clinic": "One", "date": "2025-01-01",
         "visits": 80, "capacity": 100, "booked": 85, "revenue": 8000, "staffed_hours": 40},
    ]).assign(date=lambda x: pd.to_datetime(x.date))


def test_rules_and_demand_guardrail():
    output = recommendation_engine(rows(), .85)
    assert set(output.recommendation) >= {"Investigate no-show reduction", "Validate demand before addressing unused capacity"}
    utilization = output[output.recommendation_id == "utilization:a"].iloc[0]
    assert "Demand is not measured" in utilization.evidence
    assert "review_demand" in utilization.allowed_actions
    with_demand = recommendation_engine(rows(), .85, demand_exists=True)
    assert "Investigate unused capacity" in set(with_demand.recommendation)


def test_local_explanation_cannot_change_rule_actions():
    output = recommendation_engine(rows(), .85)
    explanation = explain_recommendations(output, use_ai=False)
    for row in output.itertuples():
        assert explanation[row.recommendation_id]["action_ids"] == list(row.allowed_actions)
        assert explanation[row.recommendation_id]["mode"] == "Local rule explanation"


def test_ai_rejects_unapproved_action(monkeypatch):
    from src.data import load_data
    source = load_data()
    output = recommendation_engine(source, .85).head(1)
    row = output.iloc[0]
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MODEL", "test")
    body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
        "explanations": [{"recommendation_id": row.recommendation_id, "summary": "Review the measured operational pattern.", "action_ids": ["share_practices"]}]})}]}]}
    response = Mock(); response.json.return_value = body
    monkeypatch.setattr(requests, "post", Mock(return_value=response))
    with pytest.raises(Exception):
        explain_recommendations(output, use_ai=True, source_df=source)


def test_workspace_renders_rule_explanations(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=40).run()
    next(button for button in app.button if button.label == "Show rule explanations").click().run()
    assert not app.exception
    assert any("Rule-approved next steps" in markdown.value for markdown in app.markdown)
