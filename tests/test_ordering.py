"""Ordering (v0.17) without Chrome or the network: a fake extension and a fake matcher."""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from kiki import agent, instacart, ordering, tools
from kiki.db import connect

ADDRESS = "1 Test Street"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(instacart, "ADDRESS", ADDRESS)
    return connect(str(tmp_path / "test.db"))


def line(product_id, name, status="found", quantity=1):
    return {
        "status": status,
        "quantity": quantity,
        "quantity_type": "each",
        "product_id": str(product_id),
        "product_name": name,
    }


def order(order_id, delivered_at, *lines, address=ADDRESS + ", 3203", items=None):
    """An order as the extension reads it (browser/instacart/worker.js, op "order")."""
    return {
        "id": order_id,
        "retailer": "wegmans",
        "address": address,
        "delivered_at": delivered_at,
        "state": "delivered",
        "lines": list(lines),
        "list_items": len(lines) if items is None else items,
    }


class Extension:
    """Stands in for run_job: answers each kind of job and records what it was asked."""

    def __init__(self, orders=(), search=(), fill=None):
        self.orders, self.search, self.fill = list(orders), list(search), fill
        self.jobs = []

    def __call__(self, kind, **payload):
        self.jobs.append((kind, payload))
        if kind == "read_orders":
            return {
                "orders": [o for o in self.orders if o["id"] not in payload["known"]]
            }
        if kind == "search":
            return {"results": self.search}
        if kind == "fill_cart":
            if self.fill:
                return {"lines": self.fill(payload["lines"])}
            return {
                "lines": [
                    {
                        **x,
                        "status": "added" if x["product_id"] else "top_match",
                        "product_name": "P",
                    }
                    for x in payload["lines"]
                ]
            }
        raise AssertionError(kind)


def by_name(mapping):
    """A matcher from item name to the product names that are it."""

    def match(items, products):
        ids = {p["name"]: p["id"] for p in products}
        return {i: [ids[n] for n in mapping.get(i, []) if n in ids] for i in items}

    return match


OCT_13 = order(
    "1012",
    "2026-10-13T04:18:24Z",
    line(45195038, "Wegmans Boneless, Skinless Chicken Thighs, FAMILY PACK"),
    line(16963479, "Wegmans 0% Greek Plain Nonfat Yogurt", status="replaced"),
    line(17499428, "Wegmans Onions, Red"),
)
OCT_21 = order(
    "1021",
    "2026-10-21T21:48:44Z",
    line(16961005, "Wegmans Grade AA Large Eggs, 18 Count", quantity=3),
    line(17499428, "Wegmans Onions, Red"),
)


def test_fr_0_34_list_rows_carry_the_product(conn):
    tools.add_items(conn, [{"name": "eggs"}, {"name": "milk"}])
    tools.set_product_for_item(
        conn, "eggs", 16961005, "Wegmans Grade AA Large Eggs, 18 Count"
    )
    rows = {i["name"]: i["product_name"] for i in tools.read_list(conn)["items"]}
    assert rows == {"eggs": "Wegmans Grade AA Large Eggs, 18 Count", "milk": None}


def test_fr_0_35_reset_list_starts_the_list_over(conn):
    tools.add_items(
        conn,
        [{"name": "chicken"}, {"name": "tomatoes", "quantity": 6}, {"name": "walnuts"}],
    )
    tools.set_usual_quantity(conn, "tomatoes", 4)
    tools.set_quantity(conn, "tomatoes", 6)
    tools.set_buying_pattern(conn, "chicken", "frequent")
    tools.set_buying_pattern(conn, "tomatoes", "frequent")
    tools.remove_items(conn, ["chicken"])

    result = tools.reset_list(conn)

    assert result == {
        "needed": [
            {"name": "chicken", "quantity": 1},
            {"name": "tomatoes", "quantity": 4},
        ]
    }
    rows = {
        i["name"]: (i["status"], i["quantity"]) for i in tools.read_list(conn)["items"]
    }
    assert rows == {
        "chicken": ("needed", 1),
        "tomatoes": ("needed", 4),
    }  # walnuts: off the List


def test_fr_0_36_saves_what_was_placed_never_the_substitute(conn):
    ext = Extension(orders=[OCT_13])
    result = ordering.read_new_orders(conn, ext)
    assert result == {"new_orders": 1, "unreadable_orders": []}
    lines = conn.execute(
        "SELECT product_id, status FROM order_lines ORDER BY product_id"
    ).fetchall()
    assert [tuple(r) for r in lines] == [
        (16963479, "substituted"),  # the yogurt that was placed, not the one that came
        (17499428, "found"),
        (45195038, "found"),
    ]


def test_fr_0_36_reads_only_new_orders_to_the_address(conn):
    elsewhere = order(
        "2000", "2026-10-22T00:00:00Z", line(1, "Corn"), address="3049 Kennedy Blvd"
    )
    ext = Extension(orders=[OCT_21, OCT_13, elsewhere])
    assert ordering.read_new_orders(conn, ext)["new_orders"] == 2
    assert ordering.read_new_orders(conn, ext)["new_orders"] == 0
    assert set(ext.jobs[1][1]["known"]) == {"1012", "1021"}


