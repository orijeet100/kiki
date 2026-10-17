"""Kiki's own events (ADR 0010). Schema: ARCHITECTURE.md#events.

`append_turn` writes the turn log. `publish` fans events out to live subscribers (the UI).
"""

import json
import os
import queue
import threading
from collections import deque
from pathlib import Path

_subscribers: set[queue.SimpleQueue] = set()
_lock = threading.Lock()
_state = {"type": "state", "value": "idle"}


def log_path(path: str | None = None) -> Path:
    return Path(path or os.environ.get("KIKI_LOG", "logs/turns.jsonl"))


def append_turn(turn: dict, path: str | None = None) -> None:
    """Append one `turn` event as one JSON line (NFR-0.4)."""
    p = log_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")


def recent_turns(limit: int = 50, path: str | None = None) -> list[dict]:
    """The last `limit` turns from the log, oldest first."""
    p = log_path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [json.loads(line) for line in deque(f, maxlen=limit)]


def publish(event: dict) -> None:
    """Send an event to every live subscriber. Thread-safe; never blocks."""
    global _state
    with _lock:
        if event["type"] == "state":
            _state = event
        for q in _subscribers:
            q.put(event)


def set_state(value: str) -> None:
    """idle | listening | thinking | speaking | error"""
    publish({"type": "state", "value": value})


def current_state() -> dict:
    return _state


def subscribe() -> queue.SimpleQueue:
    q = queue.SimpleQueue()
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: queue.SimpleQueue) -> None:
    with _lock:
        _subscribers.discard(q)


def record_turn(turn: dict, items: list[dict]) -> None:
    """After every turn: log it, then tell live subscribers about the turn and the new list."""
    append_turn(turn)
    publish(turn)
    publish({"type": "list", "items": items})
