"""Voice loop: mic -> wake gate -> VAD -> end of turn -> Whisper -> agent -> Piper -> speaker.

Nothing reaches VAD or speech-to-text until "hey jarvis" is heard (NFR-0.1, ADR 0003), except
for a few seconds after each reply (FR-0.18, ADR 0025). Each command is single-turn (ADR 0009).
"""

import asyncio
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from loguru import logger
from pipecat.audio.mixers.base_audio_mixer import BaseAudioMixer
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
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams
from pipecat.workers.runner import WorkerRunner

from kiki import tools, ui
from kiki.agent import DIDNT_CATCH, run_turn, warm_up
from kiki.db import connect
from kiki.events import current_state, record_turn, set_state

SAMPLE_RATE = 16000
WAKE_CHUNK_SAMPLES = 1280  # openWakeWord scores 80 ms chunks of 16 kHz int16
# 0.4, not openWakeWord's usual 0.5: a real "hey jarvis" climbed past 0.46 and only crossed
# 0.5 ~0.3 s later, delaying the chime. Background speech has scored at most 0.24 so far.
WAKE_THRESHOLD = float(os.environ.get("KIKI_WAKE_THRESHOLD", "0.4"))
NEAR_MISS_SCORE = (
    0.1  # wake scores between this and the threshold are logged as near-misses
)
WAKE_REFRACTORY_SECS = 2.0  # one "hey jarvis" scores high for several chunks
LISTEN_TIMEOUT_SECS = float(os.environ.get("KIKI_LISTEN_TIMEOUT_SECS", "6"))
# After each spoken reply, Kiki listens this long for a command without the wake word (ADR 0025).
FOLLOW_UP_SECS = float(os.environ.get("KIKI_FOLLOW_UP_SECS", "5"))
# The end of Kiki's own reply can still be in the room when playback ends; don't listen to it.
ECHO_GUARD_SECS = 0.3
# A command that ends with no words (a cough, noise after "hey jarvis") gets no transcript, so
# nothing would end its "thinking"; Whisper answers well within this.
NO_WORDS_SECS = 3.0
# A pause this long makes Smart Turn check whether the sentence sounds finished (ADR 0021).
PAUSE_SECS = float(os.environ.get("KIKI_PAUSE_SECS", "0.2"))
# Silence that ends a command even if it sounded unfinished (someone stopped mid-sentence).
MAX_PAUSE_SECS = float(os.environ.get("KIKI_MAX_PAUSE_SECS", "3"))
# After a pause sounds finished, wait this much longer for more words before closing. Covers
# the commas in a spoken list: "Add milk," sounds finished, but "two apples" follows (ADR 0023).
END_GRACE_SECS = float(os.environ.get("KIKI_END_GRACE_SECS", "0.4"))
# base.en takes 0.5 s per command vs 1.6 s for small.en; small.en is the fallback if it mishears.
WHISPER_MODEL = os.environ.get("KIKI_WHISPER_MODEL", "base.en")
# faster-whisper uses 4 CPU threads unless told otherwise; one per core of this laptop's 8 makes
# base.en about 0.15 s faster (0.37 s vs 0.52 s). More threads than cores is slower again.
WHISPER_THREADS = int(os.environ.get("KIKI_WHISPER_THREADS", "8"))
# Primes Whisper with list vocabulary and spoken quantities. Without it base.en hears "braid",
# "cut the eggs" and "milk to apples" (ADR 0019).
WHISPER_PROMPT = (
    "Grocery list. Add two apples, three milks, bread and eggs. Got the milk. "
    "Remove the eggs. What's on my list?"
)
PIPER_VOICE = os.environ.get("KIKI_PIPER_VOICE", "en_US-lessac-medium")


CHIME_RATE = 48000  # rendered at full quality; the speaker output resamples as needed
# Peak level, 0 to 1. 0.32 went unnoticed and 0.7 was too loud on the laptop speakers.
CHIME_VOLUME = float(os.environ.get("KIKI_CHIME_VOLUME", "0.45"))


