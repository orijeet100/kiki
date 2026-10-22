"""Kiki's own UI page on the Tab5 (v0.14, ADR 0028).

A headless Chrome renders the UI page at the Tab5's size and sends a JPEG each time the page
repaints (the DevTools screencast). The Tab5 connects to KIKI_SCREEN_PORT and is sent the newest
frame whenever it has shown the last one; its touches come back as lines ("down 120 640",
"move ...", "up ...") and are replayed in the page as touch events (FR-0.31). The page streamed
to the Tab5 also gets an on-screen keyboard, since a headless browser has none (FR-0.32).

Run next to Kiki, once its UI is up: `python -m kiki.screen`.
"""

import asyncio
import base64
import json
import os
import struct
import tempfile
import urllib.request
from pathlib import Path

import websockets  # the DevTools protocol is a WebSocket; already installed with Pipecat

CHROME = os.environ.get(
    "KIKI_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)
PAGE_URL = f"http://127.0.0.1:{os.environ.get('KIKI_UI_PORT', '8765')}/"
# ponytail: open to the home network with no password, like KIKI_UI_HOST (ADR 0027).
PORT = int(os.environ.get("KIKI_SCREEN_PORT", "8767"))
DEVTOOLS_PORT = 9223
# The Tab5 in portrait (its panel's own orientation), less the 80 px volume bar it draws itself.
PAGE_WIDTH, PAGE_HEIGHT = 720, 1200
JPEG_QUALITY = int(os.environ.get("KIKI_SCREEN_QUALITY", "70"))
KEYBOARD_SCRIPT = (Path(__file__).parent / "screen_keyboard.js").read_text(
    encoding="utf-8"
)
TOUCH_EVENTS = {"down": "touchStart", "move": "touchMove", "up": "touchEnd"}


def list_devtools_pages() -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{DEVTOOLS_PORT}/json/list") as r:
        return json.load(r)


class PageStreamer:
    """Holds the newest frame of the page and passes the Tab5's touches back to it."""

    def __init__(self):
        self.latest_frame = b""
        self.new_frame = asyncio.Event()
        self._devtools = None  # the WebSocket to the page, once Chrome is up
        self._next_id = 0

    async def send_devtools(self, method: str, **params):
        self._next_id += 1
        await self._devtools.send(
            json.dumps({"id": self._next_id, "method": method, "params": params})
        )

    async def prepare_page(self):
        """Size the page like the Tab5, make it take touches, add the keyboard, load the UI."""
        await self.send_devtools(
            "Emulation.setDeviceMetricsOverride",
            width=PAGE_WIDTH,
            height=PAGE_HEIGHT,
            deviceScaleFactor=1,
            mobile=True,
        )
        await self.send_devtools(
            "Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=1
        )
        # Chrome only runs scripts added for new documents once the Page domain is enabled.
        await self.send_devtools("Page.enable")
        await self.send_devtools(
            "Page.addScriptToEvaluateOnNewDocument", source=KEYBOARD_SCRIPT
        )
        await self.send_devtools("Page.navigate", url=PAGE_URL)
        await self.send_devtools(
            "Page.startScreencast",
            format="jpeg",
            quality=JPEG_QUALITY,
            maxWidth=PAGE_WIDTH,
            maxHeight=PAGE_HEIGHT,
        )

    async def stream_page(self):
        """Attach to Chrome's page, set it up, then keep the newest screencast frame."""
        page = None
        while not page:
            await asyncio.sleep(0.3)
            try:
                pages = await asyncio.to_thread(list_devtools_pages)
                page = next((p for p in pages if p["type"] == "page"), None)
            except OSError:
                pass  # Chrome still starting
        async with websockets.connect(
            page["webSocketDebuggerUrl"], max_size=None
        ) as devtools:
            self._devtools = devtools
            await self.prepare_page()
            async for message in devtools:
                event = json.loads(message)
                if event.get("method") == "Page.screencastFrame":
                    self.latest_frame = base64.b64decode(event["params"]["data"])
                    self.new_frame.set()
                    await self.send_devtools(
                        "Page.screencastFrameAck",
                        sessionId=event["params"]["sessionId"],
                    )

    async def serve_tab5(self, reader, writer):
        """One Tab5 connection: frames out, "shown" and touches in."""
        print("Tab5 connected", writer.get_extra_info("peername"))
        shown = asyncio.Event()
        shown.set()

        async def send_newest_frames():
            # Only the newest frame goes out, once the Tab5 has shown the last one: a slow
            # link skips frames instead of falling behind.
            if self.latest_frame:
                self.new_frame.set()
            while True:
                await self.new_frame.wait()
                await shown.wait()
                self.new_frame.clear()
                shown.clear()
                frame = self.latest_frame
                writer.write(struct.pack(">I", len(frame)) + frame)
                await writer.drain()

        sender = asyncio.create_task(send_newest_frames())
        try:
            async for line in reader:
                kind, *xy = line.decode().split()
                if kind == "shown":
                    shown.set()
                elif kind in TOUCH_EVENTS:
                    x, y = map(int, xy)
                    points = [] if kind == "up" else [{"x": x, "y": y}]
                    await self.send_devtools(
                        "Input.dispatchTouchEvent",
                        type=TOUCH_EVENTS[kind],
                        touchPoints=points,
                    )
        except (ConnectionError, ValueError):
            pass
        finally:
            sender.cancel()
            writer.close()
            print("Tab5 disconnected")


async def run():
    chrome = await asyncio.create_subprocess_exec(
        CHROME,
        "--headless=new",
        f"--remote-debugging-port={DEVTOOLS_PORT}",
        f"--user-data-dir={tempfile.mkdtemp(prefix='kiki-screen-')}",
        f"--window-size={PAGE_WIDTH},{PAGE_HEIGHT}",
        "--hide-scrollbars",
        "--mute-audio",
        "about:blank",
    )
    streamer = PageStreamer()
    server = await asyncio.start_server(streamer.serve_tab5, "0.0.0.0", PORT)
    print(f"Streaming {PAGE_URL} to the Tab5 on port {PORT}  (Ctrl+C to stop)")
    try:
        async with server:
            await asyncio.gather(streamer.stream_page(), server.serve_forever())
    finally:
        chrome.terminate()


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
