"""Local UI server: real HTTP on an ephemeral port, scripted agent model, no network."""

import http.client
import json
import re
import threading
from pathlib import Path

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


def test_nfr_0_7_binds_to_localhost_only(server):
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
    assert snapshot["items"] == [
        {
            "name": "bread",
            "quantity": 1,
            "buying_pattern": "occasional",
            "status": "needed",
            "product_name": None,
            "on_list": True,
        }
    ]
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
    assert [(i["name"], i["quantity"]) for i in new_list["items"]] == [
        ("bread", 1),
        ("milk", 2),
    ]


def test_fr_0_13_a_new_page_shows_past_runs(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot
    post_command(server, "add two milks")
    next(e for e in events if e["type"] == "turn")  # the run is logged

    snapshot = next(read_events(request(server, "GET", "/events")))
    assert [t["heard"] for t in snapshot["turns"]] == ["add two milks"]
    assert {i["name"] for i in snapshot["items"]} == {"bread", "milk"}


def post_item(server, body, content_type="application/json"):
    return request(
        server, "POST", "/item", json.dumps(body), {"Content-Type": content_type}
    )


def test_fr_0_27_a_click_flips_an_item_and_the_page_gets_the_new_list(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot

    response = post_item(server, {"name": "bread", "needed": False})
    assert response.status == 200
    assert json.loads(response.read()) == {"removed": ["bread"], "not_found": []}
    off = next(events)["items"]  # Occasional: off the List, still known (FR-0.41)
    assert [(i["name"], i["on_list"]) for i in off] == [("bread", False)]

    assert post_item(server, {"name": "bread", "needed": True}).status == 200
    assert [(i["name"], i["status"]) for i in next(events)["items"]] == [
        ("bread", "needed")
    ]


@pytest.mark.parametrize(
    "body", [{"name": "bread"}, {"name": "bread", "needed": "yes"}, {"needed": True}]
)
def test_fr_0_27_rejects_a_malformed_click(server, body):
    assert post_item(server, body).status == 400


def test_fr_0_33_an_edit_sets_the_quantity_and_the_page_gets_the_new_list(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot

    response = post_item(server, {"name": "bread", "quantity": 3})
    assert response.status == 200
    assert json.loads(response.read()) == {"name": "bread", "quantity": 3}
    assert [(i["name"], i["quantity"]) for i in next(events)["items"]] == [("bread", 3)]


def test_fr_0_33_an_edit_renames_an_item(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot

    assert post_item(server, {"name": "bread", "new_name": "sourdough"}).status == 200
    assert [i["name"] for i in next(events)["items"]] == ["sourdough"]


def test_fr_0_33_an_edit_makes_an_item_frequent_so_it_stays_when_not_needed(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot

    response = post_item(server, {"name": "bread", "buying_pattern": "frequent"})
    assert response.status == 200
    assert json.loads(response.read()) == {
        "name": "bread",
        "buying_pattern": "frequent",
    }
    next(events)
    post_item(server, {"name": "bread", "needed": False})
    assert [(i["name"], i["status"]) for i in next(events)["items"]] == [
        ("bread", "not_needed")
    ]


def test_fr_0_33_a_refused_edit_says_why(server, tmp_path):
    tools.add_items(connect(str(tmp_path / "ui.db")), [{"name": "milk"}])
    assert post_item(server, {"name": "bread", "new_name": "milk"}).status == 409
    assert post_item(server, {"name": "rice", "quantity": 2}).status == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "bread", "quantity": 0},
        {"name": "bread", "quantity": "2"},
        {"name": "bread", "quantity": True},
        {"name": "bread", "new_name": " "},
        {"name": "bread", "buying_pattern": "weekly"},
        {"name": "bread", "quantity": 2, "needed": True},
    ],
)
def test_fr_0_33_rejects_a_malformed_edit(server, body):
    assert post_item(server, body).status == 400


def test_nfr_0_7_rejects_a_click_that_is_not_json(server):
    assert (
        post_item(server, {"name": "bread", "needed": False}, "text/plain").status
        == 415
    )


def test_nfr_0_7_rejects_requests_addressed_to_another_host(server):
    response = request(server, "GET", "/", headers={"Host": "evil.example:8765"})
    assert response.status == 403


@pytest.mark.parametrize(
    "host", ["localhost:8765", "127.0.0.1:8765", "192.168.1.216:8765"]
)
def test_nfr_0_7_accepts_requests_addressed_to_localhost_or_an_ip_address(server, host):
    # The Tab5 addresses the laptop by its IP; an IP can't be rebound to another site.
    assert request(server, "GET", "/", headers={"Host": host}).status == 200


def test_nfr_0_7_kiki_ui_host_opens_the_ui_to_the_home_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "HOST", "0.0.0.0")
    server = ui.serve(connect(str(tmp_path / "ui.db")), port=0)
    try:
        assert server.server_address[0] == "0.0.0.0"
    finally:
        server.shutdown()


def test_nfr_0_7_rejects_commands_that_are_not_json(server):
    assert post_command(server, "add milk", content_type="text/plain").status == 415


@pytest.mark.parametrize("text", ["", "   ", "x" * (ui.MAX_COMMAND_CHARS + 1)])
def test_nfr_0_7_rejects_empty_or_oversized_commands(server, text):
    assert post_command(server, text).status == 400


def test_fr_0_15_a_second_kiki_cannot_start_on_the_same_port(server, tmp_path):
    with pytest.raises(ui.AlreadyRunning):
        ui.serve(connect(str(tmp_path / "other.db")), port=server.server_address[1])


def test_fr_0_16_colors_are_design_md_tokens():
    root = Path(__file__).parent.parent
    page = (root / "src/kiki/ui.html").read_text(encoding="utf-8")
    design = (root / "DESIGN.md").read_text(encoding="utf-8").lower()
    style = page[page.index("<style>") : page.index("</style>")]
    tokens = style[style.index(":root {") : style.index("}")]
    rest = style.replace(tokens, "")

    declared = re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-f]{6})", tokens)
    assert declared
    for name, value in declared:
        assert value in design, f"--{name} {value} isn't in DESIGN.md"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", rest)
    assert "prefers-color-scheme" not in style


