# 0026. One item table holds both the item and its state for the next order

- Status: Accepted
- Date: 2026-10-18
- Related: FR-0.19 to FR-0.27 (v0.12); replaces FR-0.5, FR-0.6, FR-0.7. Keeps 0006 (SQLite), 0012 (clear without confirmation). Terms in [CONTEXT.md](../../CONTEXT.md).

## Context
Most Items the household buys come back Order after Order (Frequent), some only now and then (Occasional), and a Frequent Item is sometimes left out for one Order (Not needed, the owner's old "NTT" tag). Today a row is deleted when an item is removed or the list is cleared, so Kiki forgets Frequent Items and the owner has to say them again for every Order.

## Options considered
- Keep one row per wanted item and delete it on remove (today): Kiki can't tell "not this time" from "never again".
- An Item table plus a separate "next order" (Need) table with item, quantity and status: clean history, but there is only ever one next Order, so the second table is one-to-one with the first.
- One `item` table with `kind` (frequent/occasional), `status` (needed/not_needed), `quantity` (next Order) and `usual_quantity`.

## Decision
One `item` table. Remove, "not this time" and clear set `status` to `not_needed`; nothing is deleted. The List shows every Frequent Item (Not needed ones labelled) and the Occasional Items that are Needed. A new Item is Occasional and Needed. `status` and `quantity` change only when the owner changes them or an Order completes; there is no weekly cycle or scheduled reset. When Orders are added later, they are a separate record (`order`, `order_line`) written when an Order is placed. Completing one starts the List over in one transaction: Frequent Items Needed at their Usual quantity, Occasional Items Not needed, Missing Items still Needed.

## Consequences
+ Frequent Items are remembered; each Order starts from them instead of from nothing.
+ No join and no second table to keep in step for the next Order.
+ "Clear the list" can no longer lose anything (the risk noted in 0012 goes away).
- One row mixes two lifetimes: name, kind and usual quantity last; status and quantity change all the time.
- Two Orders can't be prepared at once (for example two Stores). If that becomes real, move `status` and `quantity` into a `next_order` table.
- Misheard Items stay as hidden Occasional rows. Deleting them waits for Orders, when "never ordered" can be told apart.
- The schema changes; an existing `kiki.db` is not migrated and Kiki starts with an empty List.
