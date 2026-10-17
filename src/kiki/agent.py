"""One command in, one `turn` event out, via Pydantic AI (ADR 0015).

Single-turn: no history (ADR 0009). The model is a "provider:name" string from KIKI_MODEL,
so swapping providers is an env change.
"""

import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import (
    AgentRunError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from kiki import tools

DEFAULT_MODEL = "anthropic:claude-haiku-5-5"
DIDNT_CATCH = "Sorry, I didn't catch that."

INSTRUCTIONS = """You manage a household grocery list by voice. Replies are spoken aloud: one or two \
short sentences, no markdown, bullets or emojis, numbers written as words ("two milks").

Rules:
- Use the tools for every change. Each request is independent; you only know the current list.
- Fix obvious speech-to-text slips ("bred" means bread). Use plain item names ("rice", not "some rice").
- If an item is already on the list, say so and don't change it. Only change a quantity when the \
user explicitly asks ("add another milk", "make it three milks"); compute the new number from the \
list and call set_quantity.
- Removing an item deletes it completely, whatever its quantity.
- When asked what's on the list, read every item.
- After clearing the list, say only how many items were removed ("Cleared five items.").
- If you can't tell what the user wants, reply exactly "Sorry, I didn't catch that." and call no tools."""


os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


@dataclass
class Deps:
    conn: sqlite3.Connection
    list_at_start: str
    tool_calls: list[dict] = field(default_factory=list)


class Item(BaseModel):
    name: str = Field(description="Item name as spoken, e.g. 'eggs'")
    quantity: int = Field(default=1, ge=1)


agent = Agent(
    deps_type=Deps,
    instructions=INSTRUCTIONS,
    model_settings=ModelSettings(thinking="low", max_tokens=4096),
    retries=2,
)


@agent.instructions
def current_list(ctx: RunContext[Deps]) -> str:
    # Pydantic AI re-renders instructions on every model request, so this must be the snapshot
    # from the start of the turn. A live read would show "bread x2" after the first set_quantity
    # and "add another bread" would bump it again.
    return f"Current list at the start of this request: {ctx.deps.list_at_start}"


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


@agent.tool
def add_items(ctx: RunContext[Deps], items: list[Item]) -> dict:
    """Add one or more items. Items already on the list are left unchanged and returned in already_present."""
    return _call(ctx, "add_items", items=[i.model_dump() for i in items])


@agent.tool
def set_quantity(
    ctx: RunContext[Deps], name: str, quantity: Annotated[int, Field(ge=1)]
) -> dict:
    """Set the quantity of an item already on the list. Only for explicit requests like 'add another milk' or 'make it three milks'."""
    return _call(ctx, "set_quantity", name=name, quantity=quantity)


@agent.tool
def remove_items(ctx: RunContext[Deps], names: list[str]) -> dict:
    """Remove one or more items completely, whatever their quantity."""
    return _call(ctx, "remove_items", names=names)


@agent.tool
def read_list(ctx: RunContext[Deps]) -> dict:
    """Return every item on the list."""
    return _call(ctx, "read_list")


@agent.tool
def clear_list(ctx: RunContext[Deps]) -> dict:
    """Remove every item from the list immediately."""
    return _call(ctx, "clear_list")


@agent.output_validator
def spoken_style(output: str) -> str:
    """FR-0.10 guard: a reply must be speakable. (Empty replies are retried by Pydantic AI itself.)"""
    output = output.strip()
    if re.search(r"[*#`•_]|^\s*-\s|\d", output, re.MULTILINE):
        raise ModelRetry(
            "Spoken reply: no markdown or bullets, write numbers as words."
        )
    return output


def run_turn(
    command: str,
    conn: sqlite3.Connection,
    model: Model | str | None = None,
    source: str = "text",
) -> dict:
    start = time.perf_counter()
    now = datetime.now(UTC)
    model = model or os.environ.get("KIKI_MODEL", DEFAULT_MODEL)
    deps = Deps(conn, _snapshot(conn))
    turn = {
        "type": "turn",
        "id": f"t_{now:%Y%m%dT%H%M%S}_{secrets.token_hex(2)}",
        "ts": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": source,
        "heard": command,
        "tool_calls": deps.tool_calls,
        "said": "",
        "model": model if isinstance(model, str) else model.model_name,
        "latency_ms": {"stt": None, "llm": 0, "tts": None, "total": 0},
        "error": None,
    }

    try:
        result = agent.run_sync(
            command, model=model, deps=deps, usage_limits=UsageLimits(request_limit=6)
        )
        turn["said"] = result.output
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
    except AgentRunError as e:  # usage limit and anything else from the run
        turn["said"] = "Something went wrong, please try again."
        turn["error"] = f"{type(e).__name__}: {e}"

    elapsed = round((time.perf_counter() - start) * 1000)
    turn["latency_ms"]["llm"] = turn["latency_ms"]["total"] = elapsed
    return turn
