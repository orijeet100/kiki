"""Kiki's own event shapes (ADR 0010). Schema: ARCHITECTURE.md#events."""

import json
import os
from pathlib import Path


def append_turn(turn: dict, path: str | None = None) -> None:
    """Append one `turn` event as one JSON line (NFR-0.4)."""
    p = Path(path or os.environ.get("KIKI_LOG", "logs/turns.jsonl"))
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")
