"""ROADMAP v0 and v0.12 scenarios against the real Claude API.

Asserts on tool calls and final list state, not exact wording. Run: uv run --env-file .env pytest -m scenario
"""

import os
import re

import pytest

from kiki import agent, tools
from kiki.db import connect

pytestmark = [
    pytest.mark.scenario,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"
    ),
]


@pytest.fixture
def conn(tmp_path):
    return connect(str(tmp_path / "test.db"))


def seed(conn, *items):
    tools.add_items(conn, [{"name": n, "quantity": q} for n, q in items])


def state(conn):
    return {
        tools.normalize(i["name"]): i["quantity"]
        for i in tools.read_list(conn)["items"]
    }


def item(conn, name):
    row = conn.execute(
        "SELECT name, buying_pattern, status, quantity, usual_quantity FROM items"
        " WHERE normalized_name = ?",
        (tools.normalize(name),),
    ).fetchone()
    return dict(row) if row else None


def seed_item(conn, name, buying_pattern="occasional", needed=True, usual=1):
    """One Item in a given state, set up through the plain tools."""
    tools.add_items(conn, [{"name": name, "quantity": usual}])
    tools.set_buying_pattern(conn, name, buying_pattern)
    if not needed:
        tools.remove_items(conn, [name])


def on_list(conn):
    return {tools.normalize(i["name"]) for i in tools.read_list(conn)["items"]}


def called(turn):
    return [c["name"] for c in turn["tool_calls"]]


def assert_voice_style(said):
    """FR-0.10: short, no markdown, no digits."""
    assert not re.search(r"[*#`\-•]\s|\d", said), said
    assert len(re.findall(r"[.!?](\s|$)", said)) <= 2, said


def test_scenario_1_fr_0_1_add_two(conn):
    turn = agent.run_turn("Add bread and eggs", conn)
    assert state(conn) == {"bread": 1, "egg": 1}
    assert_voice_style(turn["said"])


def test_scenario_2_fr_0_2_duplicate(conn):
    seed(conn, ("bread", 1))
    turn = agent.run_turn("Add bread", conn)
    assert state(conn) == {"bread": 1}
    assert "already" in turn["said"].lower()


def test_scenario_3_fr_0_3_another(conn):
    seed(conn, ("bread", 1))
    agent.run_turn("Add another bread", conn)
    assert state(conn) == {"bread": 2}


def test_scenario_4_fr_0_4_plural_duplicate(conn):
    seed(conn, ("eggs", 1))
    agent.run_turn("Add egg", conn)
    assert state(conn) == {"egg": 1}


def test_scenario_5_fr_0_1_mixed_quantities(conn):
    agent.run_turn("Add milk, two apples and some rice", conn)
    assert state(conn) == {"milk": 1, "apple": 2, "rice": 1}


def test_scenario_6_fr_0_21_got_them(conn):
    seed(conn, ("milk", 3), ("eggs", 1), ("rice", 1))
    agent.run_turn("Got the milk and eggs", conn)
    assert state(conn) == {"rice": 1}


def test_scenario_7_fr_0_21_remove_missing(conn):
    seed(conn, ("rice", 1))
    turn = agent.run_turn("Remove bananas", conn)
    assert state(conn) == {"rice": 1}
    assert re.search(r"n't|not", turn["said"].lower()), turn["said"]


def test_scenario_8_fr_0_25_read_all_eight(conn):
    names = ["bread", "milk", "eggs", "rice", "apples", "butter", "cheese", "onions"]
    seed(conn, *[(n, 1) for n in names])
    turn = agent.run_turn("What's on my list?", conn)
    said = turn["said"].lower()
    assert all(tools.normalize(n) in said for n in names), said


def test_scenario_9_fr_0_25_empty(conn):
    turn = agent.run_turn("What's on my list?", conn)
    assert "empty" in turn["said"].lower()


def test_scenario_10_fr_0_26_clear(conn):
    seed(conn, ("bread", 1), ("milk", 1), ("eggs", 1), ("rice", 1), ("butter", 1))
    turn = agent.run_turn("Clear the list", conn)
    assert state(conn) == {}
    assert "five" in turn["said"].lower()
    clear = next(c for c in turn["tool_calls"] if c["name"] == "clear_list")
    assert len(clear["result"]["removed"]) == 5


def test_scenario_11_fr_0_8_garbled(conn):
    seed(conn, ("rice", 1))
    turn = agent.run_turn("Blorp the frim", conn)
    assert state(conn) == {"rice": 1}
    assert called(turn) == []
    assert turn["said"] == agent.DIDNT_CATCH


