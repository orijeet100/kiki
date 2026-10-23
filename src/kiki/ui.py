"""Local UI (v0.4): one HTML page plus the vendored orb script, live over Server-Sent Events,
standard library only (ADR 0020, ADR 0024).

`python -m kiki.ui` serves the page with a text box; `python -m kiki.voice` serves it too.
Bound to 127.0.0.1 unless KIKI_UI_HOST opens it to the home network for the Tab5 (NFR-0.7).
"""

import ipaddress
import json
import os
import queue
import secrets
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kiki import events, instacart, tools
from kiki.agent import run_turn, turn_lock, warm_up
from kiki.db import connect

# KIKI_UI_HOST=0.0.0.0 lets the Tab5 reach the UI over the home network (ADR 0027).
# ponytail: no password on it yet; add a shared secret before Kiki runs unattended.
HOST = os.environ.get("KIKI_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("KIKI_UI_PORT", "8765"))
PAGE = (Path(__file__).parent / "ui.html").read_bytes()
ORB = (Path(__file__).parent / "speaking-orb.js").read_bytes()  # ADR 0024
MAX_COMMAND_CHARS = 200
KEEPALIVE_SECS = 15
# The extension's answers; GET /instacart/job is in do_GET (ADR 0034).
INSTACART_POSTS = {
    "/instacart/result": instacart.finish,
    "/instacart/progress": instacart.progress,
}


def send_command(text: str, conn: sqlite3.Connection, model=None) -> None:
    """A typed command, same path as voice: state, turn, log, live events."""
    events.set_state("thinking")
    turn = run_turn(text, conn, model, source="text")
    events.record_turn(turn, tools.read_list(conn)["items"])
    events.set_state("error" if turn["error"] else "idle")


def item_change(body: dict) -> tuple[str, bool | int | str] | None:
    """The one change a POST /item asks for: needed, quantity, buying_pattern or new_name; None
    if malformed."""
    keys = ("needed", "quantity", "buying_pattern", "new_name", "forget_product")
    changes = [key for key in keys if key in body]
    if len(changes) != 1:
        return None
    key, value = changes[0], body[changes[0]]
    if key == "needed" and isinstance(value, bool):
        return key, value
    if key == "quantity" and type(value) is int and 1 <= value <= 99:
        return key, value
    if key == "buying_pattern" and value in ("frequent", "occasional"):
        return key, value
    if key == "forget_product" and value is True:
        return key, value
    if (
        key == "new_name"
        and isinstance(value, str)
        and 0 < len(value.strip()) <= MAX_COMMAND_CHARS
    ):
        return key, value.strip()
    return None


def edit_item(name: str, change: tuple, conn: sqlite3.Connection) -> tuple[int, dict]:
    """A click or an edit on the list (FR-0.27, FR-0.33): the same tools as speaking, no model.

    Returns the HTTP status with the tool's result: 409 when the tool refuses (a name that's
    taken), 404 when there's no such Item to change.
    """
    key, value = change
    with turn_lock:
        if key == "needed" and value:
            result = tools.add_items(conn, [{"name": name}])
        elif key == "needed":
            result = tools.remove_items(conn, [name])
        elif key == "quantity":
            result = tools.set_quantity(conn, name, value)
        elif key == "buying_pattern":
            result = tools.set_buying_pattern(conn, name, value)
        elif key == "forget_product":
            result = tools.forget_product_for_item(conn, name)
        else:
            result = tools.rename_item(conn, name, value)
        items = tools.read_list(conn)["items"]
    events.publish({"type": "list", "items": items})
    if "error" in result:
        return 409, result
    if key != "needed" and "not_found" in result:  # remove_items always lists not_found
        return 404, result
    return 200, result


def reset(conn: sqlite3.Connection) -> dict:
    """The Reset button (FR-0.35): start the List over, logged as a turn so History shows
    what it did and the log keeps the List as it was."""
    with turn_lock:
        before = tools.read_list(conn)["items"]
        result = tools.reset_list(conn)
        items = tools.read_list(conn)["items"]
    now = datetime.now(UTC)
    turn = {
        "type": "turn",
        "id": f"t_{now:%Y%m%dT%H%M%S}_{secrets.token_hex(2)}",
        "ts": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "button",
        "heard": "Reset",
        "tool_calls": [
            {"name": "reset_list", "args": {"before": before}, "result": result}
        ],
        "said": "",
        "model": None,
        "latency_ms": {"stt": None, "llm": 0, "tts": None, "total": 0},
        "error": None,
    }
    events.record_turn(turn, items)
    return result


def make_handler(conn: sqlite3.Connection, model=None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal for Kiki's own output
            pass

        def _host_is_allowed(self) -> bool:
            # Blocks DNS rebinding: a request must be addressed to "localhost" or to an IP
            # address (the Tab5 uses the laptop's), never to some other site's host name.
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            if host == "localhost":
                return True
            try:
                ipaddress.ip_address(host)
                return True
            except ValueError:
                return False

        def do_GET(self):
            if not self._host_is_allowed():
                return self.send_error(403)
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE)
            elif self.path == "/speaking-orb.js":
                self._send(200, "text/javascript; charset=utf-8", ORB)
            elif self.path == "/events":
                self._stream()
            elif (
                self.path == "/instacart/job"
            ):  # the extension asks for its job (ADR 0034)
                job = instacart.current_job()
                if job is None:
                    return self._send(204, "application/json", b"")
                self._send(200, "application/json", json.dumps(job).encode())
            else:
                self.send_error(404)

        def do_POST(self):
            if not self._host_is_allowed():
                return self.send_error(403)
            if self.path not in ("/command", "/item", "/reset", *INSTACART_POSTS):
                return self.send_error(404)
            # A JSON content type can't be sent cross-site without a CORS preflight we never
            # answer, so other web pages can't post commands.
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send_error(415)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length))
                if self.path in INSTACART_POSTS:
                    INSTACART_POSTS[self.path](body)
                    return self._send(200, "application/json", b"{}")
                if self.path == "/reset":
                    return self._send(
                        200, "application/json", json.dumps(reset(conn)).encode()
                    )
                text = body["text" if self.path == "/command" else "name"].strip()
            except (ValueError, KeyError, TypeError, AttributeError):
                return self.send_error(400)
            if not text or len(text) > MAX_COMMAND_CHARS:
                return self.send_error(400)
            if self.path == "/item":
                change = item_change(body)
                if change is None:
                    return self.send_error(400)
                status, result = edit_item(text, change, conn)
                return self._send(
                    status, "application/json", json.dumps(result).encode()
                )
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
