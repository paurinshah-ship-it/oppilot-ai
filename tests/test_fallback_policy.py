from datetime import date
import pytest
from src.conversation import respond
from src.data import generate_data, validate_data

@pytest.fixture(scope='module')
def df():
    return validate_data(generate_data(start='2025-07-01',days=62))

@pytest.mark.parametrize('q',[
    'What is the weather?', 'Why did collections decline?',
    'Show revenue by age', 'Show anomalies excluding North',
    'How about last month?', 'Compare him with the specialty average',
    'Compare cardiology utilization this quarter versus last quarter',
    'Which provider saw most patients last year?', 'Show patient names',
    'Chart clinical quality', 'What happens if no-shows drop to 500%?', '',
])
def test_all_routes_offer_answerable_alternatives(df,q):
    r=respond(q,df,as_of=date(2026,9,27))
    assert r['status']!='answered'
    assert len(r['suggested_questions'])==3
    assert r['text'].count('You can ask instead:')==1
    for suggestion in r['suggested_questions']:
        assert respond(suggestion,df,as_of=date(2026,9,27))['status']=='answered'


def test_empty_selection_offers_definitions(df):
    empty=df.iloc[:0]
    r=respond('Show revenue',empty)
    assert len(r['suggested_questions'])==3
    for suggestion in r['suggested_questions']:
        assert respond(suggestion,empty)['status']=='answered'


def test_success_not_rewritten(df):
    r=respond('Show utilization by clinic',df)
    assert r['status']=='answered'
    assert 'You can ask instead' not in r['text']


def test_alternative_button_runs_question():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=40).run()
    app.chat_input[0].set_value('Why did collections decline?').run()
    assert not app.exception
    buttons=[b for b in app.button if str(b.key).startswith('alternative_')]
    assert len(buttons)==3
    prompt=buttons[0].label
    buttons[0].click().run()
    assert not app.exception
    assert app.session_state.chat_history[-2]['text']==prompt
    assert app.session_state.chat_history[-1]['status']=='answered'
