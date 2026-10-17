"""ROADMAP v0 scenarios against the real Claude API.

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


def test_scenario_6_fr_0_5_got_them(conn):
    seed(conn, ("milk", 3), ("eggs", 1), ("rice", 1))
    agent.run_turn("Got the milk and eggs", conn)
    assert state(conn) == {"rice": 1}


def test_scenario_7_fr_0_5_remove_missing(conn):
    seed(conn, ("rice", 1))
    turn = agent.run_turn("Remove bananas", conn)
    assert state(conn) == {"rice": 1}
    assert re.search(r"n't|not", turn["said"].lower()), turn["said"]


def test_scenario_8_fr_0_6_read_all_eight(conn):
    names = ["bread", "milk", "eggs", "rice", "apples", "butter", "cheese", "onions"]
    seed(conn, *[(n, 1) for n in names])
    turn = agent.run_turn("What's on my list?", conn)
    said = turn["said"].lower()
    assert all(tools.normalize(n) in said for n in names), said


def test_scenario_9_fr_0_6_empty(conn):
    turn = agent.run_turn("What's on my list?", conn)
    assert "empty" in turn["said"].lower()


def test_scenario_10_fr_0_7_clear(conn):
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
