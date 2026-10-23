import sqlite3

import pytest

from kiki import tools
from kiki.db import connect


@pytest.fixture
def conn(tmp_path):
    return connect(str(tmp_path / "test.db"))


def names(conn):
    return {i["name"]: i["quantity"] for i in tools.read_list(conn)["items"]}


def test_fr_0_1_add_many_with_quantities(conn):
    result = tools.add_items(
        conn, [{"name": "milk"}, {"name": "apples", "quantity": 2}, {"name": "rice"}]
    )
    assert len(result["added"]) == 3
    assert names(conn) == {"milk": 1, "apples": 2, "rice": 1}


def test_fr_0_2_duplicate_add_keeps_quantity(conn):
    tools.add_items(conn, [{"name": "bread"}])
    result = tools.add_items(conn, [{"name": "bread", "quantity": 3}])
    assert result == {"added": [], "already_present": ["bread"]}
    assert names(conn) == {"bread": 1}


def test_fr_0_3_set_quantity(conn):
    tools.add_items(conn, [{"name": "milk"}])
    assert tools.set_quantity(conn, "milks", 3) == {"name": "milks", "quantity": 3}
    assert names(conn) == {"milk": 3}
    assert tools.set_quantity(conn, "bananas", 2) == {"not_found": "bananas"}
    assert "error" in tools.set_quantity(conn, "milk", 0)


@pytest.mark.parametrize(
    "singular, plural",
    [
        ("egg", "eggs"),
        ("cookie", "cookies"),
        ("berry", "berries"),
        ("tomato", "tomatoes"),
        ("peach", "peaches"),
        ("box", "boxes"),
        ("glass", "glasses"),
        ("apple", "apples"),
        ("Green Onion", "green  onions"),
    ],
)
def test_fr_0_4_singular_and_plural_match(singular, plural):
    assert tools.normalize(singular) == tools.normalize(plural)


def test_fr_0_4_words_ending_in_s_survive():
    assert tools.normalize("hummus") == "hummus"
    assert tools.normalize("glass") == "glass"


def test_fr_0_4_duplicate_across_plural(conn):
    tools.add_items(conn, [{"name": "eggs"}])
    assert tools.add_items(conn, [{"name": "egg"}])["already_present"] == ["eggs"]


def row(conn, name):
    return dict(
        conn.execute(
            "SELECT name, buying_pattern, status, quantity, usual_quantity FROM items"
            " WHERE normalized_name = ?",
            (tools.normalize(name),),
        ).fetchone()
    )


def test_fr_0_19_list_is_frequent_items_plus_needed_ones_needed_first(conn):
    tools.add_items(conn, [{"name": f"item{i}"} for i in range(4)])
    tools.set_buying_pattern(conn, "item0", "frequent")
    tools.remove_items(conn, ["item0", "item1"])
    assert [(i["name"], i["status"]) for i in tools.read_list(conn)["items"]] == [
        ("item2", "needed"),
        ("item3", "needed"),
        ("item0", "not_needed"),
    ]


def test_fr_0_19_a_list_file_from_before_v0_12_starts_empty(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, normalized_name TEXT UNIQUE,"
        " quantity INTEGER, created_at TEXT, updated_at TEXT)"
    )
    old.execute("INSERT INTO items VALUES (1, 'milk', 'milk', 2, '', '')")
    old.commit()
    old.close()
    conn = connect(path)
    assert tools.read_list(conn) == {"items": []}
    assert (
        conn.execute("SELECT name FROM items_before_v0_12").fetchall()[0][0] == "milk"
    )


