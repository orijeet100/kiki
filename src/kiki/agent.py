"""One command in, one `turn` event out, via Pydantic AI (ADR 0015).

Single-turn: no history (ADR 0009). One model request per command (ADR 0018): the model either
calls `update_list` with every change plus the spoken reply, or answers in plain text.
The model is a "provider:name" string from KIKI_MODEL, so swapping providers is an env change.
"""

import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput
from pydantic_ai.exceptions import (
    AgentRunError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.models import Model, infer_model
from pydantic_ai.settings import ModelSettings

from kiki import tools

DEFAULT_MODEL = "anthropic:claude-haiku-5-5"
DIDNT_CATCH = "Sorry, I didn't catch that."

INSTRUCTIONS = """You manage a household grocery list by voice. Replies are spoken aloud: one or two \
short sentences, no markdown, bullets or emojis, numbers written as words ("two milks").

Rules:
- To change the list, call update_list once with every change from the sentence and the spoken \
reply. Each request is independent; you only know the current list below.
- Questions about the list are answered in plain text from the current list, with no call.
- Fix obvious speech-to-text slips ("bred" means bread). Use plain item names ("rice", not "some rice").
- "Got the X" means it was bought: remove it. Speech-to-text often hears it as "cut", "dot" or "gut".
- If an item is already on the list, say so and don't change it. Only change a quantity when the \
user explicitly asks ("add another milk", "make it three milks"); compute the new number from the \
list and put it in set_quantities.
- Removing an item deletes it completely, whatever its quantity.
- When asked what's on the list, read every item.
- After clearing the list, say only how many items were removed ("Cleared five items.").
- If you can't tell what the user wants, reply exactly "Sorry, I didn't catch that." in plain text."""


os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


@dataclass
class Deps:
    conn: sqlite3.Connection
    list_at_start: str
    tool_calls: list[dict] = field(default_factory=list)


class Item(BaseModel):
    name: str = Field(description="Item name as spoken, e.g. 'eggs'")
    quantity: int = Field(default=1, ge=1)


def _snapshot(conn: sqlite3.Connection) -> str:
    items = tools.read_list(conn)["items"]
    return ", ".join(f"{i['name']} x{i['quantity']}" for i in items) or "(empty)"


def _call(ctx: RunContext[Deps], tool: str, /, **args) -> dict:
    """Run a plain tool (ADR 0008), record it for the turn log, turn tool errors into retries."""
    result = getattr(tools, tool)(ctx.deps.conn, **args)
    ctx.deps.tool_calls.append({"name": tool, "args": args, "result": result})
    if "error" in result:
        raise ModelRetry(result["error"])
    return result


def update_list(
    ctx: RunContext[Deps],
    reply: str,
    add: list[Item] | None = None,
    remove: list[str] | None = None,
    set_quantities: list[Item] | None = None,
    clear: bool = False,
) -> str:
    """Make every list change the user asked for, in one call, and give the spoken reply.

    Args:
        reply: What to say back: one short sentence (two at most), written from the current list.
        add: Items to add. Items already on the list stay unchanged; say so in the reply.
        remove: Items to delete completely, whatever their quantity.
        set_quantities: New quantities for items already on the list, only when asked explicitly.
        clear: True to remove every item.
    """
    # Every step is idempotent, so a retry after ModelRetry can safely re-apply them.
    if clear:
        _call(ctx, "clear_list")
    if remove:
        _call(ctx, "remove_items", names=remove)
    if add:
        _call(ctx, "add_items", items=[i.model_dump() for i in add])
    for change in set_quantities or []:
        _call(ctx, "set_quantity", name=change.name, quantity=change.quantity)
    return reply


agent = Agent(
    deps_type=Deps,
    output_type=[ToolOutput(update_list, name="update_list"), str],
    instructions=INSTRUCTIONS,
    # timeout: a stalled request must fail in seconds, not the client's default ten minutes.
    model_settings=ModelSettings(thinking="low", max_tokens=4096, timeout=10),
    retries=2,
)


@agent.instructions
def current_list(ctx: RunContext[Deps]) -> str:
    # Pydantic AI re-renders instructions on every model request (including retries), so this
    # must be the snapshot from the start of the turn, not a live read.
    return f"Current list at the start of this request: {ctx.deps.list_at_start}"


@agent.output_validator
def spoken_style(output: str) -> str:
    """FR-0.10 guard: a reply must be speakable. (Empty replies are retried by Pydantic AI itself.)"""
    output = output.strip()
    if re.search(r"[*#`•_]|^\s*-\s|\d", output, re.MULTILINE):
        raise ModelRetry(
            "Spoken reply: no markdown or bullets, write numbers as words."
        )
    if len(re.findall(r"[.!?](?:\s|$)", output)) > 2:
        raise ModelRetry("Too long to say aloud: one or two short sentences.")
    return output


def model_name() -> str:
    return os.environ.get("KIKI_MODEL", DEFAULT_MODEL)


def warm_up() -> None:
    """Pay the one-time model start-up cost (imports, TLS setup, about 3 s) before the first command.

    The client itself is built per turn: a cached client keeps connections tied to the event
    loop of the thread that first used it, and a turn on another thread then stalls until the
    request timeout (measured: 11 s per turn). A fresh client costs about 40 ms.
    """
    infer_model(model_name())


# ponytail: one turn at a time for the whole process. Voice and the UI's text box share one
# SQLite connection, and a household never needs two commands in parallel.
_turn_lock = threading.Lock()


def run_turn(
    command: str,
    conn: sqlite3.Connection,
    model: Model | str | None = None,
    source: str = "text",
) -> dict:
    with _turn_lock:
        return _run_turn(command, conn, model, source)


def _run_turn(command: str, conn: sqlite3.Connection, model, source: str) -> dict:
    start = time.perf_counter()
    now = datetime.now(UTC)
    name = model.model_name if isinstance(model, Model) else (model or model_name())
    model = model if isinstance(model, Model) else infer_model(name)
    deps = Deps(conn, _snapshot(conn))
    turn = {
        "type": "turn",
        "id": f"t_{now:%Y%m%dT%H%M%S}_{secrets.token_hex(2)}",
        "ts": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": source,
        "heard": command,
        "tool_calls": deps.tool_calls,
        "said": "",
        "model": name,
        "latency_ms": {"stt": None, "llm": 0, "tts": None, "total": 0},
        "error": None,
    }

    try:
        turn["said"] = agent.run_sync(command, model=model, deps=deps).output
    except ModelHTTPError as e:
        turn["said"] = "Something went wrong, please try again."
        turn["error"] = f"API error {e.status_code}"
    except ModelAPIError:
        turn["said"] = "I can't reach the internet right now."
        turn["error"] = "connection error"
    except (
        UnexpectedModelBehavior
    ) as e:  # retries exhausted: no speakable reply (FR-0.8)
        turn["said"] = DIDNT_CATCH
        turn["error"] = f"{type(e).__name__}: {e}"
    except AgentRunError as e:  # anything else from the run
        turn["said"] = "Something went wrong, please try again."
        turn["error"] = f"{type(e).__name__}: {e}"

    elapsed = round((time.perf_counter() - start) * 1000)
    turn["latency_ms"]["llm"] = turn["latency_ms"]["total"] = elapsed
    return turn
