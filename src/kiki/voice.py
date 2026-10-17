"""Voice loop: mic -> wake gate -> VAD -> end of turn -> Whisper -> agent -> Piper -> speaker.

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
from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer, EndOfTurnState
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
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
    UserStoppedSpeakingFrame,
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
# After each spoken reply, Kiki listens this long without the wake word (ADR 0022).
FOLLOW_UP_SECS = float(os.environ.get("KIKI_FOLLOW_UP_SECS", "5"))
# The end of Kiki's own reply can still be in the room when playback ends; ignore it.
ECHO_GUARD_SECS = 0.3
# A pause this long makes Smart Turn check whether the sentence sounds finished (ADR 0021).
# Smart Turn is trained to judge at 0.2 s; at 0.5 s it called "Can you add one..." finished.
PAUSE_SECS = float(os.environ.get("KIKI_PAUSE_SECS", "0.2"))
# After a pause sounds finished, wait this much longer for more words before closing. Covers
# the commas in a spoken list: "Add milk, ..." sounds finished, but "two apples" follows.
END_GRACE_SECS = float(os.environ.get("KIKI_END_GRACE_SECS", "0.4"))
# Silence that ends a command even if it sounded unfinished (someone stopped mid-sentence).
MAX_PAUSE_SECS = float(os.environ.get("KIKI_MAX_PAUSE_SECS", "3"))
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
    """Drops mic audio unless Kiki is listening for a command (FR-0.11, FR-0.16, NFR-0.1).

    Kiki listens after the wake word, and for FOLLOW_UP_SECS after each spoken reply with no
    wake word (ADR 0022). Each listening session lets one command through; it ends when
    EndOfTurnDetector says so (UserStoppedSpeakingFrame), not at the first pause. Saying the
    wake word while Kiki speaks interrupts the speech (FR-0.12).
    """

    def __init__(self, detect: Callable[[np.ndarray], float] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._detect = detect or hey_jarvis_detector()
        self._buffer = bytearray()
        self._last_wake = -WAKE_REFRACTORY_SECS
        self._listening = False
        self._follow_up = False  # this session started after a reply, not the wake word
        self._heard_speech = False
        self._opens_at = 0.0
        self._gives_up_at = 0.0  # close if nobody has spoken by then
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            if self._heard_wake_word(frame.audio):
                await self._start_listening(LISTEN_TIMEOUT_SECS, follow_up=False)
            now = time.monotonic()
            if self._listening and not self._heard_speech and now > self._gives_up_at:
                await self._stop_listening()
            if self._listening and now >= self._opens_at:
                await self.push_frame(frame, direction)
            return  # closed gate: audio goes nowhere

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._heard_speech = True
        elif isinstance(frame, UserStoppedSpeakingFrame) and self._listening:
            await self._stop_listening()  # one command per session
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            if (
                not self._listening
            ):  # after an interruption the wake session is already open
                await self._start_listening(FOLLOW_UP_SECS, follow_up=True)
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

    async def _start_listening(self, timeout: float, follow_up: bool):
        if self._bot_speaking:
            await self.broadcast_interruption()
        delay = ECHO_GUARD_SECS if follow_up else 0
        now = time.monotonic()
        self._listening = True
        self._follow_up = follow_up
        self._heard_speech = False
        self._opens_at = now + delay
        self._gives_up_at = now + delay + timeout
        set_state("listening")
        if (
            not follow_up
        ):  # a chime after every reply would get old fast; the orb shows it
            await self._play(LISTENING_CHIME)

    async def _stop_listening(self):
        self._listening = False
        set_state("thinking" if self._heard_speech else "idle")
        if (
            self._heard_speech or not self._follow_up
        ):  # an unused follow-up ends silently
            await self._play(DONE_CHIME)

    async def _play(self, pcm: bytes):
        await self.push_frame(
            OutputAudioRawFrame(audio=pcm, sample_rate=SAMPLE_RATE, num_channels=1)
        )


class EndOfTurnDetector(FrameProcessor):
    """Ends a spoken command when it sounds finished, not at the first pause (ADR 0021).

    VAD reports every pause longer than PAUSE_SECS. At each one, Smart Turn (a small local
    model that listens to intonation) judges whether the sentence is finished. If it sounds
    finished and nobody speaks for END_GRACE_SECS more, the command ends; speech in the grace
    period (a list comma) keeps the same command going. Pauses that aren't the end are hidden
    from Whisper, so it transcribes the whole command once. After MAX_PAUSE_SECS of silence
    the command ends anyway.
    """

    def __init__(self, analyzer: BaseTurnAnalyzer | None = None, **kwargs):
        super().__init__(**kwargs)
        self._analyzer = analyzer or LocalSmartTurnAnalyzerV3(
            params=SmartTurnParams(stop_secs=MAX_PAUSE_SECS)
        )
        self._analyzer.set_sample_rate(SAMPLE_RATE)
        self._in_command = False
        self._speaking = False
        self._ends_at: float | None = None  # set while waiting out the grace period

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.UPSTREAM:
            return await self.push_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._speaking = True
            self._ends_at = None  # more words: not the end after all
            self._analyzer.update_vad_start_secs(frame.start_secs)
            if self._in_command:
                return  # speech resumed after a pause: still the same command
            self._in_command = True
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._speaking = False
            if self._in_command:
                state, _ = await self._analyzer.analyze_end_of_turn()
                if state == EndOfTurnState.COMPLETE:
                    self._ends_at = time.monotonic() + END_GRACE_SECS
            return  # a pause; Whisper only hears about the end of the command
        elif isinstance(frame, InputAudioRawFrame):
            silence_ran_out = (
                self._analyzer.append_audio(frame.audio, self._speaking)
                == EndOfTurnState.COMPLETE
            )
            await self.push_frame(frame, direction)
            grace_over = self._ends_at is not None and time.monotonic() >= self._ends_at
            if self._in_command and (silence_ran_out or grace_over):
                await self._end_command()
            return
        await self.push_frame(frame, direction)

    async def _end_command(self):
        self._in_command = False
        self._ends_at = None
        self._analyzer.clear()
        await self.push_frame(
            VADUserStoppedSpeakingFrame(stop_secs=PAUSE_SECS)
        )  # to Whisper
        await self.push_frame(
            UserStoppedSpeakingFrame(), FrameDirection.UPSTREAM
        )  # to the gate


class Brain(FrameProcessor):
    """Transcript in, spoken reply out, via the same agent as the terminal (v0.1).

    A command that starts within the follow-up window after a reply is sent with the
    previous command as context, so "and eggs" after "add chicken" makes sense (ADR 0022).
    """

    def __init__(self, conn, model=None, **kwargs):
        super().__init__(**kwargs)
        self._conn = conn
        self._model = model
        self._speech_started = 0.0
        self._speech_ended = time.monotonic()
        self._reply_ended: float | None = None
        self._last_command: str | None = None
        self._waiting_for_speech: tuple[dict, float] | None = None
        self._last_error = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._speech_started = time.monotonic()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._speech_ended = time.monotonic()
        elif isinstance(frame, TranscriptionFrame) and frame.text.strip():
            await self._answer(frame.text.strip())
            return
        elif isinstance(frame, BotStartedSpeakingFrame):
            set_state("speaking")
            if self._waiting_for_speech:
                self._log_turn(time.monotonic())
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._reply_ended = time.monotonic()
            set_state("error" if self._last_error else "idle")
        await self.push_frame(frame, direction)

    async def _answer(self, text: str):
        if (
            self._waiting_for_speech
        ):  # previous reply never started playing; log it anyway
            self._log_turn(None)
        stt_done = time.monotonic()
        previous = self._last_command if self._is_follow_up() else None
        self._last_command = text
        turn = await asyncio.to_thread(
            run_turn, text, self._conn, self._model, "voice", previous
        )
        turn["latency_ms"]["stt"] = round((stt_done - self._speech_ended) * 1000)
        self._last_error = bool(turn["error"])
        self._waiting_for_speech = (turn, time.monotonic())
        await self.push_frame(TTSSpeakFrame(turn["said"]))

    def _is_follow_up(self) -> bool:
        """Did this command start within the follow-up window after the last reply?"""
        if self._reply_ended is None:
            return False
        since_reply = self._speech_started - self._reply_ended
        return 0 <= since_reply <= ECHO_GUARD_SECS + FOLLOW_UP_SECS

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
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=PAUSE_SECS))
        ),
        EndOfTurnDetector(),
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

    conn = connect()
    try:
        server = ui.serve(conn)  # first: fails fast if Kiki is already running
    except ui.AlreadyRunning as e:
        sys.exit(str(e))
    warm_up()
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=SAMPLE_RATE,
        )
    )
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
