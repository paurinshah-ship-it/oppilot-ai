import pandas as pd
import pytest
from src.deep_analysis import annual_summary, deep_answer
from src.conversation import respond
from src.data import load_data


def fixture_data():
    rows = []
    for year, visits in [(2024, 5), (2025, 8)]:
        for date in pd.bdate_range(f'{year}-01-01', f'{year}-12-31'):
            rows.append(dict(date=date, provider_id='A', provider='Dr. Demo Example', specialty='Demo',
                             clinic='Demo Clinic', visits=visits, capacity=10, booked=9,
                             no_shows=9-visits, revenue=visits*100, staffed_hours=5))
    return pd.DataFrame(rows)


def test_weighted_annual_and_improvement():
    df = fixture_data()
    summary = annual_summary(df)
    assert summary.complete.all()
    assert summary.loc[2024, 'utilization'] == .5
    assert summary.loc[2025, 'utilization'] == .8
    assert summary.loc[2025, 'productivity'] == 1.6
    text = deep_answer('which providers improved utilization the most?', df, .85)
    assert '+30.0 pp' in text
    assert '2024→2025' in text
    partial = df[df.date >= pd.Timestamp('2024-06-01')]
    assert not annual_summary(partial).loc[2024, 'complete']
    assert 'needed' in deep_answer('year over year', partial, .85)


def test_scenario_and_concentration_hand_calculation():
    df = fixture_data().query('date.dt.year == 2025').head(1)
    # 8 visits, 10 slots, $100/visit => 1 additional visit at 90%, $100 opportunity.
    assert '$100' in deep_answer('what if utilization reached 90%?', df, .85)
    assert '100.0%' in deep_answer('how concentrated is our revenue opportunity?', df, .85)
    assert '50.0%' in deep_answer('unused capacity breakdown', df, .85)


def test_names_followups_and_known_but_filtered_provider():
    df = load_data()
    assert respond('Why is Dr. Patel utilization lower?', df)['provider'] == 'Dr. Maya Patel'
    assert respond('Why is Dr. Maya Patel utilization lower?', df)['status'] == 'limited'
    assert respond('Why is Dr. Unknown utilization lower?', df)['status'] == 'refused'
    subset = df[df.provider != 'Dr. Maya Patel']
    assert 'not in the current selection' in respond('Dr. Patel utilization?', subset)['text']
    assert respond('Predict next year revenue', df)['status'] == 'refused'


def test_reporting_period_shortcuts():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    next(w for w in app.selectbox if w.label == "Reporting period").set_value('Latest calendar year').run()
    assert not app.exception
    assert app.date_input[0].value[0].year == 2025
    next(w for w in app.selectbox if w.label == "Reporting period").set_value('Latest two calendar years').run()
    assert app.date_input[0].value[0].year == 2024
    next(w for w in app.selectbox if w.label == "Reporting period").set_value('All five years').run()
    assert app.date_input[0].value[0].year == 2021
    assert not app.exception


def test_date_widget_has_one_owner_and_handles_incomplete_range(caplog, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import streamlit.elements.lib.policies as policies
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    assert not app.exception
    assert 'also had its value set' not in caplog.text
    start = app.date_input[0].value[0]
    app.date_input[0].set_value((start,)).run()
    assert not app.exception
    assert any('Select both a start and end date' in item.value for item in app.info)
