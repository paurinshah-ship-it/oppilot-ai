"""Offline voice transport and transcription. Audio is processed in RAM only."""
import base64
import io
from pathlib import Path
import threading
import wave
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from src.conversation import respond

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / '.models' / 'tiny.en'
MAX_SECONDS = 20


class VoiceError(ValueError):
    pass


def decode_audio(encoded):
    """Accept only bounded mono 16-bit WAV at 16 kHz; reject silence/invalid input."""
    if not isinstance(encoded, str) or len(encoded) > 900000:
        raise VoiceError('Audio is too large. Keep each question under 20 seconds.')
    try:
        raw = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(raw), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise VoiceError('Unsupported audio format.')
            if not 3200 <= wav.getnframes() <= MAX_SECONDS * 16000:
                raise VoiceError('Ask a question between 0.2 and 20 seconds long.')
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
        if not len(audio) or np.sqrt(np.mean(audio ** 2)) < .002:
            raise VoiceError('No clear speech detected. Please try again.')
        return audio
    except VoiceError:
        raise
    except (ValueError, EOFError, wave.Error):
        raise VoiceError('Audio could not be read. Please try again.') from None


@st.cache_resource
def recognizer():
    from faster_whisper import WhisperModel
    # A path + local_files_only prevents runtime network downloads or cloud calls.
    return WhisperModel(str(MODEL_PATH), device='cpu', compute_type='int8',
                        cpu_threads=4, local_files_only=True), threading.Lock()


def transcribe(encoded):
    audio = decode_audio(encoded)
    if not (MODEL_PATH / 'model.bin').exists():
        raise VoiceError('Local model missing. Run python scripts/setup_voice.py.')
    try:
        model, lock = recognizer()
        with lock:
            segments, _ = model.transcribe(audio, language='en', beam_size=1,
                                          condition_on_previous_text=False, vad_filter=True)
            text = ' '.join(s.text.strip() for s in segments if s.no_speech_prob < .6 and s.avg_logprob > -1).strip()
    except Exception:
        raise VoiceError('Local transcription failed. Check the voice installation and try again.') from None
    if not text:
        raise VoiceError('No clear speech detected. Please try again.')
    return text[:1000]


def process_turn(event, df, target, history, transcriber=transcribe, raw_df=None, data_bounds=None):
    text = transcriber(event.get('audio'))
    reply = respond(text, df, target, history, raw_df=raw_df, data_bounds=data_bounds)
    return text, reply


def render_voice(df, target, scope, raw_df=None, data_bounds=None):
    """Stable component key preserves microphone across Streamlit reruns.

    Each utterance has a session token and monotonic turn. Frontend rejects
    responses superseded by speech, Stop, a filter change, or Clear chat.
    """
    st.session_state.setdefault('voice_history', [])
    component = components.declare_component('local_voice', path=str(ROOT / 'voice_frontend'))
    ready = (MODEL_PATH / 'model.bin').exists()
    event = component(scope=scope, ready=ready, response=st.session_state.get('voice_response'),
                      key='continuous_voice', default=None)
    if not isinstance(event, dict) or event.get('scope') != scope:
        return
    token = (event.get('session'), event.get('turn'))
    if event.get('type') == 'clear':
        if token != st.session_state.get('voice_processed'):
            st.session_state.voice_processed = token
            st.session_state.voice_history = []
            st.session_state.pop('voice_response', None)
            st.rerun()
        return
    if token == st.session_state.get('voice_processed') or event.get('type') != 'audio':
        return
    st.session_state.voice_processed = token
    try:
        question, reply = process_turn(event, df, target, st.session_state.voice_history, raw_df=raw_df, data_bounds=data_bounds)
        st.session_state.voice_history.extend([{'role': 'user', 'text': question}, {'role': 'assistant', **reply}])
        st.session_state.voice_history = st.session_state.voice_history[-40:]
        response = {'text': reply['text'], 'transcript': question}
    except VoiceError as exc:
        response = {'error': str(exc)}
    st.session_state.voice_response = {**response, 'session': event.get('session'),
                                     'turn': event.get('turn'), 'scope': scope}
    st.rerun()
