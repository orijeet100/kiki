import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    # Pydantic AI runs sync tools in worker threads; calls within a turn are sequential, so sharing is safe.
    conn = sqlite3.connect(
        path or os.environ.get("KIKI_DB", "kiki.db"), check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn
