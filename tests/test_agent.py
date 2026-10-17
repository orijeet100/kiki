"""Agent loop against Pydantic AI's FunctionModel: no network, no cost."""

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


def call(name, args):
    return ModelResponse(parts=[ToolCallPart(name, args)])


def reply(text):
    return ModelResponse(parts=[TextPart(text)])


@pytest.fixture
def conn(tmp_path):
    return connect(str(tmp_path / "test.db"))


def test_fr_0_9_single_turn_request_has_only_list_and_command(conn):
    tools.add_items(conn, [{"name": "bread"}])
    model, seen = scripted(
        call("add_items", {"items": [{"name": "milk"}]}), reply("Added milk.")
    )

    turn = agent.run_turn("add milk", conn, model)

    first = seen[0]
    assert len(first) == 1  # one request, no history
    assert [p.content for p in first[0].parts] == ["add milk"]
    assert "bread x1" in first[0].instructions
    assert turn["said"] == "Added milk."
    assert turn["tool_calls"] == [
        {
            "name": "add_items",
            "args": {"items": [{"name": "milk", "quantity": 1}]},
            "result": {
                "added": [{"name": "milk", "quantity": 1}],
                "already_present": [],
            },
        }
    ]
    assert {i["name"] for i in tools.read_list(conn)["items"]} == {"bread", "milk"}


def test_fr_0_3_list_snapshot_does_not_change_mid_turn(conn):
    tools.add_items(conn, [{"name": "bread"}])
    model, seen = scripted(
        call("set_quantity", {"name": "bread", "quantity": 2}), reply("Two breads now.")
    )
    agent.run_turn("add another bread", conn, model)
    assert (
        "bread x1" in seen[1][-1].instructions
    )  # second request still sees the start state


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


def test_bad_tool_args_are_rejected_before_the_tool_runs(conn):
    model, seen = scripted(
        call("set_quantity", {"name": "milk", "quantity": 0}), reply(agent.DIDNT_CATCH)
    )
    turn = agent.run_turn("make it zero milks", conn, model)
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)
    assert turn["tool_calls"] == []


def test_tool_errors_are_logged_and_retried(conn, monkeypatch):
    monkeypatch.setattr(tools, "clear_list", lambda conn: {"error": "disk on fire"})
    model, seen = scripted(call("clear_list", {}), reply("Sorry, I didn't catch that."))
    turn = agent.run_turn("clear the list", conn, model)
    assert turn["tool_calls"][0]["result"] == {"error": "disk on fire"}
    assert isinstance(seen[1][-1].parts[0], RetryPromptPart)


def test_runaway_tool_loop_stops_with_error(conn):
    model = FunctionModel(lambda messages, info: call("read_list", {}))
    turn = agent.run_turn("loop", conn, model)
    assert turn["error"] and "UsageLimitExceeded" in turn["error"]


def test_nfr_0_5_model_from_env(conn, monkeypatch):
    monkeypatch.setenv("KIKI_MODEL", "test")  # Pydantic AI's built-in offline TestModel
    turn = agent.run_turn("what's on my list", conn)
    assert turn["model"] == "test"
    assert turn["tool_calls"]  # TestModel calls every tool, so the env model really ran


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
