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
from typing import Literal

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

from kiki import ordering, tools
from kiki.instacart import ADDRESS, InstacartError

DEFAULT_MODEL = "anthropic:claude-haiku-5-5"
DIDNT_CATCH = "Sorry, I didn't catch that."

INSTRUCTIONS = """You manage a household grocery list by voice. Replies are spoken aloud: one or two \
short sentences, no markdown, bullets or emojis, numbers written as words ("two milks").

Every item is frequent (bought often, always on the list) or occasional (on the list only while \
needed), and needed (goes in the next order) or not needed.

Rules:
- To change the list, call update_list once with every change from the sentence and the spoken \
reply. Each request is independent; you only know the current list below.
- Questions about the list are answered in plain text from the current list, with no call.
- Fix obvious speech-to-text slips ("bred" means bread). Use plain item names ("rice", not "some rice").
- Adding puts the item in add, with a quantity only if the user said a number. If an item is \
already needed, say so and don't change it.
- Only change a quantity when the user explicitly asks ("add another milk", "make it three \
milks"); compute the new number from the list and put it in set_quantities. "We usually get \
three tomatoes" goes in set_usual_quantities.
- "Remove", "not this time" and "got the X" (bought) put the item in remove: it becomes not \
needed. Speech-to-text often hears "got the" as "cut", "dot" or "gut". Nothing is ever deleted.
- "Make chicken frequent" goes in set_buying_patterns. "We don't buy X any more": make it \
occasional and remove it.
- "Call yogurt Greek yogurt" goes in renames.
- When asked what's on the list, read every needed item, then only the number of frequent items \
that are not needed, without naming them ("Milk, eggs and bread. Two more are off this time."). \
With nothing needed, reply "Your list is empty."
- After clearing the list, say only how many items were taken off ("Cleared five items.").
- "Analyze my order" sets learn_product_preferences. "Order the groceries" or "fill the cart" \
sets fill_cart: Kiki puts the needed items in the store's cart, and the user checks out. Kiki \
never places or pays for an order.
- "Use Diamond walnuts for walnuts" goes in set_products (name walnuts, product "Diamond \
walnuts"). "Forget the walnut product" goes in forget_products.
- For those four, any short reply will do: Kiki replaces it with what actually happened.
- If you can't tell what the user wants, reply exactly "Sorry, I didn't catch that." in plain text."""


os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")


@dataclass
class Deps:
    conn: sqlite3.Connection
    list_at_start: str
    tool_calls: list[dict] = field(default_factory=list)
    # Replies Kiki writes itself from what ordering did; they replace the model's reply.
    replies: list[str] = field(default_factory=list)


class Item(BaseModel):
    name: str = Field(description="Item name as spoken, e.g. 'eggs'")
    quantity: int | None = Field(
        default=None, ge=1, description="Only when the user said a number"
    )


class Quantity(BaseModel):
    name: str
    quantity: int = Field(ge=1)


class BuyingPattern(BaseModel):
    name: str
    buying_pattern: Literal["frequent", "occasional"]


class Rename(BaseModel):
    name: str
    new_name: str


class ProductChoice(BaseModel):
    name: str = Field(description="Item name, e.g. 'walnuts'")
    product: str = Field(description="The product as said, e.g. 'Diamond walnuts'")


