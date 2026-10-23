import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    buying_pattern TEXT NOT NULL DEFAULT 'occasional'
        CHECK (buying_pattern IN ('frequent', 'occasional')),
    status TEXT NOT NULL DEFAULT 'needed' CHECK (status IN ('needed', 'not_needed')),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    usual_quantity INTEGER NOT NULL DEFAULT 1 CHECK (usual_quantity >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    product_id INTEGER REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,  -- the Store's own product id: /store/<store>/products/<id>
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,  -- the Store's order id
    delivered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_lines (
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),  -- what was placed, never the substitute
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('found', 'substituted', 'missing')),
    PRIMARY KEY (order_id, product_id)
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    # Pydantic AI runs sync tools in worker threads; calls within a turn are sequential, so sharing is safe.
    conn = sqlite3.connect(
        path or os.environ.get("KIKI_DB", "kiki.db"), check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    if columns and "buying_pattern" not in columns:
        # A pre-v0.12 file: keep its rows aside and start an empty List (ADR 0026).
        conn.execute("ALTER TABLE items RENAME TO items_before_v0_12")
        columns = set()
    if columns and "product_id" not in columns:
        # A v0.12 to v0.16 file: the List stays, its Items have no Product yet (ADR 0035).
        conn.execute(
            "ALTER TABLE items ADD COLUMN product_id INTEGER REFERENCES products(id)"
        )
    conn.executescript(SCHEMA)
    return conn
