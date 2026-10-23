# 0035. Learn each Item's Product from what was placed in past Orders; Claude matches, code picks

- Status: Accepted
- Date: 2026-10-23
- Related: FR-0.34 to FR-0.39 (v0.17). Builds on 0026 (one item table), 0034 (the extension). An exception to 0018 (one model request per command) for "analyze my order" and "order the groceries".

## Context
The owner says "eggs", Wegmans sells "Wegmans Grade AA Large Eggs, 18 Count". Kiki has to know which Product each Item is, without asking every time and without picking a different eggs each week. Past Orders know: every line has the Product that was placed. Shoppers replace things often (four lines in the Oct 3 order), and the substitute isn't what the household chose.

## Options considered
- Store only two columns on `items` (the Product's id and name): smaller, but an Item's eggs change over time and the history of what was bought would be lost.
- A `products` table, `orders` and `order_lines`, with `items.product_id`: each name stored once, the history kept.
- Pick the Product in Claude's request: one step, but the same history could give a different answer each time.
- Claude says which Products are which Item; code picks among them.

## Decision
`products(id, name)`, `orders(id, delivered_at)`, `order_lines(order_id, product_id, quantity, status)` and `items.product_id`. A line's Product is what was **placed**, never the substitute; its status is `found`, `substituted` or `missing` (CONTEXT.md's words, not Instacart's). Only delivered Orders from `KIKI_STORE` to `KIKI_ADDRESS` are kept; the first read keeps the seven newest. An Order with anything Kiki doesn't recognise (a new status word, a line without a Product, fewer lines than the order history says) isn't saved and is reported.

Matching an Item without a Product is one Claude request with the Items' names and the placed Products' names; it returns, for each Item, every Product that is that Item. Code then picks the one in the most Orders, the most recent on a tie. Analysis only fills Items without a Product; it never changes one the owner chose. The owner changes or forgets a Product by voice ("use Diamond walnuts for walnuts", "forget the walnut product") or with Forget on the Tab5's item sheet.

"Analyze my order" and "order the groceries" may make that second request. They are rare, deliberate commands, not the everyday voice path, so 0018's latency reason doesn't apply to them. Kiki writes their spoken reply itself from what happened, since the model's `reply` is written before anything ran.

## Consequences
+ The same history always gives the same Product; a shopper's swap never becomes the household's choice.
+ Matching costs one small request, only when an Item has no Product.
+ The record of what each Order got is there for the List reset and Missing items later.
- A wrong match stays until the owner changes it; Analysis doesn't revisit Items that have a Product.
- An Item that has never been ordered gets a search result for that Cart only (one the Store tags "Buy it again" first), until it shows up in a delivered Order.
