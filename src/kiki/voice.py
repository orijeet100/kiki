"""Voice loop (v0.2): mic -> wake gate -> VAD -> Whisper -> agent -> Piper -> speaker.

Nothing reaches VAD or speech-to-text until "hey jarvis" is heard (NFR-0.1, ADR 0003).
One wake word = one command (ADR 0009).
"""

import asyncio
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

from kiki import tools, ui
from kiki.agent import run_turn, warm_up
from kiki.db import connect
from kiki.events import record_turn, set_state

SAMPLE_RATE = 16000
WAKE_CHUNK_SAMPLES = 1280  # openWakeWord scores 80 ms chunks of 16 kHz int16
WAKE_THRESHOLD = float(os.environ.get("KIKI_WAKE_THRESHOLD", "0.5"))
WAKE_REFRACTORY_SECS = 2.0  # one "hey jarvis" scores high for several chunks
LISTEN_TIMEOUT_SECS = float(os.environ.get("KIKI_LISTEN_TIMEOUT_SECS", "6"))
# Silence that ends a command. Pipecat's default (0.2 s) cuts people off mid-sentence.
VAD_STOP_SECS = float(os.environ.get("KIKI_VAD_STOP_SECS", "0.8"))
# base.en takes 0.5 s per command vs 1.6 s for small.en; small.en is the fallback if it mishears.
WHISPER_MODEL = os.environ.get("KIKI_WHISPER_MODEL", "base.en")
# Primes Whisper with list vocabulary and spoken quantities. Without it base.en hears "braid",
# "cut the eggs" and "milk to apples" (ADR 0019).
WHISPER_PROMPT = (
    "Grocery list. Add two apples, three milks, bread and eggs. Got the milk. "
    "Remove the eggs. What's on my list?"
)
PIPER_VOICE = os.environ.get("KIKI_PIPER_VOICE", "en_US-lessac-medium")


def chime(freqs: list[float], ms: int = 80) -> bytes:
    """Short sine tones with fades, as 16 kHz int16 PCM."""
    n = SAMPLE_RATE * ms // 1000
    fade = np.minimum(
        1, np.minimum(np.arange(n), np.arange(n)[::-1]) / (SAMPLE_RATE * 0.006)
    )
    t = np.arange(n) / SAMPLE_RATE
    pcm = np.concatenate([np.sin(2 * np.pi * f * t) * fade for f in freqs])
    return (pcm * 0.25 * 32767).astype("<i2").tobytes()


LISTENING_CHIME = chime([660, 990])  # rising: "I'm listening"
DONE_CHIME = chime([990, 660])  # falling: "I stopped listening"


def hey_jarvis_detector() -> Callable[[np.ndarray], float]:
    """openWakeWord's bundled "hey jarvis" model, as chunk -> score."""
    import openwakeword
    from openwakeword.model import Model

    path = Path(openwakeword.__file__).parent / "resources/models/hey_jarvis_v0.1.onnx"
    model = Model(wakeword_model_paths=[str(path)])
    return lambda chunk: max(model.predict(chunk).values())


