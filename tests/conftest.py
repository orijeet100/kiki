"""Fixtures shared by the voice tests (test_voice.py, test_tab5.py)."""

import io
import wave

import numpy as np
import pytest

from kiki import voice


@pytest.fixture(scope="session")
def speak():
    from pipecat.services.piper.tts import PIPER_CACHE_DIR
    from piper import PiperVoice
    from piper.download_voices import download_voice
    from scipy.signal import resample_poly

    path = PIPER_CACHE_DIR / f"{voice.PIPER_VOICE}.onnx"
    if not path.exists():
        PIPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        download_voice(voice.PIPER_VOICE, PIPER_CACHE_DIR)
    piper = PiperVoice.load(str(path))

    def speak(text):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            piper.synthesize_wav(text, w)
        buf.seek(0)
        with wave.open(buf) as w:
            rate = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        return resample_poly(pcm, 16000, rate)

    return speak
