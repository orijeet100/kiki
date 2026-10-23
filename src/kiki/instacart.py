"""Kiki's side of the Instacart extension (ADR 0034): hand it one job, wait for its answer.

Kiki opens a tab in the owner's own Chrome at an Instacart page ending in
`#kiki-<job id>-<port>`.
The extension (browser/instacart) sees that tab, fetches the job from GET /instacart/job,
does it in that tab, posts POST /instacart/result and closes the tab. No other tab is touched.
"""

import os
import secrets
import subprocess
import threading

from kiki import events

CHROME = os.environ.get(
    "KIKI_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)
PORT = int(os.environ.get("KIKI_UI_PORT", "8765"))  # where the extension finds Kiki
STORE = os.environ.get("KIKI_STORE", "wegmans")
ADDRESS = os.environ.get("KIKI_ADDRESS", "30 River Court")
# Reading 10 Orders or filling 20 Items takes about two minutes; this only catches a dead job.
TIMEOUT_SECS = 300


class InstacartError(Exception):
    """A job that couldn't finish. `code` is the extension's short reason (`signed_out`, ...)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_jobs = threading.Lock()  # one job at a time: there is one Kiki tab
_state = threading.Lock()
_job: dict | None = None
_result: dict | None = None
_done = threading.Event()


def run_job(kind: str, **payload) -> dict:
    """Run one extension job and return its data; raise InstacartError if it failed."""
    global _job, _result
    with _jobs:
        job = {"id": secrets.token_hex(4), "kind": kind, "store": STORE, **payload}
        with _state:
            _job, _result = job, None
            _done.clear()
        try:
            open_tab(
                f"https://www.instacart.com/store/account/orders#kiki-{job['id']}-{PORT}"
            )
        except OSError:
            raise InstacartError("no_chrome") from None
        answered = _done.wait(TIMEOUT_SECS)
        with _state:
            result, _job = _result, None
    if not answered:
        raise InstacartError(
            "no_answer"
        )  # the extension isn't loaded, or Chrome is stuck
    if not result["ok"]:
        raise InstacartError(result["error"])
    return result["data"]


def open_tab(url: str) -> None:
    # Chrome opens the URL as a new tab in the running browser, or starts it signed in.
    subprocess.Popen([CHROME, url])


def current_job() -> dict | None:
    """GET /instacart/job: the job waiting for the extension, if any."""
    with _state:
        return _job


def finish(result: dict) -> bool:
    """POST /instacart/result: the extension's answer. False if it isn't for the current job."""
    global _result
    with _state:
        if not _job or result.get("id") != _job["id"]:
            return False
        _result = result
    _done.set()
    return True


def progress(update: dict) -> None:
    """POST /instacart/progress: "Filling cart, 4 of 12" on the screens."""
    with _state:
        if not _job or update.get("id") != _job["id"]:
            return
    done, total = update.get("done"), update.get("total")
    if isinstance(done, int) and isinstance(total, int):
        events.publish(
            {"type": "progress", "text": f"Filling cart, {done + 1} of {total}"}
        )
