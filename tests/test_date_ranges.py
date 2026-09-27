from datetime import date
from pathlib import Path
import pytest
from src.date_ranges import parse_date_range
from src.conversation import respond
from src.data import load_data

TODAY = date(2026, 9, 26)

@pytest.mark.parametrize('phrase,start,end', [
    ('last year', '2025-01-01', '2025-12-31'),
    ('this year', '2026-01-01', '2026-09-26'),
    ('last month', '2026-08-01', '2026-08-31'),
    ('this month', '2026-09-01', '2026-09-26'),
    ('Q2', '2026-04-01', '2026-06-30'),
    ('Q2 2025', '2025-04-01', '2025-06-30'),
    ('July', '2026-07-01', '2026-07-31'),
    ('in August', '2026-08-01', '2026-08-31'),
    ('July 2026', '2026-07-01', '2026-07-31'),
    ('July 1 to August 15, 2026', '2026-07-01', '2026-08-15'),
    ('from 2026-07-01 to 2026-08-15', '2026-07-01', '2026-08-15'),
    ('available period', '2021-01-01', '2026-12-31'),
])
def test_calendar_ranges(phrase, start, end):
    result = parse_date_range('Compare visits ' + phrase, TODAY, date(2021,1,1), date(2026,12,31))
    assert result['status'] == 'ok'
    assert result['requested_start'] == result['effective_start'] == date.fromisoformat(start)
    assert result['requested_end'] == result['effective_end'] == date.fromisoformat(end)


def test_coverage_and_no_date():
    bounds = date(2026,6,1), date(2026,8,29)
    assert parse_date_range('Summary', TODAY, *bounds)['status'] == 'no_date_requested'
    assert parse_date_range('last year', TODAY, *bounds)['status'] == 'unavailable'
    partial = parse_date_range('Q3', TODAY, *bounds)
    assert partial['status'] == 'partially_available'
    assert partial['effective_end'] == bounds[1]
    assert partial['requested_end'] == date(2026,9,30)
    assert parse_date_range('last month', date(2026,8,10), *bounds)['status'] == 'ok'
    leap = parse_date_range('last month', date(2024,3,1), date(2024,1,1), date(2024,12,31))
    assert leap['requested_end'] == date(2024,2,29)

@pytest.mark.parametrize('phrase', ['February 30 to March 1, 2026', 'Q5', 'July 2025 and August 2026', 'from 2026-08-15 to 2026-07-01'])
def test_invalid_ranges(phrase):
    assert parse_date_range(phrase, TODAY, date(2021,1,1), TODAY)['status'] == 'invalid'


def test_raw_rows_override_dashboard_dates_without_mutation():
    raw = load_data()
    dashboard = raw[raw.date.dt.year == 2024].copy()
    original = dashboard.copy(deep=True)
    reply = respond('Which provider saw the most patients last year?', dashboard, raw_df=raw, as_of=TODAY)
    totals = raw[raw.date.dt.year == 2025].groupby('provider').visits.sum()
    assert reply['status'] == 'answered'
    assert totals.idxmax() in reply['text'] and f'{totals.max():,}' in reply['text']
    assert 'Jan 1, 2025–Dec 31, 2025' in reply['grounding']
    assert dashboard.equals(original)
    undated = respond('Most patients?', dashboard, raw_df=raw, as_of=TODAY)
    assert '2024' in undated['grounding'] and '2025' not in undated['grounding']
    all_period = respond('Most patients during the available period?', dashboard, raw_df=raw, as_of=TODAY)
    assert '2021' in all_period['grounding'] and '2025' in all_period['grounding']


def test_unavailable_and_partial_do_not_aggregate(monkeypatch):
    raw = load_data()
    def fail(*args, **kwargs):
        raise AssertionError('Must not calculate unavailable or partial periods')
    monkeypatch.setattr('src.conversation.benchmark', fail)
    reply = respond('Which provider saw the most patients last year?', raw, as_of=date(2030,1,1))
    assert reply['status'] == 'unavailable'
    assert '2029' in reply['text'] and len(reply['suggested_questions']) == 3
    partial = respond('Compare utilization Q1 2021', raw[(raw.date.dt.month == 2) & (raw.date.dt.year == 2021)], as_of=TODAY)
    assert partial['status'] == 'partially_available'

@pytest.mark.parametrize('question', [
    'Who had the highest no-show rate last month?',
    'Compare provider utilization in Q2.',
    'What was revenue opportunity in July?',
    'Compare visits from July 1 to August 15, 2025.',
])
def test_date_intents(question):
    assert respond(question, load_data(), as_of=date(2025,9,26))['status'] == 'answered'


def test_ui_query_dates_preserve_controls():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    selected = (date(2024,1,1), date(2024,12,31))
    app.date_input[0].set_value(selected).run()
    before = [m.value for m in app.metric]
    app.chat_input[0].set_value('Compare visits in July 2025').run()
    assert not app.exception
    assert app.session_state.chat_history[-1]['status'] == 'answered'
    assert 'Jul 1, 2025–Jul 31, 2025' in app.session_state.chat_history[-1]['grounding']
    assert tuple(app.date_input[0].value) == selected
    assert [m.value for m in app.metric] == before


def test_voice_dates_preserve_provider_selection():
    from src.voice import process_turn
    raw = load_data()
    provider = raw[raw.provider == 'Dr. Maya Patel']
    dashboard = provider[provider.date.dt.year == 2024]
    _, reply = process_turn({'audio': 'mock'}, dashboard, .85, [],
                            transcriber=lambda _: 'Compare visits July 2025', raw_df=provider,
                            data_bounds=(raw.date.min().date(), raw.date.max().date()))
    expected = provider[(provider.date.dt.year == 2025) & (provider.date.dt.month == 7)].visits.sum()
    assert reply['status'] == 'answered'
    assert f'{expected:,} completed visits' in reply['text']
    assert 'Dr. Ethan Chen' not in reply['text']
