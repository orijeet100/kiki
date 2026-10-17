"""Grocery list tools. Plain functions, JSON-compatible in and out (ADR 0008)."""

import sqlite3
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize(name: str) -> str:
    """Matching key shared by singular and plural ("Eggs" and "egg" -> "egg").

    Not always a real word ("cookie" -> "cooky"); it only has to be the same for both forms.
    """
    # ponytail: suffix rules, no irregulars ("loaves"). Add cases here as odd words show up.
    n = " ".join(name.lower().split())
    if n.endswith("s") and not n.endswith(("ss", "us", "is")):
        n = n[:-1]
    if n.endswith("ie"):
        n = n[:-2] + "y"
    elif n.endswith(("oe", "che", "she", "xe", "sse")):
        n = n[:-1]
    return n


def add_items(conn: sqlite3.Connection, items: list[dict]) -> dict:
    added, already_present = [], []
    for item in items:
        name = item["name"].strip()
        quantity = int(item.get("quantity") or 1)
        row = conn.execute(
            "SELECT name FROM items WHERE normalized_name = ?", (normalize(name),)
        ).fetchone()
        if row:
            already_present.append(row["name"])
            continue
        now = _now()
        conn.execute(
            "INSERT INTO items (name, normalized_name, quantity, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, normalize(name), quantity, now, now),
        )
        added.append({"name": name, "quantity": quantity})
    conn.commit()
    return {"added": added, "already_present": already_present}


def set_quantity(conn: sqlite3.Connection, name: str, quantity: int) -> dict:
    if quantity < 1:
        return {"error": "quantity must be at least 1; use remove_items to delete"}
    cur = conn.execute(
        "UPDATE items SET quantity = ?, updated_at = ? WHERE normalized_name = ?",
        (quantity, _now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name, "quantity": quantity}


def remove_items(conn: sqlite3.Connection, names: list[str]) -> dict:
    removed, not_found = [], []
    for name in names:
        cur = conn.execute(
            "DELETE FROM items WHERE normalized_name = ?", (normalize(name),)
        )
        (removed if cur.rowcount else not_found).append(name)
    conn.commit()
    return {"removed": removed, "not_found": not_found}


def read_list(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT name, quantity FROM items ORDER BY created_at, id"
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


def clear_list(conn: sqlite3.Connection) -> dict:
    removed = read_list(conn)["items"]
    conn.execute("DELETE FROM items")
    conn.commit()
    return {"removed": removed}
