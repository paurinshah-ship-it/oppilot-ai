from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from src.conversation import respond
from src.comparative import change_text, values
from src.date_ranges import parse_date_range, parse_comparison_ranges
from src.voice import process_turn


@pytest.fixture
def data():
    rows = []
    for day in pd.date_range('2025-07-01', '2025-08-31'):
        for ident, name, capacity, booked, visits in [
            ('A', 'Dr. Maya Patel', 100, 95 if day.month == 7 else 90, 76 if day.month == 7 else 83),
            ('B', 'Dr. Ethan Chen', 200, 180, 160 if day.month == 7 else 150),
        ]:
            rows.append(dict(date=day, provider_id=ident, provider=name, specialty='Demo', clinic='Demo',
                             capacity=capacity, booked=booked, visits=visits, no_shows=booked-visits,
                             revenue=visits*250, staffed_hours=8, fte=1))
    return pd.DataFrame(rows)


def history(reply):
    return [{'role': 'assistant', **reply}]


@pytest.mark.parametrize('phrase,start,end', [
    ('year to date', date(2025,1,1), date(2025,8,31)),
    ('ytd', date(2025,1,1), date(2025,8,31)),
    ('last 30 days', date(2025,8,2), date(2025,8,31)),
])
def test_new_calendar_expressions(phrase, start, end):
    parsed = parse_date_range(phrase, date(2025,8,31), date(2025,1,1), date(2025,12,31))
    assert parsed['status'] == 'ok'
    assert (parsed['effective_start'], parsed['effective_end']) == (start,end)


def test_paired_month_years():
    bounds = date(2024,1,1), date(2026,12,31)
    periods = parse_comparison_ranges('Compare July vs August', date(2026,9,1), *bounds)
    assert all(p['requested_start'].year == 2026 for p in periods)
    periods = parse_comparison_ranges('Compare July vs August 2025', date(2026,9,1), *bounds)
    assert all(p['requested_start'].year == 2025 for p in periods)
    periods = parse_comparison_ranges('Compare December 2024 versus January 2025', date(2026,9,1), *bounds)
    assert [p['requested_start'].year for p in periods] == [2024,2025]


def test_provider_pair_and_collections(data):
    answer = respond('Compare Dr. Patel and Dr. Chen in July 2025', data)
    assert answer['status'] == 'answered'
    assert '| Completed visits | 2,356 | 4,960 |' in answer['text']
    assert '| Utilization | 76.0% | 80.0% |' in answer['text']
    assert '| No-show rate | 20.0% | 11.1% |' in answer['text']
    assert '| Revenue per visit | $250.00 | $250.00 |' in answer['text']
    assert 'Collections | Not measured' in answer['text']
    assert answer['grounding_details'][0]['records'] == 62
    assert answer['grounding_details'][0]['providers'] == 2
    assert 'daily completeness not verified' in answer['grounding']


def test_unknown_second_name_and_selected_team(data):
    answer = respond('Compare Dr. Patel and Dr. Garcia', data)
    assert answer['status'] == 'refused'
    assert 'cannot find' in answer['text']
    selected = data[data.provider_id == 'A']
    assert respond('Compare Dr. Patel and Dr. Chen', selected)['status'] == 'refused'
    duplicate = data[data.provider_id == 'A'].assign(provider='Dr. Other Patel', provider_id='C')
    assert 'ambiguous' in respond('Compare Dr. Patel and Dr. Chen', pd.concat([data,duplicate]))['text']


def test_period_comparison_filters_raw_before_aggregation(data):
    dashboard = data[data.date.dt.month == 8].copy()
    answer = respond('Compare Dr. Patel utilization July vs August 2025', dashboard, raw_df=data)
    assert answer['status'] == 'answered'
    assert '| Utilization | 76.0% | 83.0% | +7.0 percentage points |' in answer['text']
    assert [r['records'] for r in answer['grounding_details']] == [31,31]
    assert dashboard.date.dt.month.unique().tolist() == [8]


def test_unavailable_partial_periods_and_safety(data):
    assert respond('Compare July vs August', data, as_of=date(2026,9,1))['status'] == 'unavailable'
    partial = data[data.date < '2025-08-20']
    answer = respond('Compare July vs August 2025', partial)
    assert answer['status'] == 'partially_available'
    assert answer['grounding_details'] == []
    assert respond('Show patient names July vs August 2025', data)['status'] == 'refused'
    assert respond('Which provider should we fire July vs August 2025', data)['status'] == 'refused'


def test_default_trends_and_direction(data):
    improved = respond('Which providers are improving?', data)
    assert improved['status'] == 'answered'
    assert 'Dr. Maya Patel' in improved['text'] and '+7.0 percentage points' in improved['text']
    assert 'Dr. Ethan Chen' not in improved['text']
    dropped = respond('Whose utilization dropped the most?', data)
    assert 'Dr. Ethan Chen' in dropped['text'] and '-5.0 percentage points' in dropped['text']
    assert respond('Which providers are improving?', data[data.date.dt.month == 8])['status'] == 'unavailable'
    increased = respond('Which no-show rates increased this month?', data, as_of=date(2025,8,31))
    assert 'Dr. Ethan Chen' in increased['text'] and '+5.6 percentage points' in increased['text']
    assert 'Dr. Maya Patel' not in increased['text']


