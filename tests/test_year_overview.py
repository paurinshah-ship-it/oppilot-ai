from datetime import date
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from src.conversation import respond
from src.date_ranges import parse_date_range
from src.data import load_data


@pytest.mark.parametrize('question', ['2023', 'in 2023', 'Full year comparison 2023', 'Compare providers, clinics, and specialties in 2023'])
def test_year_overview(question):
    raw = load_data()
    reply = respond(question, raw[raw.date.dt.year == 2025], raw_df=raw)
    selected = raw[raw.date.dt.year == 2023]
    assert reply['status'] == 'answered'
    assert f'{selected.visits.sum():,} completed visits' in reply['text']
    assert 'Jan 1, 2023–Dec 31, 2023' in reply['grounding']
    assert all(f'**{name}**' in reply['text'] for name in ['Providers', 'Clinics', 'Specialties'])
    clinic = sorted(selected.clinic.unique())[0]
    clinic_rows = selected[selected.clinic == clinic]
    assert f'| {clinic} | {clinic_rows.visits.sum():,} | {clinic_rows.capacity.sum():,} | {clinic_rows.visits.sum()/clinic_rows.capacity.sum():.1%}' in reply['text']


def test_year_bounds_and_missing_coverage():
    bounds = (date(2021,1,1), date(2025,12,31))
    parsed = parse_date_range('2023', date(2026,9,26), *bounds)
    assert parsed['requested_start'] == date(2023,1,1)
    assert parsed['requested_end'] == date(2023,12,31)
    assert parse_date_range('2023 and 2024', date.today(), *bounds)['status'] == 'invalid'
    assert respond('2026', load_data())['status'] == 'unavailable'


def test_newest_exchange_first_history_stays_chronological():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    app.chat_input[0].set_value('Summarize performance').run()
    app.chat_input[0].set_value('2023').run()
    assert not app.exception
    assert app.chat_message[0].markdown[0].value == '2023'
    assert '**Clinics**' in app.chat_message[1].markdown[0].value
    assert app.chat_message[2].markdown[0].value == 'Summarize performance'
    history = app.session_state.chat_history
    assert history[0]['text'] == 'Summarize performance'
    assert history[2]['text'] == '2023'


def test_year_overview_retains_team_selection():
    selected = load_data().query("provider == 'Dr. Maya Patel'")
    reply = respond('2023', selected[selected.date.dt.year == 2025], raw_df=selected)
    assert reply['status'] == 'answered'
    expected = selected[selected.date.dt.year == 2023].visits.sum()
    assert f'{expected:,} completed visits' in reply['text']
    assert 'Dr. Maya Patel' in reply['text']
    assert 'Dr. Ethan Chen' not in reply['text']
