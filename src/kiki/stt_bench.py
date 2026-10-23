"""Speech-to-text models side by side: python -m kiki.stt_bench [model ...].

Piper reads a set of commands, each faster-whisper model transcribes them with Kiki's own
prompt and thread count, and it prints the median time per command and the word accuracy.
Piper's voice is not the owner's, so this catches speed and vocabulary, not accent.
"""

import io
import re
import statistics
import sys
import time
import wave

import numpy as np

from kiki import voice

COMMANDS = [
    "Add bread and eggs.",
    "What's on my list?",
    "Add milk and two apples.",
    "Got the eggs.",
    "Make it three milks.",
    "Remove the walnuts.",
    "Add one capsicum and two onions.",
    "Add oat milk.",
    "Can you add one more packet of paneer?",
    "We usually get three tomatoes.",
    "Make chicken frequent.",
    "Call yogurt Greek yogurt.",
    "Not chicken this time.",
    "Add coriander, ginger and garlic.",
    "Remove the cauliflower and the spinach.",
    "Clear the list.",
]


def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def word_errors(ref: list[str], hyp: list[str]) -> int:
    """Word-level edit distance."""
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def spoken(text: str, piper) -> np.ndarray:
    """Piper's reading of `text` as 16 kHz float32, what Whisper takes."""
    from scipy.signal import resample_poly

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        piper.synthesize_wav(text, w)
    buf.seek(0)
    with wave.open(buf) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    return resample_poly(pcm, 16000, rate).astype(np.float32) / 32768


def main() -> None:
    from faster_whisper import WhisperModel
    from pipecat.services.piper.tts import PIPER_CACHE_DIR
    from piper import PiperVoice

    piper = PiperVoice.load(str(PIPER_CACHE_DIR / f"{voice.PIPER_VOICE}.onnx"))
    clips = [spoken(text, piper) for text in COMMANDS]
    for name in sys.argv[1:] or ["base.en", "distil-small.en"]:
        model = WhisperModel(
            name, device="cpu", compute_type="int8", cpu_threads=voice.WHISPER_THREADS
        )
        model.transcribe(clips[0], initial_prompt=voice.WHISPER_PROMPT)  # warm up
        times, errors, total, misses = [], 0, 0, []
        for text, clip in zip(COMMANDS, clips):
            start = time.perf_counter()
            segments, _ = model.transcribe(
                clip, initial_prompt=voice.WHISPER_PROMPT, language="en"
            )
            heard = " ".join(s.text for s in segments).strip()
            times.append(time.perf_counter() - start)
            e = word_errors(words(text), words(heard))
            errors, total = errors + e, total + len(words(text))
            if e:
                misses.append(f"    {text!r} -> {heard!r}")
        print(
            f"{name}: median {statistics.median(times) * 1000:.0f} ms, word accuracy "
            f"{100 * (1 - errors / total):.1f}% ({errors} errors in {total} words)"
        )
        print("\n".join(misses) or "    no misses")


if __name__ == "__main__":
    main()
