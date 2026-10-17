"""Terminal loop (v0.1): type a command, see what Kiki did and said."""

import json

from kiki.agent import run_turn
from kiki.db import connect
from kiki.events import append_turn


def main() -> None:
    conn = connect()
    print("Kiki v0.1. Type a command, or 'quit'.")
    while True:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not command:
            continue
        if command.lower() in {"quit", "exit"}:
            break
        turn = run_turn(command, conn)
        append_turn(turn)
        for call in turn["tool_calls"]:
            print(
                f"  {call['name']}({json.dumps(call['args'])}) -> {json.dumps(call['result'])}"
            )
        print(f"Kiki: {turn['said']}  ({turn['latency_ms']['total']} ms)")
        if turn["error"]:
            print(f"  error: {turn['error']}")


if __name__ == "__main__":
    main()
