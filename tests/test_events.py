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