def chime(notes: list[tuple[float, float, float]]) -> bytes:
    """A soft glass chime as 48 kHz int16 PCM. `notes` are (frequency Hz, start s, gain).

    Each note is a sine with gentle 2nd and 3rd harmonics (upper ones fade faster), a
    raised-cosine attack so there is no click, and a natural ring-out. Picked by ear by the
    owner from three styles (glass, marimba, bell).
    """
    partials = [(1, 1.0), (2, 0.22), (3, 0.06)]  # (frequency ratio, amplitude)
    decay, attack, tail = (
        0.3,
        0.006,
        1.1,
    )  # rings long enough to notice across a kitchen
    out = np.zeros(int(CHIME_RATE * (max(start for _, start, _ in notes) + tail)))
    for freq, start, gain in notes:
        i = int(CHIME_RATE * start)
        t = np.arange(len(out) - i) / CHIME_RATE
        rise = 0.5 - 0.5 * np.cos(np.pi * np.clip(t / attack, 0, 1))
        tone = sum(
            amp
            * np.sin(2 * np.pi * freq * ratio * t)
            * np.exp(-t / (decay / ratio**0.5))
            for ratio, amp in partials
        )
        out[i:] += gain * tone * rise * np.exp(-t / (decay * 3))
    fade = int(CHIME_RATE * 0.01)
    out[-fade:] *= np.linspace(1, 0, fade)  # end exactly at silence: no click
    out *= CHIME_VOLUME / np.max(np.abs(out))
    return (out * 32767).astype("<i2").tobytes()


# Rising fifth (C6 to G6): "I'm listening". There is no sound when listening stops: the
# owner found the falling chime unpleasant, and the reply (or silence) already says it.
LISTENING_CHIME = chime([(1046.5, 0.0, 1.0), (1568.0, 0.09, 0.85)])


def hey_jarvis_detector() -> Callable[[np.ndarray], float]:
    """openWakeWord's bundled "hey jarvis" model, as chunk -> score."""
    import openwakeword
    from openwakeword.model import Model

    path = Path(openwakeword.__file__).parent / "resources/models/hey_jarvis_v0.1.onnx"
    model = Model(wakeword_model_paths=[str(path)])
    return lambda chunk: max(model.predict(chunk).values())


class KeepSpeakerAwake(BaseAudioMixer):
    """Mixes nothing in; having a mixer makes Pipecat write silence to the speaker between sounds.

    Windows lets an audio output that gets no data fall asleep, and waking it loses the first
    ~0.7 s of the next sound. Measured on this laptop through the mic: "Milk is added to your
    list" played as "Your list." in 6 of 8 tries after a 5 to 10 s pause, and whole in 8 of 8
    with silence written through the pause.
    """

    async def start(self, sample_rate: int):
        pass

    async def stop(self):
        pass

    async def process_frame(self, frame):
        pass

    async def mix(self, audio: bytes) -> bytes:
        return audio