def test_fr_0_20_new_is_occasional_and_needed_a_not_needed_one_comes_back(conn):
    tools.add_items(conn, [{"name": "tomatoes", "quantity": 2}])
    assert row(conn, "tomato") == {
        "name": "tomatoes",
        "buying_pattern": "occasional",
        "status": "needed",
        "quantity": 2,
        "usual_quantity": 2,
    }
    tools.remove_items(conn, ["tomatoes"])
    assert tools.add_items(conn, [{"name": "tomato"}])["added"] == [
        {"name": "tomatoes", "quantity": 2}
    ]
    tools.remove_items(conn, ["tomatoes"])
    tools.add_items(conn, [{"name": "tomatoes", "quantity": 3}])
    assert row(conn, "tomato")["quantity"] == 3
    assert row(conn, "tomato")["usual_quantity"] == 2


def test_fr_0_21_remove_many_makes_them_not_needed(conn):
    tools.add_items(
        conn, [{"name": "milk", "quantity": 3}, {"name": "eggs"}, {"name": "rice"}]
    )
    result = tools.remove_items(conn, ["milk", "egg", "bananas"])
    assert result == {"removed": ["milk", "egg"], "not_found": ["bananas"]}
    assert names(conn) == {"rice": 1}
    assert row(conn, "milk")["status"] == "not_needed"  # still known, not deleted
    assert tools.remove_items(conn, ["milk"]) == {"removed": [], "not_found": ["milk"]}


def test_fr_0_22_quantity_is_for_the_next_order_usual_changes_only_when_said(conn):
    tools.add_items(conn, [{"name": "tomatoes", "quantity": 2}])
    tools.remove_items(conn, ["tomatoes"])
    tools.set_quantity(conn, "tomatoes", 3)
    assert row(conn, "tomato")["status"] == "needed"
    assert (row(conn, "tomato")["quantity"], row(conn, "tomato")["usual_quantity"]) == (
        3,
        2,
    )
    assert tools.set_usual_quantity(conn, "tomatoes", 4) == {
        "name": "tomatoes",
        "usual_quantity": 4,
    }
    assert (row(conn, "tomato")["quantity"], row(conn, "tomato")["usual_quantity"]) == (
        4,
        4,
    )
    assert tools.set_usual_quantity(conn, "kale", 2) == {"not_found": "kale"}
    assert "error" in tools.set_usual_quantity(conn, "tomatoes", 0)


def test_fr_0_23_buying_pattern(conn):
    tools.add_items(conn, [{"name": "chicken"}])
    assert tools.set_buying_pattern(conn, "chicken", "frequent") == {
        "name": "chicken",
        "buying_pattern": "frequent",
    }
    assert row(conn, "chicken")["buying_pattern"] == "frequent"
    assert tools.set_buying_pattern(conn, "kale", "frequent") == {"not_found": "kale"}
    assert "error" in tools.set_buying_pattern(conn, "chicken", "weekly")


def test_fr_0_24_rename_keeps_everything_else(conn):
    tools.add_items(conn, [{"name": "yogurt", "quantity": 2}, {"name": "milk"}])
    tools.set_buying_pattern(conn, "yogurt", "frequent")
    assert tools.rename_item(conn, "yogurt", "Greek yogurt") == {
        "name": "yogurt",
        "new_name": "Greek yogurt",
    }
    assert row(conn, "greek yogurt") == {
        "name": "Greek yogurt",
        "buying_pattern": "frequent",
        "status": "needed",
        "quantity": 2,
        "usual_quantity": 2,
    }
    assert "error" in tools.rename_item(conn, "Greek yogurt", "milk")
    assert tools.rename_item(conn, "kale", "cabbage") == {"not_found": "kale"}


def test_fr_0_26_clear_makes_everything_not_needed_and_returns_what_was_needed(conn):
    tools.add_items(conn, [{"name": "bread"}, {"name": "milk", "quantity": 2}])
    tools.set_buying_pattern(conn, "milk", "frequent")
    assert tools.clear_all_items(conn) == {
        "removed": [{"name": "bread", "quantity": 1}, {"name": "milk", "quantity": 2}]
    }
    assert [(i["name"], i["status"]) for i in tools.read_list(conn)["items"]] == [
        ("milk", "not_needed")
    ]
