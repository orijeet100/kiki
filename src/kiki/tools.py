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
        "SELECT items.name, quantity, buying_pattern, status, products.name AS product_name"
        " FROM items LEFT JOIN products ON products.id = items.product_id"
        " WHERE buying_pattern = 'frequent' OR status = 'needed'"
        " ORDER BY status, created_at, items.id"  # 'needed' sorts before 'not_needed'
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


def read_all_items(conn: sqlite3.Connection) -> dict:
    """Every Item Kiki knows, for the screens (FR-0.41): the List first, then the rest by name.
    `on_list` says which part each is in."""
    others = conn.execute(
        "SELECT items.name, quantity, buying_pattern, status, products.name AS product_name"
        " FROM items LEFT JOIN products ON products.id = items.product_id"
        " WHERE buying_pattern = 'occasional' AND status = 'not_needed'"
        " ORDER BY lower(items.name)"
    ).fetchall()
    return {
        "items": [{**i, "on_list": True} for i in read_list(conn)["items"]]
        + [{**dict(r), "on_list": False} for r in others]
    }


def clear_all_items(conn: sqlite3.Connection) -> dict:
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


def reset_list(conn: sqlite3.Connection) -> dict:
    """Start the List over (FR-0.35): Frequent Items Needed at their Usual quantity,
    Occasional Items Not needed. Returns what is Needed now."""
    now = _now()
    conn.execute(
        "UPDATE items SET status = 'needed', quantity = usual_quantity, updated_at = ?"
        " WHERE buying_pattern = 'frequent'",
        (now,),
    )
    conn.execute(
        "UPDATE items SET status = 'not_needed', updated_at = ?"
        " WHERE buying_pattern = 'occasional' AND status = 'needed'",
        (now,),
    )
    conn.commit()
    needed = conn.execute(
        "SELECT name, quantity FROM items WHERE status = 'needed' ORDER BY created_at, id"
    )
    return {"needed": [dict(r) for r in needed]}


def known_order_ids(conn: sqlite3.Connection) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM orders")]


def save_order(conn: sqlite3.Connection, order: dict) -> dict:
    """One delivered Order and its lines; each line is the Product that was placed (FR-0.36).

    `order` is {id, delivered_at, lines: [{product_id, product_name, quantity, status}]}.
    """
    conn.execute(
        "INSERT OR IGNORE INTO orders (id, delivered_at) VALUES (?, ?)",
        (order["id"], order["delivered_at"]),
    )
    for line in order["lines"]:
        conn.execute(
            "INSERT INTO products (id, name) VALUES (?, ?)"
            " ON CONFLICT (id) DO UPDATE SET name = excluded.name",
            (line["product_id"], line["product_name"]),
        )
        conn.execute(
            "INSERT OR IGNORE INTO order_lines (order_id, product_id, quantity, status)"
            " VALUES (?, ?, ?, ?)",
            (order["id"], line["product_id"], line["quantity"], line["status"]),
        )
    conn.commit()
    return {"order_id": order["id"], "lines": len(order["lines"])}


def items_without_product(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM items WHERE product_id IS NULL ORDER BY created_at, id"
    )
    return [r["name"] for r in rows]


def placed_products(conn: sqlite3.Connection) -> list[dict]:
    """Every Product placed in a known Order, with how many Orders it was in."""
    rows = conn.execute(
        "SELECT products.id, products.name, COUNT(DISTINCT orders.id) AS orders,"
        " MAX(orders.delivered_at) AS last_ordered"
        " FROM order_lines JOIN products ON products.id = order_lines.product_id"
        " JOIN orders ON orders.id = order_lines.order_id"
        " GROUP BY products.id ORDER BY orders DESC, last_ordered DESC"
    )
    return [dict(r) for r in rows]


def preferred_product(conn: sqlite3.Connection, product_ids: list[int]) -> dict | None:
    """Of these Products, the one in the most Orders; a tie goes to the most recent (FR-0.37)."""
    if not product_ids:
        return None
    marks = ",".join("?" * len(product_ids))
    row = conn.execute(
        "SELECT products.id, products.name, COUNT(DISTINCT orders.id) AS orders,"
        " MAX(orders.delivered_at) AS last_ordered"
        " FROM products LEFT JOIN order_lines ON order_lines.product_id = products.id"
        " LEFT JOIN orders ON orders.id = order_lines.order_id"
        f" WHERE products.id IN ({marks})"
        " GROUP BY products.id ORDER BY orders DESC, last_ordered DESC LIMIT 1",
        product_ids,
    ).fetchone()
    return dict(row) if row else None


def set_product_for_item(
    conn: sqlite3.Connection, name: str, product_id: int, product_name: str
) -> dict:
    """The Product that goes in the Cart for this Item, until it is changed (FR-0.38)."""
    conn.execute(
        "INSERT INTO products (id, name) VALUES (?, ?)"
        " ON CONFLICT (id) DO UPDATE SET name = excluded.name",
        (product_id, product_name),
    )
    cur = conn.execute(
        "UPDATE items SET product_id = ?, updated_at = ? WHERE normalized_name = ?",
        (product_id, _now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name, "product_name": product_name}


def forget_product_for_item(conn: sqlite3.Connection, name: str) -> dict:
    """The Item has no Product again; the next Cart finds one for it (FR-0.38)."""
    cur = conn.execute(
        "UPDATE items SET product_id = NULL, updated_at = ? WHERE normalized_name = ?",
        (_now(), normalize(name)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return {"not_found": name}
    return {"name": name}


def cart_lines(conn: sqlite3.Connection) -> list[dict]:
    """The Needed Items with their quantity and Product, in List order."""
    rows = conn.execute(
        "SELECT items.name, quantity, product_id, products.name AS product_name"
        " FROM items LEFT JOIN products ON products.id = items.product_id"
        " WHERE status = 'needed' ORDER BY created_at, items.id"
    )
    return [dict(r) for r in rows]
