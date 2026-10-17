"""Latency report from the turn log (NFR-0.3): python -m kiki.latency [last_n]."""

import json
import os
import statistics
import sys


def report(path: str, last_n: int = 20) -> dict[str, float]:
    """Median ms per stage over the last `last_n` voice turns."""
    with open(path, encoding="utf-8") as f:
        turns = [json.loads(line) for line in f]
    voice = [t["latency_ms"] for t in turns if t["source"] == "voice"][-last_n:]
    stages = ("stt", "llm", "tts", "total")
    return {
        s: statistics.median(v)
        for s in stages
        if (v := [lat[s] for lat in voice if lat[s]])
    }


def main() -> None:
    last_n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    medians = report(os.environ.get("KIKI_LOG", "logs/turns.jsonl"), last_n)
    if not medians:
        sys.exit("No voice turns in the log yet.")
    print(f"Median over the last {last_n} voice turns (ms):")
    for stage, ms in medians.items():
        print(f"  {stage:5s} {ms:6.0f}")
    total = medians.get("total", 0)
    print("NFR-0.3 (about 2 s or less):", "met" if total <= 2000 else "NOT met")


if __name__ == "__main__":
    main()