class WakeGate(FrameProcessor):
    """Drops mic audio until the wake word; then lets one utterance through (FR-0.11, NFR-0.1).

    Saying the wake word while Kiki speaks interrupts the speech (FR-0.12).
    """

    def __init__(self, detect: Callable[[np.ndarray], float] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._detect = detect or hey_jarvis_detector()
        self._buffer = bytearray()
        self._last_wake = -WAKE_REFRACTORY_SECS
        self._listening = False
        self._heard_speech = False
        self._listening_since = 0.0
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            if self._heard_wake_word(frame.audio):
                await self._start_listening()
            silent_too_long = (
                time.monotonic() - self._listening_since > LISTEN_TIMEOUT_SECS
            )
            if self._listening and not self._heard_speech and silent_too_long:
                await self._stop_listening()
            if self._listening:
                await self.push_frame(frame, direction)
            return  # closed gate: audio goes nowhere

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._heard_speech = True
        elif isinstance(frame, VADUserStoppedSpeakingFrame) and self._listening:
            await self._stop_listening()  # one command per wake word
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        await self.push_frame(frame, direction)

    def _heard_wake_word(self, audio: bytes) -> bool:
        self._buffer += audio
        heard = False
        chunk_bytes = WAKE_CHUNK_SAMPLES * 2
        while len(self._buffer) >= chunk_bytes:
            chunk = np.frombuffer(bytes(self._buffer[:chunk_bytes]), dtype=np.int16)
            del self._buffer[:chunk_bytes]
            # ponytail: scored inline (~ms per chunk); move to an executor if the loop ever lags.
            if self._detect(chunk) >= WAKE_THRESHOLD:
                now = time.monotonic()
                if now - self._last_wake > WAKE_REFRACTORY_SECS:
                    self._last_wake = now
                    heard = True
        return heard

    async def _start_listening(self):
        if self._bot_speaking:
            await self.broadcast_interruption()
        self._listening = True
        self._heard_speech = False
        self._listening_since = time.monotonic()
        set_state("listening")
        await self._play(LISTENING_CHIME)

    async def _stop_listening(self):
        self._listening = False
        set_state("thinking" if self._heard_speech else "idle")
        await self._play(DONE_CHIME)

    async def _play(self, pcm: bytes):
        await self.push_frame(
            OutputAudioRawFrame(audio=pcm, sample_rate=SAMPLE_RATE, num_channels=1)
        )


class Brain(FrameProcessor):
    """Transcript in, spoken reply out, via the same agent as the terminal (v0.1)."""

    def __init__(self, conn, model=None, **kwargs):
        super().__init__(**kwargs)
        self._conn = conn
        self._model = model
        self._speech_ended = time.monotonic()
        self._waiting_for_speech: tuple[dict, float] | None = None
        self._last_error = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._speech_ended = time.monotonic()
        elif isinstance(frame, TranscriptionFrame) and frame.text.strip():
            await self._answer(frame.text.strip())
            return
        elif isinstance(frame, BotStartedSpeakingFrame):
            set_state("speaking")
            if self._waiting_for_speech:
                self._log_turn(time.monotonic())
        elif isinstance(frame, BotStoppedSpeakingFrame):
            set_state("error" if self._last_error else "idle")
        await self.push_frame(frame, direction)

    async def _answer(self, text: str):
        if (
            self._waiting_for_speech
        ):  # previous reply never started playing; log it anyway
            self._log_turn(None)
        stt_done = time.monotonic()
        turn = await asyncio.to_thread(run_turn, text, self._conn, self._model, "voice")
        turn["latency_ms"]["stt"] = round((stt_done - self._speech_ended) * 1000)
        self._last_error = bool(turn["error"])
        self._waiting_for_speech = (turn, time.monotonic())
        await self.push_frame(TTSSpeakFrame(turn["said"]))

    def _log_turn(self, first_audio: float | None):
        turn, reply_ready = self._waiting_for_speech
        self._waiting_for_speech = None
        if first_audio is not None:
            turn["latency_ms"]["tts"] = round((first_audio - reply_ready) * 1000)
            turn["latency_ms"]["total"] = round(
                (first_audio - self._speech_ended) * 1000
            )
        record_turn(turn, tools.read_list(self._conn)["items"])


def processors(conn, model=None) -> list[FrameProcessor]:
    """Everything between the mic and the speaker."""
    from pipecat.services.piper.tts import PiperTTSService
    from pipecat.services.whisper.stt import WhisperSTTService

    return [
        WakeGate(),
        VADProcessor(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=VAD_STOP_SECS))
        ),
        WhisperSTTService(
            settings=WhisperSTTService.Settings(
                model=WHISPER_MODEL, initial_prompt=WHISPER_PROMPT
            ),
            device="cpu",
            compute_type="int8",
        ),
        Brain(conn, model),
        PiperTTSService(settings=PiperTTSService.Settings(voice=PIPER_VOICE)),
    ]


async def run() -> None:
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=SAMPLE_RATE,
        )
    )
    warm_up()
    conn = connect()
    server = ui.serve(conn)
    pipeline = Pipeline([transport.input(), *processors(conn), transport.output()])
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=SAMPLE_RATE),
        idle_timeout_secs=None,  # always on: never shut down for being quiet
    )
    print(
        f'Kiki. Say "hey jarvis", then a command. UI: {ui.url(server)}  (Ctrl+C to stop)'
    )
    runner = WorkerRunner(handle_sigint=sys.platform != "win32")
    await runner.add_workers(worker)
    await runner.run()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