def test_scenario_12_fr_0_4_misheard_got_means_remove(conn):
    seed(conn, ("eggs", 1), ("rice", 1))
    agent.run_turn("Dot the eggs.", conn)
    assert state(conn) == {"rice": 1}


def test_scenario_13_fr_0_20_new_item(conn):
    agent.run_turn("Add shrimp", conn)
    assert item(conn, "shrimp") == {
        "name": "shrimp",
        "buying_pattern": "occasional",
        "status": "needed",
        "quantity": 1,
        "usual_quantity": 1,
    }


def test_scenario_14_fr_0_20_not_needed_comes_back(conn):
    seed_item(conn, "chicken", "frequent", needed=False)
    agent.run_turn("Add chicken", conn)
    assert (item(conn, "chicken")["status"], item(conn, "chicken")["quantity"]) == (
        "needed",
        1,
    )


def test_scenario_15_fr_0_22_a_number_for_this_time(conn):
    seed_item(conn, "tomatoes", "frequent", needed=False, usual=2)
    agent.run_turn("Get three tomatoes", conn)
    tomatoes = item(conn, "tomatoes")
    assert (tomatoes["status"], tomatoes["quantity"], tomatoes["usual_quantity"]) == (
        "needed",
        3,
        2,
    )


def test_scenario_16_fr_0_21_not_this_time(conn):
    seed_item(conn, "chicken", "frequent")
    agent.run_turn("Not chicken this time", conn)
    assert item(conn, "chicken")["status"] == "not_needed"
    assert "chicken" in on_list(conn)


def test_scenario_17_fr_0_21_remove_occasional(conn):
    seed_item(conn, "butter")
    agent.run_turn("Remove butter", conn)
    assert item(conn, "butter")["status"] == "not_needed"
    assert "butter" not in on_list(conn)


def test_scenario_18_fr_0_22_usual_quantity(conn):
    seed_item(conn, "tomatoes", "frequent", usual=2)
    agent.run_turn("We usually get three tomatoes", conn)
    tomatoes = item(conn, "tomatoes")
    assert (tomatoes["quantity"], tomatoes["usual_quantity"]) == (3, 3)


def test_scenario_19_fr_0_23_make_frequent(conn):
    seed_item(conn, "chicken")
    agent.run_turn("Make chicken frequent", conn)
    assert item(conn, "chicken")["buying_pattern"] == "frequent"


def test_scenario_20_fr_0_23_stop_buying(conn):
    seed_item(conn, "beetroot", "frequent")
    agent.run_turn("We don't buy beetroot any more", conn)
    beetroot = item(conn, "beetroot")
    assert (beetroot["buying_pattern"], beetroot["status"]) == (
        "occasional",
        "not_needed",
    )


def test_scenario_21_fr_0_24_rename(conn):
    seed_item(conn, "yogurt", "frequent", usual=2)
    agent.run_turn("Call yogurt Greek yogurt", conn)
    assert item(conn, "greek yogurt") == {
        "name": "Greek yogurt",
        "buying_pattern": "frequent",
        "status": "needed",
        "quantity": 2,
        "usual_quantity": 2,
    }


def test_scenario_22_fr_0_25_read_needed_then_count_the_rest(conn):
    for name in ("milk", "eggs", "bread"):
        seed_item(conn, name)
    for name in ("chicken", "walnuts"):
        seed_item(conn, name, "frequent", needed=False)
    said = agent.run_turn("What's on my list?", conn)["said"].lower()
    assert all(n in said for n in ("milk", "egg", "bread")), said
    assert "two" in said and "chicken" not in said, said


def test_scenario_23_fr_0_26_clear_keeps_frequent_items(conn):
    for name in ("milk", "eggs"):
        seed_item(conn, name)
    for name in ("chicken", "walnuts"):
        seed_item(conn, name, "frequent")
    turn = agent.run_turn("Clear the list", conn)
    assert [i["status"] for i in tools.read_list(conn)["items"]] == ["not_needed"] * 2
    assert on_list(conn) == {"chicken", "walnut"}
    assert "four" in turn["said"].lower()


def test_nfr_0_3_turns_on_new_threads_do_not_stall(conn):
    """The UI and voice loop run turns on other threads; a client cached across threads used
    to stall each turn until the request timeout (about 11 s)."""
    import threading
    import time

    took = []

    def one_turn():
        start = time.perf_counter()
        agent.run_turn("What's on my list?", conn)
        took.append(time.perf_counter() - start)

    for _ in range(3):
        thread = threading.Thread(target=one_turn)
        thread.start()
        thread.join()
    assert max(took) < 5, took
