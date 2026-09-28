from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_brief_local_generation_and_separate_discussion(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=40).run()
    generate = next(b for b in app.button if b.label == 'Generate AI Executive Brief')
    assert not generate.disabled
    generate.click().run()
    assert not app.exception
    assert app.session_state['executive_brief']['mode'] == 'Local preview — no AI call'
    next(w for w in app.text_input if w.label == 'Question about this brief').set_value('Where is our largest revenue opportunity?')
    next(b for b in app.button if b.label == 'Ask about brief').click().run()
    assert not app.exception
    assert len(app.session_state['brief_discussion']) == 2
    assert app.session_state['brief_discussion'][1]['status'] == 'answered'
    assert app.session_state['chat_history'] == []
    next(b for b in app.button if b.label == 'Clear brief conversation').click().run()
    assert app.session_state['brief_discussion'] == []
    assert not app.exception