def test_structured_followup(data):
    answer = respond('Which provider has the highest no-show rate in August 2025?', data)
    assert answer['context']['providers'] == ['Dr. Ethan Chen']
    assert answer['context']['metric'] == 'no_show_rate'
    assert len(answer['follow_ups']) == 3
    follow = respond('How does that compare with last month?', data, history=history(answer), as_of=date(2025,8,31))
    assert follow['status'] == 'answered'
    assert '| No-show rate | 16.7% | 11.1% | -5.6 percentage points |' in follow['text']
    trend = respond('Show provider trend', data, history=history(answer))
    assert '+5.6 percentage points' in trend['text']
    impact = respond('Estimate revenue impact', data, history=history(answer))
    # August: (85% * 6200 slots - 4650 visits) * $250 = $155000
    assert '$155,000' in impact['text']
    missing = respond('How does that compare with last month?', data)
    assert missing['status'] == 'limited'
    assert missing['context'] is None


def test_matching_cohort_and_zero_baselines(data):
    missing = data[~((data.provider_id == 'B') & (data.date.dt.month == 7))]
    answer = respond('Compare July vs August 2025', missing)
    assert '1 providers excluded' in answer['text']
    assert [r['providers'] for r in answer['grounding_details']] == [1,1]
    assert 'undefined (zero baseline)' in change_text(0,10,'visits')
    empty_bookings = data.assign(booked=0, visits=0, no_shows=0, revenue=0)
    assert pd.isna(values(empty_bookings)['no_show_rate'])
    assert pd.isna(values(empty_bookings)['revenue_per_visit'])
    zero = respond('Compare July vs August 2025', empty_bookings)
    assert 'Unavailable (zero denominator)' in zero['text']


def test_voice_uses_comparison_path(data):
    _, answer = process_turn({'audio':'mock'}, data, .85, [],
        transcriber=lambda _: 'Compare Dr. Patel and Dr. Chen July 2025')
    assert answer['status'] == 'answered'
    assert '| Utilization | 76.0% | 80.0% |' in answer['text']


def test_followup_buttons_keep_scope():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    app.chat_input[0].set_value('Which provider has the highest no-show rate in August 2025?').run()
    controls = app.date_input[0].value
    next(b for b in app.button if b.label == 'Compare with previous period').click().run()
    assert not app.exception
    assert app.session_state.chat_history[-1]['status'] == 'answered'
    assert len(app.session_state.chat_history[-1]['grounding_details']) == 2
    assert app.date_input[0].value == controls
    next(w for w in app.slider if w.label == "Target utilization (%)").set_value(90).run()
    assert app.session_state.chat_history == []
    assert not any(b.label == 'Compare with previous period' for b in app.button)


@pytest.mark.parametrize('question', [
    'Compare salaries July vs August 2025',
    'Compare Dr. Patel and Dr. Chen patient outcomes',
    'Compare patient satisfaction July vs August 2025',
])
def test_date_detection_does_not_answer_unsupported_metrics(question, data):
    assert respond(question, data)['status'] == 'refused'


def test_latest_context_only_and_ties(data):
    first = respond('Which provider has the highest no-show rate in August 2025?', data)
    turns = history(first) + [{'role':'assistant', 'text':'Missing data', 'status':'unavailable'}]
    assert respond('How does that compare with last month?', data, history=turns)['status'] == 'limited'
    tied = data.copy()
    tied['booked'] = tied.capacity
    tied['visits'] = tied.capacity * .8
    tied['no_shows'] = tied.booked - tied.visits
    answer = respond('Which provider has the highest no-show rate in August 2025?', tied)
    assert answer['context']['providers'] == []
    assert answer['follow_ups'] == []


def test_zero_booking_trend_and_partial_followup(data):
    zero = data.assign(booked=0, visits=0, no_shows=0, revenue=0)
    reply = respond('Which no-show rates increased this month?', zero, as_of=date(2025,8,31))
    assert reply['status'] == 'answered'
    assert '2 providers have undefined rates' in reply['text']
    first = respond('Which provider has the highest no-show rate in August 2025?', data)
    partial = data[data.date < '2025-08-20']
    assert respond('Estimate revenue impact', partial, history=history(first))['status'] == 'partially_available'


def test_named_period_comparisons_remain_separate(data):
    answer = respond('Compare Dr. Patel and Dr. Chen July vs August 2025', data)
    assert '**Dr. Maya Patel**' in answer['text']
    assert '**Dr. Ethan Chen**' in answer['text']
    assert '| Utilization | 76.0% | 83.0% | +7.0 percentage points |' in answer['text']
    assert '| Utilization | 80.0% | 75.0% | -5.0 percentage points |' in answer['text']
    possessive = respond("Compare Dr. Patel's utilization July vs August 2025", data)
    assert possessive['status'] == 'answered'
