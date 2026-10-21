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
    """New names become Occasional and Needed; a Not needed Item becomes Needed (FR-0.20)."""
    added, already_present = [], []
    for item in items:
        name = item["name"].strip()
        row = conn.execute(
            "SELECT name, status, usual_quantity FROM items WHERE normalized_name = ?",
            (normalize(name),),
        ).fetchone()
        if row and row["status"] == "needed":
            already_present.append(row["name"])
            continue
        quantity = int(item.get("quantity") or (row["usual_quantity"] if row else 1))
        now = _now()
        if row:
            conn.execute(
                "UPDATE items SET status = 'needed', quantity = ?, updated_at = ?"
                " WHERE normalized_name = ?",
                (quantity, now, normalize(name)),
            )
            name = row["name"]
        else:
            conn.execute(
                "INSERT INTO items (name, normalized_name, quantity, usual_quantity,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, normalize(name), quantity, quantity, now, now),
            )
        added.append({"name": name, "quantity": quantity})
    conn.commit()
    return {"added": added, "already_present": already_present}


def set_quantity(conn: sqlite3.Connection, name: str, quantity: int) -> dict:
    """The next Order's quantity; saying a number also makes the Item Needed (FR-0.22)."""
    if quantity < 1:
        return {"error": "quantity must be at least 1; use remove_items instead"}
    cur = conn.execute(
        "UPDATE items SET quantity = ?, status = 'needed', updated_at = ?"
        " WHERE normalized_name = ?",
        (quantity, _now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name, "quantity": quantity}


def set_usual_quantity(conn: sqlite3.Connection, name: str, quantity: int) -> dict:
    """The Usual quantity, and the next Order's quantity with it (FR-0.22)."""
    if quantity < 1:
        return {"error": "quantity must be at least 1"}
    cur = conn.execute(
        "UPDATE items SET usual_quantity = ?, quantity = ?, updated_at = ?"
        " WHERE normalized_name = ?",
        (quantity, quantity, _now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name, "usual_quantity": quantity}


def set_buying_pattern(
    conn: sqlite3.Connection, name: str, buying_pattern: str
) -> dict:
    """Frequent or Occasional (FR-0.23)."""
    if buying_pattern not in ("frequent", "occasional"):
        return {"error": "buying_pattern is frequent or occasional"}
    cur = conn.execute(
        "UPDATE items SET buying_pattern = ?, updated_at = ? WHERE normalized_name = ?",
        (buying_pattern, _now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name, "buying_pattern": buying_pattern}


def rename_item(conn: sqlite3.Connection, name: str, new_name: str) -> dict:
    """A new name for the same Item; everything else stays (FR-0.24)."""
    new_name = new_name.strip()
    taken = conn.execute(
        "SELECT name FROM items WHERE normalized_name = ? AND normalized_name != ?",
        (normalize(new_name), normalize(name)),
    ).fetchone()
    if taken:
        return {"error": f"{taken['name']} is already an item"}
    cur = conn.execute(
        "UPDATE items SET name = ?, normalized_name = ?, updated_at = ?"
        " WHERE normalized_name = ?",
        (new_name, normalize(new_name), _now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name, "new_name": new_name}


def remove_items(conn: sqlite3.Connection, names: list[str]) -> dict:
    """Not needed, whatever the quantity; nothing is deleted (FR-0.21, ADR 0026)."""
    removed, not_found = [], []
    for name in names:
        cur = conn.execute(
            "UPDATE items SET status = 'not_needed', updated_at = ?"
            " WHERE normalized_name = ? AND status = 'needed'",
            (_now(), normalize(name)),
        )
        (removed if cur.rowcount else not_found).append(name)
    conn.commit()
    return {"removed": removed, "not_found": not_found}


def read_list(conn: sqlite3.Connection) -> dict:
    """The List: every Frequent Item plus the Needed Occasional ones, Needed first (FR-0.19)."""
    rows = conn.execute(
        "SELECT name, quantity, buying_pattern, status FROM items"
        " WHERE buying_pattern = 'frequent' OR status = 'needed'"
        " ORDER BY status, created_at, id"  # 'needed' sorts before 'not_needed'
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


def clear_list(conn: sqlite3.Connection) -> dict:
    """Every Item Not needed; returns the ones that were Needed (FR-0.26)."""
    removed = [
        dict(r)
        for r in conn.execute(
            "SELECT name, quantity FROM items WHERE status = 'needed'"
            " ORDER BY created_at, id"
        )
    ]
    conn.execute(
        "UPDATE items SET status = 'not_needed', updated_at = ? WHERE status = 'needed'",
        (_now(),),
    )
    conn.commit()
    return {"removed": removed}
