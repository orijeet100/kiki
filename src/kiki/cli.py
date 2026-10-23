"""Terminal loop (v0.1): type a command, see what Kiki did and said."""

import json

from kiki import tools
from kiki.agent import run_turn, warm_up
from kiki.db import connect
from kiki.events import record_turn


def main() -> None:
    conn = connect()
    warm_up()
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
        record_turn(turn, tools.read_all_items(conn)["items"])
        for call in turn["tool_calls"]:
            print(
                f"  {call['name']}({json.dumps(call['args'])}) -> {json.dumps(call['result'])}"
            )
        print(f"Kiki: {turn['said']}  ({turn['latency_ms']['total']} ms)")
        if turn["error"]:
            print(f"  error: {turn['error']}")


if __name__ == "__main__":
    main()
