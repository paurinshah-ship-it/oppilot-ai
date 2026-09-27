from pathlib import Path
from streamlit.testing.v1 import AppTest
from scripts.evaluate_copilot import evaluate
from src.conversation import respond
from src.data import load_data


def test_evaluation(tmp_path):
    rows = evaluate(tmp_path / 'evaluation.csv')
    assert all(row['evaluation_result'] == 'PASS' for row in rows)


def test_filter_scope_and_missing_data():
    df = load_data()
    subset = df[df.provider == 'Dr. Maya Patel']
    assert respond('What is Dr. Ethan Chen utilization?', subset)['status'] == 'refused'
    assert respond('Summary', df.iloc[:0])['status'] == 'refused'
    result = respond('Most unused capacity?', subset)
    assert f'{(subset.capacity-subset.visits).sum():,}' in result['text']
    assert 'Dr. Ethan Chen' not in result['text']
    assert 'self-comparison' in respond('Dr. Maya Patel utilization?', subset)['text']


def test_chat_history_suggestions_clear_and_filters():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=30).run()
    next(b for b in app.button if b.label == 'Where is our largest revenue opportunity?').click().run()
    assert len(app.chat_message) == 2
    app.chat_input[0].set_value('Why is their utilization lower?').run()
    assert len(app.chat_message) == 4
    assert 'not its cause' in app.chat_message[1].markdown[0].value
    next(w for w in app.slider if w.label == "Target utilization (%)").set_value(90).run()
    assert len(app.chat_message) == 0
    app.chat_input[0].set_value('Summarize performance').run()
    next(b for b in app.button if b.label == 'Clear chat').click().run()
    assert len(app.chat_message) == 0
    assert not app.exception
