import json
from pathlib import Path
from unittest.mock import Mock
import pytest
import requests
from streamlit.testing.v1 import AppTest
from ai_copilot import CopilotError, build_context, generate_brief
from src.data import load_data


def test_preview_no_network(monkeypatch):
    post = Mock(side_effect=AssertionError('Unexpected network'))
    monkeypatch.setattr(requests, 'post', post)
    df = load_data()
    brief = generate_brief(df, .85, use_ai=False)
    assert len(brief['sections']) == 5
    assert f'{(df.capacity-df.booked).sum():,}' in brief['sections']['Major operational opportunities']
    post.assert_not_called()


@pytest.mark.parametrize('change', ['extra_phi', 'renamed', 'metric'])
def test_fail_closed(monkeypatch, change):
    df = load_data()
    if change == 'extra_phi':
        df['patient_name'] = 'TEST PHI sentinel'
    elif change == 'renamed':
        df.loc[0, 'provider'] = 'TEST PHI sentinel'
    else:
        df.loc[0, 'revenue'] += 100
    post = Mock()
    monkeypatch.setattr(requests, 'post', post)
    with pytest.raises(CopilotError):
        generate_brief(df, .85)
    post.assert_not_called()


@pytest.mark.parametrize('valid', [True, False])
def test_api_contract(monkeypatch, valid):
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-test-key')
    monkeypatch.setenv('OPENAI_MODEL', 'test-model')
    output = {'action_ids': ['validate_revenue', 'monitor'] if valid else ['invented', 'monitor']}
    response = Mock()
    response.json.return_value = {'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(output)}]}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, 'post', post)
    if valid:
        brief = generate_brief(load_data(), .85)
        assert 'AI-prioritized' in brief['mode']
        assert 'fake-test-key' not in json.dumps(brief)
    else:
        with pytest.raises(CopilotError):
            generate_brief(load_data(), .85)
    body = post.call_args.kwargs['json']
    assert body['store'] is False
    assert body['text']['format']['strict'] is True
    assert 'fake-test-key' not in body['input']
    assert all(label not in body['input'] for label in load_data().clinic.unique())
    assert 'date' not in json.loads(body['input'])['metrics']


def test_missing_key_timeout(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(CopilotError, match='server environment'):
        generate_brief(load_data(), .85)
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-secret')
    monkeypatch.setenv('OPENAI_MODEL', 'test')
    monkeypatch.setattr(requests, 'post', Mock(side_effect=requests.Timeout('fake-secret')))
    with pytest.raises(CopilotError) as err:
        generate_brief(load_data(), .85)
    assert 'fake-secret' not in str(err.value)


def test_ui_preview_staleness(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    next(b for b in app.button if b.label == 'Preview calculated brief').click().run()
    assert not app.exception
    assert any(s.value == 'Strongest performance' for s in app.subheader)
    assert not next(b for b in app.button if b.label == 'Generate AI Executive Brief').disabled
    assert app.session_state['executive_brief']['mode'] == 'Local preview — no AI call'
    next(w for w in app.slider if w.label == "Target utilization (%)").set_value(90).run()
    assert any('Filters or target changed' in item.value for item in app.info)
    assert not app.exception


def test_subset_ties():
    df = load_data()
    context = build_context(df[df.provider == 'Dr. Maya Patel'], .85)
    assert context['strongest'] == context['weakest']
    assert context['provider_count'] == 1

@pytest.mark.parametrize('body', [
    {'status': 'incomplete', 'output': []},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"action_ids":["monitor","monitor"]}'}]}]},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"action_ids":["monitor","review_demand"],"revenue":999}'}]}]},
])
def test_refusals_incomplete_and_extra_claims(monkeypatch, body):
    monkeypatch.setenv('OPENAI_API_KEY', 'fake')
    monkeypatch.setenv('OPENAI_MODEL', 'test')
    response = Mock()
    response.json.return_value = body
    monkeypatch.setattr(requests, 'post', Mock(return_value=response))
    with pytest.raises(CopilotError):
        generate_brief(load_data(), .85)