NUMBERS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def spoken(n: int) -> str:
    """Numbers the way they are spoken (FR-0.10), up to ninety-nine."""
    if n < 20:
        return NUMBERS[n]
    if n < 100:
        return TENS[n // 10 - 2] + ("-" + NUMBERS[n % 10] if n % 10 else "")
    return "many"


def items(n: int) -> str:
    return f"{spoken(n)} item{'' if n == 1 else 's'}"


def product_said(name: str) -> str:
    """A Product name to say aloud: without the size after the comma."""
    return name.split(",")[0].strip()


# Why an Instacart job stopped, said plainly (FR-0.40).
INSTACART_SAYS = {
    "signed_out": "Instacart needs you in Chrome on the laptop.",
    "needs_human": "Instacart needs you in Chrome on the laptop.",
    "wrong_address": f"Instacart is set to another address. Switch it to {ADDRESS} in Chrome.",
    "page_changed": "I couldn't finish, Instacart changed its page.",
    "no_page": "Instacart didn't load. Try again in a minute.",
}
NO_EXTENSION = "I can't reach Instacart in Chrome. Is the Kiki extension on?"


def learned_reply(result: dict) -> str:
    matched, left = len(result["matched"]), len(result["no_product"])
    if not result["new_orders"] and not matched:
        first = "No new orders, and nothing new to match."
    else:
        first = f"Matched {items(matched)} to your products."
    if result["unreadable_orders"]:
        return first + " I couldn't read one of your orders."
    if not left:
        return first
    return f"{first} {items(left).capitalize()} still {'has' if left == 1 else 'have'} no product."


def cart_reply(result: dict) -> str:
    lines = result["lines"]
    if not lines:
        return "Your list is empty, so there's nothing to add."
    added = [line for line in lines if line["status"] != "failed"]
    failed = [line["item"] for line in lines if line["status"] == "failed"]
    guessed = sum(line["status"] == "top_match" for line in lines)
    if not added:
        return "I couldn't add anything to your cart."
    first = f"Your cart is ready with {items(len(added))}."
    if result.get("matching_failed"):
        return first + " I couldn't check your past orders, so I used top matches."
    parts = []
    if failed:
        parts.append(
            f"{failed[0]} failed"
            if len(failed) == 1
            else f"{items(len(failed))} failed"
        )
    if guessed:
        parts.append(
            f"{spoken(guessed)} {'was a top match' if guessed == 1 else 'were top matches'}"
        )
    if not parts:
        return first
    said = ", and ".join(parts) + ", details on the screen."
    return f"{first} {said[0].upper()}{said[1:]}"


def chosen_reply(result: dict) -> str:
    if "not_found" in result:
        return f"{result['not_found'].capitalize()} isn't on your list."
    if "no_results" in result:
        return f"I couldn't find {result['no_results']}."
    return (
        f"{result['name'].capitalize()} is now {product_said(result['product_name'])}."
    )


def forgotten(conn: sqlite3.Connection, name: str) -> dict:
    return tools.forget_product_for_item(conn, name)


def forgotten_reply(result: dict) -> str:
    if "not_found" in result:
        return f"{result['not_found'].capitalize()} isn't on your list."
    return f"{result['name'].capitalize()} has no product now."


def _order(ctx: RunContext[Deps], tool: str, run, reply, /, **args) -> dict:
    """Run an ordering step, log it like a tool, and say what happened instead of the model."""
    try:
        result = run(ctx.deps.conn, **args)
        ctx.deps.replies.append(reply(result))
    except InstacartError as e:
        result = {"failed": e.code}
        ctx.deps.replies.append(INSTACART_SAYS.get(e.code, NO_EXTENSION))
    except (AgentRunError, ModelAPIError) as e:  # the matching request
        result = {"failed": f"{type(e).__name__}: {e}"}
        ctx.deps.replies.append("I couldn't match your products, please try again.")
    except Exception as e:  # noqa: BLE001 -- a bug in ordering must not leave the turn hanging
        result = {"failed": f"{type(e).__name__}: {e}"}
        ctx.deps.replies.append(
            "Something went wrong with Instacart, please try again."
        )
    ctx.deps.tool_calls.append({"name": tool, "args": args, "result": result})
    return result


def _snapshot(conn: sqlite3.Connection) -> str:
    items = tools.read_list(conn)["items"]
    return (
        ", ".join(
            f"{i['name']} x{i['quantity']} ({i['buying_pattern']}, {i['status'].replace('_', ' ')})"
            for i in items
        )
        or "(empty)"
    )


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
    set_quantities: list[Quantity] | None = None,
    set_usual_quantities: list[Quantity] | None = None,
    set_buying_patterns: list[BuyingPattern] | None = None,
    renames: list[Rename] | None = None,
    clear: bool = False,
    learn_product_preferences: bool = False,
    fill_cart: bool = False,
    set_products: list[ProductChoice] | None = None,
    forget_products: list[str] | None = None,
) -> str:
    """Make every list change the user asked for, in one call, and give the spoken reply.

    Args:
        reply: What to say back: one short sentence (two at most), written from the current list.
        add: Items to make needed. Items already needed stay unchanged; say so in the reply.
        remove: Items to make not needed, whatever their quantity. Nothing is deleted.
        set_quantities: Quantities for the next order, only when asked explicitly.
        set_usual_quantities: Usual quantities, only when the user says what they usually get.
        set_buying_patterns: Make items frequent or occasional.
        renames: New names for existing items.
        clear: True to make every item not needed.
        learn_product_preferences: True for "analyze my order".
        fill_cart: True for "order the groceries": fill the store's cart, never check out.
        set_products: The product to use for an item from now on.
        forget_products: Items whose product to forget.
    """
    # Every step is idempotent, so a retry after ModelRetry can safely re-apply them.
    if clear:
        _call(ctx, "clear_all_items")
    if remove:
        _call(ctx, "remove_items", names=remove)
    if add:
        _call(ctx, "add_items", items=[i.model_dump(exclude_none=True) for i in add])
    for change in set_quantities or []:
        _call(ctx, "set_quantity", name=change.name, quantity=change.quantity)
    for change in set_usual_quantities or []:
        _call(ctx, "set_usual_quantity", name=change.name, quantity=change.quantity)
    for change in set_buying_patterns or []:
        _call(
            ctx,
            "set_buying_pattern",
            name=change.name,
            buying_pattern=change.buying_pattern,
        )
    for change in renames or []:
        _call(ctx, "rename_item", name=change.name, new_name=change.new_name)
    # Ordering runs after the list changes, so "add milk and order the groceries" has milk.
    for name in forget_products or []:
        _order(ctx, "forget_product_for_item", forgotten, forgotten_reply, name=name)
    for choice in set_products or []:
        _order(
            ctx,
            "set_product_for_item",
            ordering.choose_product,
            chosen_reply,
            name=choice.name,
            query=choice.product,
        )
    if learn_product_preferences:
        _order(
            ctx,
            "learn_product_preferences",
            ordering.learn_product_preferences,
            learned_reply,
        )
    if fill_cart:
        _order(ctx, "fill_cart", ordering.fill_cart, cart_reply)
    return " ".join(ctx.deps.replies[-2:]) if ctx.deps.replies else reply


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
def spoken_style(ctx: RunContext[Deps], output: str) -> str:
    """FR-0.10 guard: a reply must be speakable. (Empty replies are retried by Pydantic AI itself.)

    Kiki's own ordering replies pass as they are: a retry would run the ordering again.
    """
    output = output.strip()
    if ctx.deps.replies:
        return output
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


# ponytail: one turn at a time for the whole process. Voice, the UI's text box and list clicks
# share one SQLite connection, and a household never needs two commands in parallel.
turn_lock = threading.Lock()


def run_turn(
    command: str,
    conn: sqlite3.Connection,
    model: Model | str | None = None,
    source: str = "text",
) -> dict:
    with turn_lock:
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