class Tab5Mic(BaseInputTransport):
    """The Tab5's mic in place of the laptop's (KIKI_MIC=tab5, FR-0.29, ADR 0029).

    Each UDP packet is 20 ms of 16 kHz mono int16, sent as the Tab5 records it. UDP, so there
    is no connection to set up again when either side restarts; a lost packet is 20 ms of
    silence to the wake word, which it shrugs off.
    ponytail: open to the home network with no password (ADR 0027).
    """

    def __init__(self, port: int):
        super().__init__(
            TransportParams(audio_in_enabled=True, audio_in_sample_rate=SAMPLE_RATE)
        )
        self._port = port
        self._packets: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self, frame):
        await super().start(frame)
        packets = self._packets

        class Receiver(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                packets.put_nowait(data)

        await asyncio.get_running_loop().create_datagram_endpoint(
            Receiver, local_addr=("0.0.0.0", self._port)
        )
        self.create_task(self._forward_packets_as_audio())
        await self.set_transport_ready(frame)
        print(f"Listening to the Tab5's mic on UDP port {self._port}")

    async def _forward_packets_as_audio(self):
        received, since = 0, time.monotonic()
        while True:
            audio = await self._packets.get()
            received += 1
            if time.monotonic() - since >= 10:  # 500 means none lost on the way
                logger.info(f"Kiki: Tab5 mic sent {received} packets in 10 s")
                received, since = 0, time.monotonic()
            await self.push_audio_frame(
                InputAudioRawFrame(audio=audio, sample_rate=SAMPLE_RATE, num_channels=1)
            )


class Tab5Speaker(BaseOutputTransport):
    """Kiki's chime and replies on the Tab5's speaker (KIKI_SPEAKER=tab5, FR-0.30, ADR 0029).

    The Tab5 connects to the port and is sent 16 kHz mono int16. Audio leaves at the pace it
    plays, kept LEAD_SECS ahead so a Wi-Fi hiccup doesn't run the Tab5 dry, and "Kiki stopped
    speaking" (and the follow-up window after it) still roughly matches what the room hears.
    With no Tab5 connected the audio is dropped.
    ponytail: open to the home network with no password (ADR 0027).
    """

    LEAD_SECS = 0.15

    def __init__(self, port: int):
        super().__init__(
            TransportParams(audio_out_enabled=True, audio_out_sample_rate=SAMPLE_RATE)
        )
        self._port = port
        self._writer: asyncio.StreamWriter | None = None
        self._played_by = 0.0  # when the Tab5 will have played everything sent so far

    async def start(self, frame):
        await super().start(frame)
        await asyncio.start_server(self._on_tab5_connected, "0.0.0.0", self._port)
        await self.set_transport_ready(frame)
        print(f"Speaking through the Tab5 on port {self._port}")

    async def _on_tab5_connected(self, reader, writer):
        if self._writer:  # the Tab5 restarted: the old connection is dead
            self._writer.close()
        self._writer = writer
        logger.info("Kiki: Tab5 speaker connected")

    async def write_audio_frame(self, frame) -> bool:
        if self._writer:
            try:
                self._writer.write(frame.audio)
                await self._writer.drain()
            except ConnectionError:
                logger.info("Kiki: Tab5 speaker disconnected")
                self._writer = None
        # Paced by the clock, not by sleeping one chunk per chunk: Windows oversleeps a 40 ms
        # sleep by several ms, so that fell behind real time and the Tab5 ran out mid-word.
        now = time.monotonic()
        self._played_by = (
            max(self._played_by, now) + len(frame.audio) / 2 / self.sample_rate
        )
        await asyncio.sleep(max(0.0, self._played_by - now - self.LEAD_SECS))
        return True


class WakeGate(FrameProcessor):
    """Drops mic audio unless Kiki is listening for a command (FR-0.11, FR-0.18, NFR-0.1).

    Kiki listens after the wake word, and silently for FOLLOW_UP_SECS after each spoken reply
    (ADR 0025). Each listening session lets one command through; it ends when
    EndOfTurnDetector says so (UserStoppedSpeakingFrame), not at the first pause. Saying the
    wake word while Kiki speaks interrupts the speech (FR-0.12).
    """

    def __init__(self, detect: Callable[[np.ndarray], float] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._detect = detect or hey_jarvis_detector()
        self._buffer = bytearray()
        self._last_wake = -WAKE_REFRACTORY_SECS
        self._best_miss = 0.0  # highest score of the current near-miss, for the log
        self._listening = False
        self.follow_up = (
            False  # this session opened after a reply, not on the wake word
        )
        self._heard_speech = False
        self._opens_at = 0.0
        self._gives_up_at = 0.0  # close if nobody has spoken by then
        self._bot_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            if self._heard_wake_word(frame.audio):
                await self._start_listening(LISTEN_TIMEOUT_SECS)
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
            score = self._detect(chunk)
            if score >= WAKE_THRESHOLD:
                now = time.monotonic()
                if now - self._last_wake > WAKE_REFRACTORY_SECS:
                    self._last_wake = now
                    heard = True
                    logger.info(f"Kiki: wake word heard (score {score:.2f})")
            self._log_near_miss(score)
        return heard

    def _log_near_miss(self, score: float):
        """Log attempts that scored some but not enough, to tune KIKI_WAKE_THRESHOLD."""
        if time.monotonic() - self._last_wake < WAKE_REFRACTORY_SECS:
            return  # the tail of a wake word that was heard, not a miss
        if NEAR_MISS_SCORE <= score < WAKE_THRESHOLD:
            self._best_miss = max(self._best_miss, score)
        elif score < NEAR_MISS_SCORE and self._best_miss:
            logger.info(
                f"Kiki: almost heard the wake word (score {self._best_miss:.2f}, "
                f"needs {WAKE_THRESHOLD:.2f})"
            )
            self._best_miss = 0.0

    async def _start_listening(self, timeout: float, follow_up: bool = False):
        if self._bot_speaking:
            await self.broadcast_interruption()
        opens_at = time.monotonic() + (ECHO_GUARD_SECS if follow_up else 0)
        self._listening = True
        self.follow_up = follow_up
        self._heard_speech = False
        self._opens_at = opens_at
        self._gives_up_at = opens_at + timeout
        set_state("listening")
        if (
            not follow_up
        ):  # a chime after every reply would get old fast; the orb shows it
            await self._play(LISTENING_CHIME)

    async def _stop_listening(self):
        self._listening = False
        set_state("thinking" if self._heard_speech else "idle")

    async def _play(self, pcm: bytes):
        await self.push_frame(
            OutputAudioRawFrame(audio=pcm, sample_rate=CHIME_RATE, num_channels=1)
        )


class EndOfTurnDetector(FrameProcessor):
    """Ends a spoken command when it sounds finished, not at the first pause (ADR 0021).

    VAD reports every pause longer than PAUSE_SECS. At each one, Smart Turn (a small local
    model that listens to intonation) judges whether the sentence is finished. If it sounds
    finished and nobody speaks for END_GRACE_SECS more, the command ends; speech in the grace
    period (a list comma) keeps the same command going (ADR 0023). Pauses that aren't the end
    are hidden from Whisper, so it transcribes the whole command once. After MAX_PAUSE_SECS of
    silence the command ends anyway.
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

    A follow-up (said in the window after a reply, `follow_up()` is true) that isn't a command
    gets no reply: it was probably a TV or people talking, and with no reply no new window
    opens (ADR 0025).
    """

    def __init__(
        self, conn, model=None, follow_up: Callable[[], bool] = lambda: False, **kwargs
    ):
        super().__init__(**kwargs)
        self._conn = conn
        self._model = model
        self._follow_up = follow_up
        self._speech_ended = time.monotonic()
        self._waiting_for_speech: tuple[dict, float] | None = None
        self._last_error = False
        self._no_words_check: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStoppedSpeakingFrame):  # one per command
            self._speech_ended = time.monotonic()
            self._no_words_check = self.create_task(self._idle_if_no_words())
        elif isinstance(frame, TranscriptionFrame) and frame.text.strip():
            if self._no_words_check:
                await self.cancel_task(self._no_words_check)
                self._no_words_check = None
            await self._answer(frame.text.strip())
            return
        elif isinstance(frame, BotStartedSpeakingFrame):
            set_state("speaking")
            if self._waiting_for_speech:
                self._log_turn(time.monotonic())
        elif isinstance(frame, BotStoppedSpeakingFrame):
            set_state("error" if self._last_error else "idle")
        await self.push_frame(frame, direction)

    async def _idle_if_no_words(self):
        await asyncio.sleep(NO_WORDS_SECS)
        self._no_words_check = None
        if current_state()["value"] == "thinking":
            set_state("idle")

    async def _answer(self, text: str):
        if (
            self._waiting_for_speech
        ):  # previous reply never started playing; log it anyway
            self._log_turn(None)
        stt_done = time.monotonic()
        turn = await asyncio.to_thread(run_turn, text, self._conn, self._model, "voice")
        turn["latency_ms"]["stt"] = round((stt_done - self._speech_ended) * 1000)
        if self._follow_up() and turn["said"] == DIDNT_CATCH:
            turn["said"] = ""  # logged as heard, never spoken
            set_state("idle")  # before the turn event, so the UI shows no check mark
            record_turn(turn, tools.read_list(self._conn)["items"])
            return
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
    from faster_whisper import WhisperModel
    from pipecat.services.piper.tts import PiperTTSService
    from pipecat.services.whisper.stt import WhisperSTTService

    class Whisper(WhisperSTTService):
        """Pipecat's Whisper service with faster-whisper's thread count, which it doesn't expose."""

        def _load(self):
            self._model = WhisperModel(
                self._settings.model,
                device=self._device,
                compute_type=self._compute_type,
                cpu_threads=WHISPER_THREADS,
            )

    gate = WakeGate()
    return [
        gate,
        VADProcessor(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=PAUSE_SECS))
        ),
        EndOfTurnDetector(),
        Whisper(
            settings=WhisperSTTService.Settings(
                model=WHISPER_MODEL, initial_prompt=WHISPER_PROMPT
            ),
            device="cpu",
            compute_type="int8",
        ),
        Brain(conn, model, follow_up=lambda: gate.follow_up),
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
    tab5_mic = os.environ.get("KIKI_MIC") == "tab5"
    tab5_speaker = os.environ.get("KIKI_SPEAKER") == "tab5"
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=not tab5_mic,
            audio_out_enabled=not tab5_speaker,
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_mixer=KeepSpeakerAwake(),
        )
    )
    mic = (
        Tab5Mic(int(os.environ.get("KIKI_MIC_PORT", "8768")))
        if tab5_mic
        else transport.input()
    )
    speaker = (
        Tab5Speaker(int(os.environ.get("KIKI_SPEAKER_PORT", "8769")))
        if tab5_speaker
        else transport.output()
    )
    pipeline = Pipeline([mic, *processors(conn), speaker])
    worker = PipelineWorker(
        pipeline,
        # The Tab5 plays 16 kHz. Piper then speaks at that rate directly and only the chime
        # is resampled: an output's resampler accepts a single input rate.
        params=PipelineParams(
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=SAMPLE_RATE if tab5_speaker else 24000,
        ),
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
