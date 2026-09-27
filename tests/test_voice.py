import base64
import io
import wave
import numpy as np
import pytest
from src.voice import decode_audio, VoiceError, process_turn
from src.data import load_data


def wav_data(samples, rate=16000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        f.writeframes(np.asarray(samples, dtype='<i2').tobytes())
    return base64.b64encode(output.getvalue()).decode()


def test_audio_validation():
    assert len(decode_audio(wav_data([1000]*16000))) == 16000
    for invalid in ['not base64', 'a'*900001, wav_data([0]*16000), wav_data([1000]*16000, 8000), wav_data([1000]*400000)]:
        with pytest.raises(VoiceError):
            decode_audio(invalid)


def test_transcript_uses_existing_grounding():
    question, reply = process_turn({'audio': 'mock'}, load_data(), .85, [],
                                  transcriber=lambda _: 'Which providers have the most unused capacity?')
    assert reply['status'] == 'answered'
    assert 'unused slots' in reply['text']
    _, refusal = process_turn({'audio': 'mock'}, load_data(), .85, [],
                              transcriber=lambda _: 'What medication should this patient take?')
    assert refusal['status'] == 'refused'
