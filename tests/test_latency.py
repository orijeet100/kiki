import json

from kiki.latency import report


def test_nfr_0_3_report_medians_voice_turns_only(tmp_path):
    log = tmp_path / "turns.jsonl"
    turns = [
        {
            "source": "text",
            "latency_ms": {"stt": None, "llm": 9000, "tts": None, "total": 9000},
        },
        {
            "source": "voice",
            "latency_ms": {"stt": 400, "llm": 1000, "tts": 80, "total": 1500},
        },
        {
            "source": "voice",
            "latency_ms": {"stt": 600, "llm": 1400, "tts": 100, "total": 2100},
        },
        {
            "source": "voice",
            "latency_ms": {"stt": 500, "llm": 1200, "tts": 90, "total": 1800},
        },
    ]
    log.write_text("".join(json.dumps(t) + "\n" for t in turns), encoding="utf-8")
    assert report(str(log)) == {"stt": 500, "llm": 1200, "tts": 90, "total": 1800}
    assert report(str(log), last_n=1)["total"] == 1800
