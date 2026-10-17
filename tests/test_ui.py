"""Local UI server: real HTTP on an ephemeral port, scripted agent model, no network."""

import http.client
import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from kiki import tools, ui
from kiki.db import connect


def add_milk(messages, info):
    args = {"add": [{"name": "milk", "quantity": 2}], "reply": "Added two milks."}
    return ModelResponse(parts=[ToolCallPart("update_list", args)])


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("KIKI_LOG", str(tmp_path / "turns.jsonl"))
    conn = connect(str(tmp_path / "ui.db"))
    tools.add_items(conn, [{"name": "bread"}])
    server = ui.serve(conn, port=0, model=FunctionModel(add_milk))
    yield server
    server.shutdown()


def request(server, method, path, body=None, headers=None):
    client = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    client.request(method, path, body=body, headers=headers or {})
    return client.getresponse()


def post_command(server, text, content_type="application/json"):
    body = json.dumps({"text": text})
    return request(server, "POST", "/command", body, {"Content-Type": content_type})


def read_events(response):
    """Yield parsed Server-Sent Events from a streaming response."""
    while True:
        line = response.fp.readline().decode()
        if line.startswith("data: "):
            yield json.loads(line[6:])


def test_nfr_0_6_binds_to_localhost_only(server):
    assert server.server_address[0] == "127.0.0.1"


def test_fr_0_13_serves_the_page(server):
    response = request(server, "GET", "/")
    assert response.status == 200
    assert b"Grocery list" in response.read()


def test_fr_0_13_live_events_for_a_typed_command(server):
    stream = request(server, "GET", "/events")
    events = read_events(stream)
    snapshot = next(events)
    assert snapshot["type"] == "snapshot"
    assert snapshot["items"] == [{"name": "bread", "quantity": 1}]
    assert snapshot["turns"] == []

    assert post_command(server, "add two milks").status == 202

    seen = []
    for event in events:
        seen.append(event)
        if event == {"type": "state", "value": "idle"}:
            break
    types = [e["type"] for e in seen]
    assert types == ["state", "turn", "list", "state"]
    assert seen[0]["value"] == "thinking"
    turn, new_list = seen[1], seen[2]
    assert turn["heard"] == "add two milks" and turn["said"] == "Added two milks."
    assert new_list["items"] == [
        {"name": "bread", "quantity": 1},
        {"name": "milk", "quantity": 2},
    ]


def test_fr_0_13_a_new_page_shows_past_runs(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot
    post_command(server, "add two milks")
    next(e for e in events if e["type"] == "turn")  # the run is logged

    snapshot = next(read_events(request(server, "GET", "/events")))
    assert [t["heard"] for t in snapshot["turns"]] == ["add two milks"]
    assert {i["name"] for i in snapshot["items"]} == {"bread", "milk"}


def test_nfr_0_6_rejects_requests_addressed_to_another_host(server):
    response = request(server, "GET", "/", headers={"Host": "evil.example:8765"})
    assert response.status == 403


def test_nfr_0_6_rejects_commands_that_are_not_json(server):
    assert post_command(server, "add milk", content_type="text/plain").status == 415


@pytest.mark.parametrize("text", ["", "   ", "x" * (ui.MAX_COMMAND_CHARS + 1)])
def test_nfr_0_6_rejects_empty_or_oversized_commands(server, text):
    assert post_command(server, text).status == 400
