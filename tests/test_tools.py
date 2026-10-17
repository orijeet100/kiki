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


def test_fr_0_5_remove_many_whatever_quantity(conn):
    tools.add_items(
        conn, [{"name": "milk", "quantity": 3}, {"name": "eggs"}, {"name": "rice"}]
    )
    result = tools.remove_items(conn, ["milk", "egg", "bananas"])
    assert result == {"removed": ["milk", "egg"], "not_found": ["bananas"]}
    assert names(conn) == {"rice": 1}


def test_fr_0_6_read_whole_list_in_order(conn):
    tools.add_items(conn, [{"name": f"item{i}"} for i in range(8)])
    assert [i["name"] for i in tools.read_list(conn)["items"]] == [
        f"item{i}" for i in range(8)
    ]
    tools.clear_list(conn)
    assert tools.read_list(conn) == {"items": []}


def test_fr_0_7_clear_returns_removed_items(conn):
    tools.add_items(conn, [{"name": "bread"}, {"name": "milk", "quantity": 2}])
    assert tools.clear_list(conn) == {
        "removed": [{"name": "bread", "quantity": 1}, {"name": "milk", "quantity": 2}]
    }
    assert names(conn) == {}
