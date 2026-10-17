"""Voice loop tests.

Gate tests use a fake detector and run instantly. Tests marked `voice` run the real models
(openWakeWord, Silero, Whisper) on speech synthesized by Piper, with a scripted agent model:
no microphone, no API cost. First run downloads the Whisper and Piper models.
"""

import asyncio
import io
import os
import wave

import numpy as np
import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from kiki import tools, voice
from kiki.db import connect


def mic(samples: np.ndarray) -> list[InputAudioRawFrame]:
    """16 kHz int16 samples as 20 ms mic frames."""
    pcm = samples.astype(np.int16).tobytes()
    step = 640  # 320 samples * 2 bytes
    return [
        InputAudioRawFrame(audio=pcm[i : i + step], sample_rate=16000, num_channels=1)
        for i in range(0, len(pcm), step)
    ]


def silence(secs: float) -> list[InputAudioRawFrame]:
    return mic(np.zeros(int(16000 * secs), np.int16))


class FakeDetector:
    """Scores 1.0 for chunks that are all 1000s (the 'wake word'), else 0."""

    def __call__(self, chunk):
        return 1.0 if (chunk == 1000).all() else 0.0


WAKE = mic(np.full(1280, 1000))


def chimes(frames) -> list[bytes]:
    return [f.audio for f in frames if isinstance(f, OutputAudioRawFrame)]


def downstream(frames):
    down, _ = asyncio.run(
        run_test(voice.WakeGate(detect=FakeDetector()), frames_to_send=frames)
    )
    return down


def test_nfr_0_1_closed_gate_passes_no_audio():
    down = downstream(silence(1))
    assert not any(isinstance(f, InputAudioRawFrame) for f in down)


def test_fr_0_11_wake_word_opens_gate_with_chime():
    down = downstream(WAKE + silence(0.2))
    assert chimes(down) == [voice.LISTENING_CHIME]
    assert any(isinstance(f, InputAudioRawFrame) for f in down)


def test_fr_0_11_end_of_speech_closes_gate_with_chime():
    gate = voice.WakeGate(detect=FakeDetector())
    frames = [
        *WAKE,
        VADUserStartedSpeakingFrame(),
        *silence(0.1),
        VADUserStoppedSpeakingFrame(),
        *silence(0.5),
    ]
    down, _ = asyncio.run(run_test(gate, frames_to_send=frames))
    assert chimes(down) == [voice.LISTENING_CHIME, voice.DONE_CHIME]
    done = next(
        i for i, f in enumerate(down) if getattr(f, "audio", None) == voice.DONE_CHIME
    )
    after_close = down[done:]
    assert not any(isinstance(f, InputAudioRawFrame) for f in after_close)


def test_fr_0_11_gate_closes_if_nothing_is_said(monkeypatch):
    monkeypatch.setattr(voice, "LISTEN_TIMEOUT_SECS", -1)
    down = downstream(WAKE + silence(0.2))
    assert chimes(down) == [voice.LISTENING_CHIME, voice.DONE_CHIME]


def test_fr_0_12_wake_word_while_speaking_interrupts():
    gate = voice.WakeGate(detect=FakeDetector())

    async def go():
        await run_test(
            gate,
            frames_to_send=[BotStartedSpeakingFrame()],
            frames_to_send_direction=FrameDirection.UPSTREAM,
        )
        return await run_test(gate, frames_to_send=WAKE)

    down, up = asyncio.run(go())
    assert any(isinstance(f, InterruptionFrame) for f in down)
    assert any(isinstance(f, InterruptionFrame) for f in up)


class FakeSpeaker(FrameProcessor):
    """Stands in for the speaker: reports BotStartedSpeaking on the first reply audio, as the
    real output transport does, so the Brain logs voice latencies."""

    def __init__(self):
        super().__init__()
        self._speaking = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame) and not self._speaking:
            self._speaking = True
            await self.push_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        elif isinstance(frame, TTSStoppedFrame):
            self._speaking = False
        await self.push_frame(frame, direction)


# --- real models on synthesized speech -------------------------------------------------


@pytest.fixture(scope="module")
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


def run_voice(tmp_path, audio_frames):
    """The app's own processor chain (gate, VAD, Whisper, Brain, Piper) with a scripted model."""
    from pipecat.pipeline.pipeline import Pipeline

    heard = []

    def model_fn(messages, info):
        heard.append(messages[0].parts[0].content)
        args = {
            "add": [{"name": "bread"}, {"name": "milk", "quantity": 2}],
            "reply": "Added bread and two milks.",
        }
        return ModelResponse(parts=[ToolCallPart("update_list", args)])

    conn = connect(str(tmp_path / "voice.db"))
    pipeline = Pipeline(voice.processors(conn, FunctionModel(model_fn)))
    down, _ = asyncio.run(
        run_test(pipeline, frames_to_send=[*audio_frames, SleepFrame(sleep=15)])
    )
    return down, heard, conn