def test_fr_0_36_the_first_read_keeps_the_seven_newest(conn):
    orders = [
        order(str(9000 - n), f"2026-09-{20 - n:02d}T00:00:00Z", line(n + 1, f"P{n}"))
        for n in range(9)
    ]
    assert ordering.read_new_orders(conn, Extension(orders=orders))["new_orders"] == 7
    assert "8991" not in tools.known_order_ids(conn)  # the oldest two are left


@pytest.mark.parametrize(
    "bad, why",
    [
        (
            order("1", "2026-10-01T00:00:00Z", line(1, "A", status="refunded")),
            "unknown status 'refunded'",
        ),
        (
            order("1", "2026-10-01T00:00:00Z", line(1, "A"), items=2),
            "1 lines but the order history says 2",
        ),
        (
            order("1", "2026-10-01T00:00:00Z", {**line(1, "A"), "product_id": None}),
            "a line without a product",
        ),
    ],
)
def test_fr_0_36_an_order_that_cant_be_trusted_is_not_saved(conn, bad, why):
    result = ordering.read_new_orders(conn, Extension(orders=[bad]))
    assert result == {
        "new_orders": 0,
        "unreadable_orders": [{"order_id": "1", "why": why}],
    }
    assert tools.known_order_ids(conn) == []


def test_fr_0_36_analyze_links_only_items_without_a_product(conn):
    tools.add_items(conn, [{"name": "eggs"}, {"name": "onion"}, {"name": "celery"}])
    tools.set_product_for_item(
        conn, "onion", 555, "Organic Red Onion"
    )  # chosen before: kept
    match = by_name(
        {
            "eggs": ["Wegmans Grade AA Large Eggs, 18 Count"],
            "onion": ["Wegmans Onions, Red"],
        }
    )

    result = ordering.learn_product_preferences(conn, Extension(orders=[OCT_21]), match)

    assert result["matched"] == [
        {"name": "eggs", "product_name": "Wegmans Grade AA Large Eggs, 18 Count"}
    ]
    assert result["no_product"] == ["celery"]
    rows = {i["name"]: i["product_name"] for i in tools.read_list(conn)["items"]}
    assert rows["onion"] == "Organic Red Onion"


def test_fr_0_37_most_orders_wins_then_the_most_recent(conn):
    ext = Extension(
        orders=[
            order(
                "1",
                "2026-09-01T00:00:00Z",
                line(10, "Chicken Breast"),
                line(20, "Chicken Thighs"),
            ),
            order("2", "2026-09-08T00:00:00Z", line(10, "Chicken Breast")),
            order(
                "3",
                "2026-09-15T00:00:00Z",
                line(20, "Chicken Thighs"),
                line(30, "Whole Chicken"),
            ),
        ]
    )
    ordering.read_new_orders(conn, ext)
    assert (
        tools.preferred_product(conn, [10, 20, 30])["name"] == "Chicken Thighs"
    )  # 2 each, newer
    assert (
        tools.preferred_product(conn, [10, 30])["name"] == "Chicken Breast"
    )  # 2 orders vs 1
    assert tools.preferred_product(conn, []) is None


def test_fr_0_38_choose_product_prefers_a_placed_product_then_search(conn):
    tools.add_items(conn, [{"name": "onion"}, {"name": "walnuts"}])
    ordering.read_new_orders(conn, Extension(orders=[OCT_21]))
    ext = Extension(search=[{"id": "18787423", "name": "Diamond Walnuts, Shelled"}])

    assert ordering.choose_product(conn, "onion", "red onions", ext) == {
        "name": "onion",
        "product_name": "Wegmans Onions, Red",
    }
    assert ext.jobs == []  # found in past Orders, no browsing
    assert (
        ordering.choose_product(conn, "walnuts", "Diamond walnuts", ext)["product_name"]
        == "Diamond Walnuts, Shelled"
    )
    assert ordering.choose_product(conn, "walnuts", "unobtainium", Extension()) == {
        "no_results": "unobtainium"
    }


def test_fr_0_38_forget_the_product(conn):
    tools.add_items(conn, [{"name": "walnuts"}])
    tools.set_product_for_item(conn, "walnuts", 1, "Diamond Walnuts")
    assert tools.forget_product_for_item(conn, "walnuts") == {"name": "walnuts"}
    assert tools.items_without_product(conn) == ["walnuts"]
    assert tools.forget_product_for_item(conn, "kale") == {"not_found": "kale"}


