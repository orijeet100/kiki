"""Local UI (v0.4): one HTML page, live over Server-Sent Events, standard library only (ADR 0020).

`python -m kiki.ui` serves the page with a text box; `python -m kiki.voice` serves it too.
Bound to 127.0.0.1 only (NFR-0.6).
"""

import json
import os
import queue
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kiki import events, tools
from kiki.agent import run_turn, warm_up
from kiki.db import connect

HOST = "127.0.0.1"
PORT = int(os.environ.get("KIKI_UI_PORT", "8765"))
PAGE = (Path(__file__).parent / "ui.html").read_bytes()
MAX_COMMAND_CHARS = 200
KEEPALIVE_SECS = 15


def send_command(text: str, conn: sqlite3.Connection, model=None) -> None:
    """A typed command, same path as voice: state, turn, log, live events."""
    events.set_state("thinking")
    turn = run_turn(text, conn, model, source="text")
    events.record_turn(turn, tools.read_list(conn)["items"])
    events.set_state("error" if turn["error"] else "idle")


def make_handler(conn: sqlite3.Connection, model=None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal for Kiki's own output
            pass

        def _local_host(self) -> bool:
            # Blocks DNS rebinding: only accept requests addressed to this machine by name.
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            return host in {"127.0.0.1", "localhost"}

        def do_GET(self):
            if not self._local_host():
                return self.send_error(403)
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE)
            elif self.path == "/events":
                self._stream()
            else:
                self.send_error(404)

        def do_POST(self):
            if not self._local_host():
                return self.send_error(403)
            if self.path != "/command":
                return self.send_error(404)
            # A JSON content type can't be sent cross-site without a CORS preflight we never
            # answer, so other web pages can't post commands.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send_error(415)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                text = json.loads(self.rfile.read(length))["text"].strip()
            except (ValueError, KeyError, TypeError, AttributeError):
                return self.send_error(400)
            if not text or len(text) > MAX_COMMAND_CHARS:
                return self.send_error(400)
            threading.Thread(
                target=send_command, args=(text, conn, model), daemon=True
            ).start()
            self._send(202, "application/json", b'{"accepted": true}')

        def _send(self, status: int, content_type: str, body: bytes):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            subscription = events.subscribe()
            try:
                snapshot = {
                    "type": "snapshot",
                    "state": events.current_state()["value"],
                    "items": tools.read_list(conn)["items"],
                    "turns": events.recent_turns(),
                }
                self._write_event(snapshot)
                while True:
                    try:
                        self._write_event(subscription.get(timeout=KEEPALIVE_SECS))
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # browser tab closed
            finally:
                events.unsubscribe(subscription)

        def _write_event(self, event: dict):
            self.wfile.write(
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
            )
            self.wfile.flush()

    return Handler


class _Server(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second process bind a port that's already in use, so
    # two copies of Kiki would both run (and both answer every command). Without it, the
    # second copy fails to start. Elsewhere it only allows a quick restart after Ctrl+C.
    allow_reuse_address = sys.platform != "win32"


class AlreadyRunning(Exception):
    pass


def serve(
    conn: sqlite3.Connection, port: int = PORT, model=None
) -> ThreadingHTTPServer:
    """Start the UI server in a background thread and return it.

    Raises AlreadyRunning if the port is taken, which means another Kiki is running.
    """
    try:
        server = _Server((HOST, port), make_handler(conn, model))
    except OSError as e:
        raise AlreadyRunning(f"Kiki is already running (port {port} is in use).") from e
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def url(server: ThreadingHTTPServer) -> str:
    return f"http://{HOST}:{server.server_address[1]}"


def main() -> None:
    conn = connect()
    try:
        server = serve(conn)
    except AlreadyRunning as e:
        sys.exit(str(e))
    warm_up()
    print(f"Kiki UI: {url(server)}  (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
