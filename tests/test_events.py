import json

from kiki import events


def test_nfr_0_4_turn_logged_as_one_json_line(tmp_path):
    path = tmp_path / "logs" / "turns.jsonl"
    events.append_turn({"type": "turn", "heard": "add bread"}, str(path))
    events.append_turn({"type": "turn", "heard": "add milk\nplease"}, str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["heard"] for line in lines] == [
        "add bread",
        "add milk\nplease",
    ]


def test_nfr_0_4_recent_turns_reads_the_log_tail(tmp_path):
    path = str(tmp_path / "turns.jsonl")
    for i in range(5):
        events.append_turn({"type": "turn", "heard": str(i)}, path)
    assert [t["heard"] for t in events.recent_turns(3, path)] == ["2", "3", "4"]
    assert events.recent_turns(3, str(tmp_path / "missing.jsonl")) == []


def test_fr_0_13_published_events_reach_subscribers_and_state_is_remembered():
    subscription = events.subscribe()
    try:
        events.set_state("listening")
        assert subscription.get(timeout=1) == {"type": "state", "value": "listening"}
        assert events.current_state() == {"type": "state", "value": "listening"}
    finally:
        events.unsubscribe(subscription)
        events.set_state("idle")
