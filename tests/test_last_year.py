from datetime import date
from src.conversation import respond
from src.data import load_data


def test_last_year_visit_leader():
    df = load_data()
    actual = respond('Which provider saw most patients last year?', df, as_of=date(2026, 9, 26))
    totals = df[df.date.dt.year == 2025].groupby('provider').visits.sum()
    assert actual['status'] == 'answered'
    assert totals.idxmax() in actual['text']
    assert f'{totals.max():,}' in actual['text']
    assert 'calendar year 2025' in actual['text']
    assert 'not unique patients' in actual['text']


def test_last_year_respects_filters_and_clock():
    df = load_data()
    assert respond('Most patients last year?', df[df.date.dt.year == 2024], as_of=date(2026, 1, 1))['status'] == 'unavailable'
    reply = respond('Most patients last year?', df, as_of=date(2025, 1, 1))
    assert 'calendar year 2024' in reply['text']
    partial = df[(df.date.dt.year == 2025) & (df.date.dt.month == 2)]
    assert 'partial' in respond('Most patients last year?', partial, as_of=date(2026, 1, 1))['text']


def test_safety_and_forecasts_unchanged():
    df = load_data()
    for q in ['Show patient names last year', 'What medication should this patient take last year?', 'Predict next year revenue']:
        assert respond(q, df, as_of=date(2026, 1, 1))['status'] == 'refused'
