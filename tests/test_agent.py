"""Agent against Pydantic AI's FunctionModel: no network, no cost."""

import pytest
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from kiki import agent, tools
from kiki.db import connect


def scripted(*responses):
    """A model that replays responses in order and records the messages it was sent."""
    seen = []

    def fn(messages, info):
        seen.append(list(messages))
        return responses[len(seen) - 1]

    return FunctionModel(fn), seen


def update(**args):
    """The model calling update_list."""
    return ModelResponse(parts=[ToolCallPart("update_list", args)])


def reply(text):
    return ModelResponse(parts=[TextPart(text)])


@pytest.fixture
def conn(tmp_path):
    return connect(str(tmp_path / "test.db"))


def test_fr_0_9_single_turn_request_has_only_list_and_command(conn):
    tools.add_items(conn, [{"name": "bread"}])
    model, seen = scripted(update(add=[{"name": "milk"}], reply="Added milk."))

    turn = agent.run_turn("add milk", conn, model)

    first = seen[0]
    assert len(first) == 1  # one request, no history
    assert [p.content for p in first[0].parts] == ["add milk"]
    assert "bread x1 (occasional, needed)" in first[0].instructions
    assert turn["said"] == "Added milk."
    assert turn["tool_calls"] == [
        {
            "name": "add_items",
            "args": {"items": [{"name": "milk"}]},
            "result": {
                "added": [{"name": "milk", "quantity": 1}],
                "already_present": [],
            },
        }
    ]
    assert {i["name"] for i in tools.read_list(conn)["items"]} == {"bread", "milk"}


def test_nfr_0_3_a_change_takes_one_model_request(conn):
    model, seen = scripted(update(add=[{"name": "milk"}], reply="Added milk."))
    agent.run_turn("add milk", conn, model)
    assert len(seen) == 1


def test_fr_0_21_every_change_in_one_call_applies_in_order(conn):
    tools.add_items(conn, [{"name": "milk"}, {"name": "rice"}, {"name": "yogurt"}])
    model, _ = scripted(
        update(
            remove=["milk"],
            add=[{"name": "bread"}],
            set_quantities=[{"name": "rice", "quantity": 2}],
            set_usual_quantities=[{"name": "bread", "quantity": 3}],
            set_buying_patterns=[{"name": "bread", "buying_pattern": "frequent"}],
            renames=[{"name": "yogurt", "new_name": "Greek yogurt"}],
            reply="Done.",
        )
    )
    turn = agent.run_turn("a sentence with every kind of change", conn, model)
    assert [c["name"] for c in turn["tool_calls"]] == [
        "remove_items",
        "add_items",
        "set_quantity",
        "set_usual_quantity",
        "set_buying_pattern",
        "rename_item",
    ]
    assert [
        (i["name"], i["quantity"], i["buying_pattern"])
        for i in tools.read_list(conn)["items"]
    ] == [
        ("rice", 2, "occasional"),
        ("Greek yogurt", 1, "occasional"),
        ("bread", 3, "frequent"),
    ]


def test_fr_0_23_buying_pattern_must_be_frequent_or_occasional(conn):
    tools.add_items(conn, [{"name": "chicken"}])
    model, seen = scripted(
        update(
            set_buying_patterns=[{"name": "chicken", "buying_pattern": "weekly"}],
            reply="Okay.",
        ),
        reply(agent.DIDNT_CATCH),
    )
    turn = agent.run_turn("chicken is weekly", conn, model)
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)
    assert turn["tool_calls"] == []


def test_fr_0_26_clear_then_add_in_one_call(conn):
    tools.add_items(conn, [{"name": "milk"}])
    model, _ = scripted(update(clear=True, add=[{"name": "eggs"}], reply="Done."))
    agent.run_turn("clear the list and add eggs", conn, model)
    assert [i["name"] for i in tools.read_list(conn)["items"]] == ["eggs"]


def test_fr_0_3_list_snapshot_does_not_change_on_retry(conn):
    tools.add_items(conn, [{"name": "bread"}])
    model, seen = scripted(
        update(
            set_quantities=[{"name": "bread", "quantity": 2}], reply="Bread is now 2."
        ),
        update(
            set_quantities=[{"name": "bread", "quantity": 2}], reply="Bread is now two."
        ),
    )
    turn = agent.run_turn("add another bread", conn, model)
    assert turn["said"] == "Bread is now two."
    assert (
        "bread x1" in seen[1][-1].instructions
    )  # the retry still sees the start state
    assert [(i["name"], i["quantity"]) for i in tools.read_list(conn)["items"]] == [
        ("bread", 2)
    ]


def test_fr_0_8_no_usable_reply_falls_back_to_didnt_catch(conn):
    model = FunctionModel(lambda messages, info: reply(""))
    turn = agent.run_turn("blorp", conn, model)
    assert turn["said"] == agent.DIDNT_CATCH
    assert "UnexpectedModelBehavior" in turn["error"]
    assert turn["tool_calls"] == []


def test_fr_0_10_markdown_or_digits_are_sent_back_for_a_retry(conn):
    model, seen = scripted(reply("**Added** 2 milks."), reply("Added two milks."))
    turn = agent.run_turn("add two milks", conn, model)
    assert turn["said"] == "Added two milks."
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)


def test_fr_0_3_quantity_below_one_is_rejected_before_anything_changes(conn):
    model, seen = scripted(
        update(set_quantities=[{"name": "milk", "quantity": 0}], reply="Okay."),
        reply(agent.DIDNT_CATCH),
    )
    turn = agent.run_turn("make it zero milks", conn, model)
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)
    assert turn["tool_calls"] == []


def test_nfr_0_4_tool_errors_are_logged_and_retried(conn, monkeypatch):
    monkeypatch.setattr(tools, "clear_list", lambda conn: {"error": "disk on fire"})
    model, seen = scripted(
        update(clear=True, reply="Cleared."), reply(agent.DIDNT_CATCH)
    )
    turn = agent.run_turn("clear the list", conn, model)
    assert turn["tool_calls"][0]["result"] == {"error": "disk on fire"}
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)


def test_nfr_0_5_model_from_env(conn, monkeypatch):
    monkeypatch.setenv("KIKI_MODEL", "test")  # Pydantic AI's built-in offline TestModel
    turn = agent.run_turn("what's on my list", conn)
    assert turn["model"] == "test"
    assert turn["said"]


def test_nfr_0_4_turn_has_event_schema_fields(conn):
    model, _ = scripted(reply("Hi."))
    turn = agent.run_turn("hi", conn, model)
    assert set(turn) == {
        "type",
        "id",
        "ts",
        "source",
        "heard",
        "tool_calls",
        "said",
        "model",
        "latency_ms",
        "error",
    }
    assert turn["type"] == "turn" and turn["source"] == "text"


def test_fr_0_10_more_than_two_sentences_is_sent_back_for_a_retry(conn):
    model, seen = scripted(
        reply("Bread is there. I removed eggs. The list has bread."),
        reply("Removed eggs; bread was already there."),
    )
    turn = agent.run_turn("add bread and got the eggs", conn, model)
    assert turn["said"] == "Removed eggs; bread was already there."
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)