def test_fr_0_17_page_loads_the_speaking_orb_from_kiki_itself(server):
    page = request(server, "GET", "/").read().decode()
    assert '<script src="/speaking-orb.js"></script>' in page
    assert "<speaking-orb" in page
    # nothing from the network
    assert not re.search(r"""(src|href)=["']https?:""", page)
    response = request(server, "GET", "/speaking-orb.js")
    assert response.status == 200
    assert response.getheader("Content-Type").startswith("text/javascript")
    script = response.read().decode()
    assert "customElements.define('speaking-orb'" in script
    assert "MIT License" in script


def post_json(server, path, body):
    return request(
        server, "POST", path, json.dumps(body), {"Content-Type": "application/json"}
    )


def test_fr_0_35_the_reset_button_starts_the_list_over_and_shows_in_history(server):
    events = read_events(request(server, "GET", "/events"))
    next(events)  # snapshot
    response = post_json(server, "/reset", {})
    assert response.status == 200
    assert json.loads(response.read()) == {
        "needed": []
    }  # bread was Occasional: off the List
    turn = next(e for e in events if e["type"] == "turn")
    assert turn["source"] == "button" and turn["tool_calls"][0]["name"] == "reset_list"
    assert (
        turn["tool_calls"][0]["args"]["before"][0]["name"] == "bread"
    )  # the log keeps it


def test_fr_0_34_an_edit_forgets_the_product(server, tmp_path):
    conn = connect(str(tmp_path / "ui.db"))
    tools.set_product_for_item(
        conn, "bread", 82101319, "Wegmans Soft 100% Whole Wheat Bread"
    )
    response = post_json(server, "/item", {"name": "bread", "forget_product": True})
    assert response.status == 200
    assert tools.items_without_product(conn) == ["bread"]


def test_nfr_0_9_the_extension_gets_its_job_and_answers_it(server, monkeypatch):
    from kiki import instacart

    port = server.server_address[1]

    def extension(url):
        """What browser/instacart/worker.js does, over HTTP."""
        job_id, kiki_port = url.rsplit("#kiki-", 1)[1].split("-")
        assert kiki_port == str(port)
        job = json.loads(request(server, "GET", "/instacart/job").read())
        assert (
            job["id"] == job_id
            and job["kind"] == "search"
            and job["store"] == instacart.STORE
        )
        post_json(
            server, "/instacart/result", {"id": "someone-else", "ok": True, "data": {}}
        )
        post_json(
            server,
            "/instacart/result",
            {"id": job_id, "ok": True, "data": {"results": [1]}},
        )

    monkeypatch.setattr(instacart, "PORT", port)
    monkeypatch.setattr(
        instacart,
        "open_tab",
        lambda url: threading.Thread(target=extension, args=(url,)).start(),
    )
    assert instacart.run_job("search", query="walnuts") == {"results": [1]}
    assert request(server, "GET", "/instacart/job").status == 204  # nothing waiting now


def test_nfr_0_9_a_failed_job_raises_its_reason(server, monkeypatch):
    from kiki import instacart

    def extension(url):
        job_id = url.rsplit("#kiki-", 1)[1].split("-")[0]
        post_json(
            server,
            "/instacart/result",
            {"id": job_id, "ok": False, "error": "signed_out"},
        )

    monkeypatch.setattr(
        instacart,
        "open_tab",
        lambda url: threading.Thread(target=extension, args=(url,)).start(),
    )
    with pytest.raises(instacart.InstacartError) as e:
        instacart.run_job("read_orders", known=[])
    assert e.value.code == "signed_out"


def test_fr_0_41_the_screens_also_get_the_items_not_on_the_list(server, tmp_path):
    conn = connect(str(tmp_path / "ui.db"))
    tools.add_items(conn, [{"name": "walnuts"}])
    tools.remove_items(
        conn, ["walnuts"]
    )  # Occasional and Not needed: off the List, still known
    snapshot = next(read_events(request(server, "GET", "/events")))
    assert [(i["name"], i["on_list"]) for i in snapshot["items"]] == [
        ("bread", True),
        ("walnuts", False),
    ]
