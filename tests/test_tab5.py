"""The laptop's side of the Tab5 (v0.14): its mic, its speaker and its screen, over real sockets.

The Tab5 itself is checked by hand (ROADMAP, definition of done for v0.14); these tests stand in
for it with plain sockets.
"""

import asyncio
import socket
import struct
import threading
import time

import numpy as np
import pytest
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.tests.utils import SleepFrame, run_test
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from kiki import screen, tools, voice
from kiki.db import connect

RATE = voice.SAMPLE_RATE


def free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def send_as_the_tab5_mic(port: int, samples: np.ndarray, start_after: float):
    """Send audio the way the Tab5 does: one UDP packet per 20 ms, at real-time pace."""

    def send():
        time.sleep(start_after)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            step = RATE // 50
            for i in range(0, len(samples) - step + 1, step):
                udp.sendto(samples[i : i + step].tobytes(), ("127.0.0.1", port))
                time.sleep(0.02)

    thread = threading.Thread(target=send)
    thread.start()
    return thread


# --- mic (FR-0.29) ---------------------------------------------------------------------------


def test_fr_0_29_the_tab5_mic_packets_become_kikis_mic_audio():
    port = free_port(socket.SOCK_DGRAM)
    samples = (np.arange(RATE // 50 * 10) % 1000).astype(np.int16)  # ten 20 ms packets
    sender = send_as_the_tab5_mic(port, samples, start_after=0.5)
    down, _ = asyncio.run(
        run_test(
            Pipeline([voice.Tab5Mic(port)]), frames_to_send=[SleepFrame(sleep=1.5)]
        )
    )
    sender.join()
    audio = [f for f in down if isinstance(f, InputAudioRawFrame)]
    assert len(audio) == 10
    assert all(f.sample_rate == RATE and f.num_channels == 1 for f in audio)
    assert (
        b"".join(f.audio for f in audio) == samples.tobytes()
    )  # same bytes, same order


# --- speaker (FR-0.30) -----------------------------------------------------------------------


def listen_as_the_tab5_speaker(port: int, expected_bytes: int, arrivals: list):
    """Connect like the Tab5 and note when each piece of audio arrives."""

    def listen():
        for _ in range(100):
            try:
                link = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                time.sleep(0.02)
        received = b""
        with link:
            while len(received) < expected_bytes:
                data = link.recv(65536)
                if not data:
                    break
                received += data
                arrivals.append((time.monotonic(), received))

    thread = threading.Thread(target=listen)
    thread.start()
    return thread


def test_fr_0_30_the_tab5_speaker_gets_the_audio_at_the_pace_it_plays():
    port = free_port()
    one_second = (np.arange(RATE) % 2000 - 1000).astype(np.int16).tobytes()
    chunk = len(one_second) // 25  # 40 ms, the size the output sends audio in
    frames = [
        OutputAudioRawFrame(
            audio=one_second[i : i + chunk], sample_rate=RATE, num_channels=1
        )
        for i in range(0, len(one_second), chunk)
    ]
    arrivals = []
    listener = listen_as_the_tab5_speaker(port, len(one_second), arrivals)
    asyncio.run(
        run_test(
            Pipeline([voice.Tab5Speaker(port)]),
            # Time for the stand-in Tab5 to connect: audio sent before that is dropped.
            frames_to_send=[SleepFrame(sleep=2), *frames, SleepFrame(sleep=1.5)],
        )
    )
    listener.join()
    assert arrivals[-1][1][: len(one_second)] == one_second  # all of it, in order
    # Not dumped at once, not falling behind: one second of audio arrives over about 0.85 s,
    # since it is kept LEAD_SECS (0.15 s) ahead of the Tab5's playback.
    spread = arrivals[-1][0] - arrivals[0][0]
    assert 0.6 < spread < 1.0, spread


# --- screen (FR-0.31, FR-0.32) ---------------------------------------------------------------


class RecordingStreamer(screen.PageStreamer):
    """A PageStreamer with no Chrome: DevTools commands are recorded instead of sent."""

    def __init__(self):
        super().__init__()
        self.devtools_calls = []

    async def send_devtools(self, method, **params):
        self.devtools_calls.append((method, params))


async def read_frame(reader) -> bytes:
    (length,) = struct.unpack(">I", await reader.readexactly(4))
    return await reader.readexactly(length)


def test_fr_0_31_the_tab5_gets_the_newest_frame_and_its_touches_reach_the_page():
    async def scenario():
        streamer = RecordingStreamer()
        streamer.latest_frame = b"first"
        server = await asyncio.start_server(streamer.serve_tab5, "127.0.0.1", 0)
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", server.sockets[0].getsockname()[1]
        )
        assert (
            await read_frame(reader) == b"first"
        )  # a new connection gets the page at once

        # Two repaints before the Tab5 has shown the first: only the newest is sent.
        for frame in (b"second", b"third"):
            streamer.latest_frame = frame
            streamer.new_frame.set()
        await asyncio.sleep(0.1)
        writer.write(b"shown\n")
        assert await read_frame(reader) == b"third"

        writer.write(b"down 120 640\nmove 121 650\nup 121 650\n")
        await writer.drain()
        await asyncio.sleep(0.1)
        writer.close()
        server.close()
        return streamer.devtools_calls

    calls = asyncio.run(scenario())
    assert calls == [
        (
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": 120, "y": 640}]},
        ),
        (
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": 121, "y": 650}]},
        ),
        ("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}),
    ]


def test_fr_0_32_the_page_for_the_tab5_gets_its_keyboard_before_it_loads():
    streamer = RecordingStreamer()
    asyncio.run(streamer.prepare_page())
    methods = [method for method, _ in streamer.devtools_calls]
    # Chrome ignores a script for new documents unless the Page domain is enabled first.
    assert (
        methods.index("Page.enable")
        < methods.index("Page.addScriptToEvaluateOnNewDocument")
        < methods.index("Page.navigate")
    )
    script = dict(streamer.devtools_calls)["Page.addScriptToEvaluateOnNewDocument"]
    assert script["source"] == screen.KEYBOARD_SCRIPT and "kiki-kb" in script["source"]
    size = dict(streamer.devtools_calls)["Emulation.setDeviceMetricsOverride"]
    assert (size["width"], size["height"]) == (720, 1200)  # above the Tab5's volume bar


# --- audio stays at home (NFR-0.8) -----------------------------------------------------------


@pytest.mark.voice
def test_nfr_0_8_speech_from_the_tab5_reaches_the_model_only_as_text(
    tmp_path, speak, monkeypatch
):
    monkeypatch.setenv("KIKI_LOG", str(tmp_path / "turns.jsonl"))
    heard = []

    def model_fn(messages, info):
        heard.append(messages[0].parts[0].content)
        args = {"add": [{"name": "bread"}], "reply": "Added bread."}
        return ModelResponse(parts=[ToolCallPart("update_list", args)])

    speech = np.concatenate(
        [
            np.zeros(RATE // 2, np.int16),
            speak("Hey Jarvis.").astype(np.int16),
            np.zeros(RATE * 3 // 10, np.int16),
            speak("Add bread.").astype(np.int16),
            np.zeros(RATE * 4, np.int16),
        ]
    ).astype(np.int16)
    port = free_port(socket.SOCK_DGRAM)
    conn = connect(str(tmp_path / "tab5.db"))
    pipeline = Pipeline(
        [voice.Tab5Mic(port), *voice.processors(conn, FunctionModel(model_fn))]
    )
    sender = send_as_the_tab5_mic(port, speech, start_after=1.0)
    asyncio.run(
        run_test(pipeline, frames_to_send=[SleepFrame(sleep=len(speech) / RATE + 3)])
    )
    sender.join()
    assert len(heard) == 1 and isinstance(heard[0], str), (
        heard
    )  # a transcript, never audio
    assert "bread" in heard[0].lower(), heard
    assert [i["name"] for i in tools.read_list(conn)["items"]] == ["bread"]
