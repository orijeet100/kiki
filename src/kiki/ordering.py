"""Ordering (v0.17): learn each Item's Product from past Orders, then fill the Cart.

Flows over the plain tools (ADR 0008), the Instacart extension (kiki.instacart) and one
Claude request that says which placed Products are which Item (ADR 0035). Each returns JSON
for the turn log; an extension failure raises InstacartError and the caller says why.
"""

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError, ModelAPIError
from pydantic_ai.models import infer_model
from pydantic_ai.settings import ModelSettings

from kiki import instacart, tools

# Instacart's line status -> CONTEXT.md's words. Anything else stops that Order (FR-0.36).
STATUSES = {"found": "found", "replaced": "substituted"}
FIRST_ORDERS = (
    7  # the first read keeps the 7 newest Orders; later reads keep every new one
)

MATCH_INSTRUCTIONS = """You link a household's grocery items to products they have ordered.
For each item, list the id of every product that is that item: the same food, any brand, size or
pack ("eggs" is "Wegmans Grade AA Large Eggs, 18 Count"; "yogurt" is not "yogurt bars").
Give an empty list when no product is the item. Use only ids from the product list."""


class Match(BaseModel):
    item: str = Field(description="The item exactly as listed")
    product_ids: list[int] = Field(description="Every listed product that is this item")


def match_products(items: list[str], products: list[dict]) -> dict[str, list[int]]:
    """One Claude request: which of these Products is each Item (ADR 0035)."""
    from kiki.agent import model_name  # agent imports this module

    agent = Agent(output_type=list[Match], instructions=MATCH_INSTRUCTIONS)
    prompt = (
        "Items:\n"
        + "\n".join(items)
        + "\n\nProducts:\n"
        + "\n".join(f"{p['id']}: {p['name']}" for p in products)
    )
    settings = ModelSettings(thinking="low", max_tokens=8192, timeout=60)
    # Its own thread: this runs inside the command's agent run, where Pydantic AI refuses a
    # nested run_sync (it could deadlock), and a new thread starts outside that run.
    with ThreadPoolExecutor(1) as thread:
        run = thread.submit(
            agent.run_sync,
            prompt,
            model=infer_model(model_name()),
            model_settings=settings,
        )
        matches = run.result().output
    known = {p["id"] for p in products}
    by_key = {tools.normalize(i): i for i in items}
    return {
        by_key[tools.normalize(m.item)]: [i for i in m.product_ids if i in known]
        for m in matches
        if tools.normalize(m.item) in by_key
    }


def order_lines(order: dict) -> tuple[list[dict] | None, str | None]:
    """An Order's lines in Kiki's words, or None and why it can't be trusted (FR-0.36)."""
    lines = []
    for line in order["lines"]:
        status = STATUSES.get(line.get("status"))
        if status is None:
            return None, f"unknown status {line.get('status')!r}"
        if not str(line.get("product_id") or "").isdigit() or not line.get(
            "product_name"
        ):
            return None, "a line without a product"
        if not isinstance(line.get("quantity"), int | float):
            return None, "a line without a quantity"
        lines.append(
            {
                "product_id": int(line["product_id"]),
                "product_name": line["product_name"],
                "quantity": max(1, round(line["quantity"])),
                "status": status,
            }
        )
    if order.get("list_items") is not None and order["list_items"] != len(lines):
        return (
            None,
            f"{len(lines)} lines but the order history says {order['list_items']}",
        )
    return lines, None


def read_new_orders(conn, browse) -> dict:
    """Save the Store's delivered Orders to the Address that Kiki hasn't read yet."""
    known = tools.known_order_ids(conn)
    orders = [
        o
        for o in browse("read_orders", known=known)["orders"]
        if o.get("state") == "delivered"
        and (o.get("address") or "").startswith(instacart.ADDRESS)
    ]
    if not known:
        orders = orders[:FIRST_ORDERS]  # the order history is newest first
    saved, unreadable = [], []
    for o in orders:
        lines, why = order_lines(o)
        if lines is None:
            unreadable.append({"order_id": o["id"], "why": why})
            continue
        tools.save_order(
            conn, {"id": o["id"], "delivered_at": o["delivered_at"], "lines": lines}
        )
        saved.append(o["id"])
    return {"new_orders": len(saved), "unreadable_orders": unreadable}


def fill_gaps(conn, names: list[str], match) -> dict:
    """Give each of these Items the Product it was ordered as most often (FR-0.37)."""
    products = tools.placed_products(conn)
    matched, no_product = [], []
    matches = match(names, products) if names and products else {}
    for name in names:
        best = tools.preferred_product(conn, matches.get(name, []))
        if best:
            tools.set_product_for_item(conn, name, best["id"], best["name"])
            matched.append({"name": name, "product_name": best["name"]})
        else:
            no_product.append(name)
    return {"matched": matched, "no_product": no_product}


def learn_product_preferences(conn, browse=None, match=None) -> dict:
    """ "Analyze my order": read new Orders, then link every Item without a Product (FR-0.36)."""
    result = read_new_orders(conn, browse or instacart.run_job)
    result.update(
        fill_gaps(conn, tools.items_without_product(conn), match or match_products)
    )
    return result


def fill_cart(conn, browse=None, match=None) -> dict:
    """ "Order the groceries": every Needed Item into the Store's Cart at its quantity (FR-0.39)."""
    browse = browse or instacart.run_job
    if not tools.cart_lines(conn):
        return {"lines": []}
    result = read_new_orders(conn, browse)
    gaps = [line["name"] for line in tools.cart_lines(conn) if not line["product_id"]]
    if gaps:
        try:
            result.update(fill_gaps(conn, gaps, match or match_products))
        except (AgentRunError, ModelAPIError):
            result["matching_failed"] = True  # top search results instead (FR-0.40)
    lines = [
        {
            "item": line["name"],
            "product_id": line["product_id"] and str(line["product_id"]),
            "query": line["name"],
            "quantity": line["quantity"],
        }
        for line in tools.cart_lines(conn)
    ]
    result["lines"] = browse("fill_cart", address=instacart.ADDRESS, lines=lines)[
        "lines"
    ]
    return result


def choose_product(conn, name: str, query: str, browse=None) -> dict:
    """ "Use Diamond walnuts for walnuts": a placed Product first, else the top search result."""
    words = [tools.normalize(w) for w in query.split()]
    placed = [
        p
        for p in tools.placed_products(conn)
        if all(w in p["name"].lower() for w in words)
    ]
    if placed:
        pick = placed[0]  # most Orders, then most recent
    else:
        results = (browse or instacart.run_job)("search", query=query)["results"]
        if not results:
            return {"no_results": query}
        # "Buy it again" first: the household has had it before.
        top = next((r for r in results if r.get("bought")), results[0])
        pick = {"id": int(top["id"]), "name": top["name"] or query}
    return tools.set_product_for_item(conn, name, int(pick["id"]), pick["name"])