def test_fr_0_39_fill_cart_sends_every_needed_item_at_its_quantity(conn):
    tools.add_items(
        conn, [{"name": "eggs", "quantity": 3}, {"name": "walnuts"}, {"name": "kale"}]
    )
    tools.remove_items(conn, ["kale"])
    match = by_name({"eggs": ["Wegmans Grade AA Large Eggs, 18 Count"]})
    ext = Extension(orders=[OCT_21])

    result = ordering.fill_cart(conn, ext, match)

    kind, payload = ext.jobs[-1]
    assert kind == "fill_cart" and payload["address"] == ADDRESS
    assert payload["lines"] == [
        {"item": "eggs", "product_id": "16961005", "query": "eggs", "quantity": 3},
        {"item": "walnuts", "product_id": None, "query": "walnuts", "quantity": 1},
    ]
    assert [x["status"] for x in result["lines"]] == ["added", "top_match"]


def test_fr_0_39_an_empty_list_fills_nothing(conn):
    ext = Extension()
    assert ordering.fill_cart(conn, ext) == {"lines": []}
    assert ext.jobs == []


def test_fr_0_40_matching_down_falls_back_to_top_matches(conn):
    from pydantic_ai.exceptions import ModelAPIError

    def down(items, products):
        raise ModelAPIError("anthropic", "no internet")

    tools.add_items(conn, [{"name": "eggs"}])
    result = ordering.fill_cart(conn, Extension(orders=[OCT_21]), down)
    assert result["matching_failed"] is True
    assert result["lines"][0]["status"] == "top_match"


# The voice side: the agent turns ordering results into the spoken reply.


def says(**args):
    """A model that calls update_list once with these arguments."""
    return FunctionModel(
        lambda messages, info: ModelResponse(parts=[ToolCallPart("update_list", args)])
    )


def test_fr_0_39_order_the_groceries_says_what_landed(conn, monkeypatch):
    tools.add_items(
        conn, [{"name": "eggs"}, {"name": "blueberries"}, {"name": "walnuts"}]
    )

    def fill(lines):
        status = {"eggs": "added", "blueberries": "failed", "walnuts": "top_match"}
        return [{**x, "status": status[x["item"]], "product_name": "P"} for x in lines]

    monkeypatch.setattr(instacart, "run_job", Extension(fill=fill))
    turn = agent.run_turn(
        "order the groceries", conn, says(fill_cart=True, reply="On it!")
    )

    assert turn["said"] == (
        "Your cart is ready with two items. "
        "Blueberries failed, and one was a top match, details on the screen."
    )
    assert turn["tool_calls"][-1]["name"] == "fill_cart"


def test_fr_0_36_analyze_my_order_says_how_many_matched(conn, monkeypatch):
    tools.add_items(conn, [{"name": "eggs"}, {"name": "celery"}])
    monkeypatch.setattr(instacart, "run_job", Extension(orders=[OCT_21]))
    monkeypatch.setattr(
        ordering,
        "match_products",
        by_name({"eggs": ["Wegmans Grade AA Large Eggs, 18 Count"]}),
    )
    turn = agent.run_turn(
        "analyze my order", conn, says(learn_product_preferences=True, reply="Sure.")
    )
    assert (
        turn["said"]
        == "Matched one item to your products. One item still has no product."
    )


def test_fr_0_38_use_a_product_by_voice(conn, monkeypatch):
    tools.add_items(conn, [{"name": "walnuts"}])
    monkeypatch.setattr(
        instacart,
        "run_job",
        Extension(search=[{"id": "18787423", "name": "Diamond Walnuts, Shelled"}]),
    )
    turn = agent.run_turn(
        "use diamond walnuts for walnuts",
        conn,
        says(
            set_products=[{"name": "walnuts", "product": "Diamond walnuts"}],
            reply="Okay.",
        ),
    )
    assert turn["said"] == "Walnuts is now Diamond Walnuts."
    turn = agent.run_turn(
        "forget the walnut product",
        conn,
        says(forget_products=["walnuts"], reply="Okay."),
    )
    assert turn["said"] == "Walnuts has no product now."


@pytest.mark.parametrize(
    "code, said",
    [
        ("signed_out", "Instacart needs you in Chrome on the laptop."),
        ("needs_human", "Instacart needs you in Chrome on the laptop."),
        ("page_changed", "I couldn't finish, Instacart changed its page."),
        (
            "wrong_address",
            f"Instacart is set to another address. Switch it to {instacart.ADDRESS} in Chrome.",
        ),
        ("no_answer", "I can't reach Instacart in Chrome. Is the Kiki extension on?"),
    ],
)
def test_fr_0_40_an_instacart_failure_is_said_plainly(conn, monkeypatch, code, said):
    tools.add_items(conn, [{"name": "eggs"}])

    def fail(kind, **payload):
        raise instacart.InstacartError(code)

    monkeypatch.setattr(instacart, "run_job", fail)
    turn = agent.run_turn(
        "order the groceries", conn, says(fill_cart=True, reply="On it.")
    )
    assert turn["said"] == said
    assert turn["tool_calls"][-1]["result"] == {"failed": code}
    assert tools.known_order_ids(conn) == []