@pytest.mark.voice
def test_nfr_0_2_end_to_end_only_text_reaches_the_model(tmp_path, speak, monkeypatch):
    monkeypatch.setenv("KIKI_LOG", str(tmp_path / "turns.jsonl"))
    audio = [
        *silence(0.5),
        *mic(speak("Hey Jarvis.")),
        *silence(0.3),
        *mic(speak("Add bread and two milks.")),
        *silence(2),
    ]
    down, heard, conn = run_voice(tmp_path, audio)
    assert len(heard) == 1 and isinstance(heard[0], str), (
        heard
    )  # a transcript, never audio
    assert "bread" in heard[0].lower(), heard
    assert any(isinstance(f, TTSAudioRawFrame) for f in down)  # Piper spoke the reply
    assert {i["name"] for i in tools.read_list(conn)["items"]} == {"bread", "milk"}


@pytest.mark.voice
def test_nfr_0_1_no_wake_word_nothing_transcribed(tmp_path, speak):
    audio = [*silence(0.5), *mic(speak("Add bread and two milks.")), *silence(2)]
    down, heard, conn = run_voice(tmp_path, audio)
    assert heard == []
    assert not any(isinstance(f, TranscriptionFrame | TTSAudioRawFrame) for f in down)
    assert tools.read_list(conn)["items"] == []


VOICE_SCENARIOS = [  # ROADMAP scenarios required by the v0.2 definition of done
    ("1", [], "Add bread and eggs.", {"bread": 1, "egg": 1}),
    ("2", [("bread", 1)], "Add bread.", {"bread": 1}),
    (
        "5",
        [],
        "Add milk, two apples and some rice.",
        {"milk": 1, "apple": 2, "rice": 1},
    ),
    (
        "6",
        [("milk", 3), ("eggs", 1), ("rice", 1)],
        "Got the milk and eggs.",
        {"rice": 1},
    ),
    ("8", [("bread", 1), ("milk", 1), ("eggs", 1)], "What's on my list?", None),
    ("10", [("bread", 1), ("milk", 1), ("rice", 1)], "Clear the list.", {}),
    ("11", [("rice", 1)], "Blorp the frim.", {"rice": 1}),
]


@pytest.mark.voice
@pytest.mark.scenario
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"
)
@pytest.mark.parametrize("number, seed, command, expected", VOICE_SCENARIOS)
def test_scenario_by_voice(
    tmp_path, speak, monkeypatch, number, seed, command, expected
):
    from pipecat.frames.frames import TTSTextFrame
    from pipecat.pipeline.pipeline import Pipeline

    monkeypatch.setenv("KIKI_LOG", str(tmp_path / "turns.jsonl"))
    conn = connect(str(tmp_path / "voice.db"))
    tools.add_items(conn, [{"name": n, "quantity": q} for n, q in seed])
    before = {
        tools.normalize(i["name"]): i["quantity"]
        for i in tools.read_list(conn)["items"]
    }
    audio = [
        *silence(0.5),
        *mic(speak("Hey Jarvis.")),
        *silence(0.3),
        *mic(speak(command)),
        *silence(2),
    ]
    down, _ = asyncio.run(
        run_test(
            Pipeline(voice.processors(conn)),
            frames_to_send=[*audio, SleepFrame(sleep=20)],
        )
    )
    state = {
        tools.normalize(i["name"]): i["quantity"]
        for i in tools.read_list(conn)["items"]
    }
    said = " ".join(f.text for f in down if isinstance(f, TTSTextFrame)).lower()
    assert said, "Kiki said nothing"
    assert state == (before if expected is None else expected), (said, state)
    if number == "8":
        assert all(n in said for n in ("bread", "milk", "egg")), said


LATENCY_COMMANDS = [
    "Add bread and eggs.",
    "What's on my list?",
    "Add milk and two apples.",
    "Got the eggs.",
    "Add some rice.",
    "Make it three milks.",
    "What's on my list?",
    "Remove the apples.",
    "Add butter and cheese.",
    "Got the bread and rice.",
]


@pytest.mark.voice
@pytest.mark.scenario
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"
)
def test_nfr_0_3_median_end_of_speech_to_first_audio(tmp_path, speak, monkeypatch):
    """Twenty spoken commands through the full chain; median from the turn log, as in the ROADMAP."""
    from pipecat.pipeline.pipeline import Pipeline

    from kiki.latency import report

    log = tmp_path / "turns.jsonl"
    monkeypatch.setenv("KIKI_LOG", str(log))
    conn = connect(str(tmp_path / "voice.db"))
    frames = []
    for command in LATENCY_COMMANDS * 2:
        frames += [
            *silence(0.5),
            *mic(speak("Hey Jarvis.")),
            *silence(0.3),
            *mic(speak(command)),
            *silence(1.5),
            SleepFrame(sleep=6),
        ]
    asyncio.run(
        run_test(
            Pipeline([*voice.processors(conn), FakeSpeaker()]), frames_to_send=frames
        )
    )
    medians = report(str(log))
    assert len(log.read_text(encoding="utf-8").splitlines()) == 20
    assert medians["total"] <= 2000, medians
