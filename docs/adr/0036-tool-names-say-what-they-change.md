# 0036. Tool names say what they change; `clear_list` becomes `clear_all_items`

- Status: Accepted
- Date: 2026-10-23
- Related: FR-0.26, FR-0.35 (v0.17). Keeps 0008 (plain tools), 0012 (clear without confirmation).

## Context
v0.17 adds a second whole-List tool: `reset_list` starts the List over (Frequent items Needed at their usual quantity, Occasional ones Not needed). Next to it, `clear_list` read as the same kind of thing, though it only makes every item Not needed. The owner asked for names that say exactly what they change.

## Decision
Tool names are verb, then what they change, then `_for_item` when they change one Item: `clear_all_items`, `reset_list`, `set_product_for_item`, `forget_product_for_item`, `learn_product_preferences`, `fill_cart`. `clear_list` is renamed `clear_all_items`. The older tools keep their names for now (`set_quantity`, `set_usual_quantity`, `set_buying_pattern`); renaming them touches the screens' chips on both UIs and the device, and waits for the owner's call.

## Consequences
+ Clear and reset can't be confused in code, logs or History.
- Turn logs from before v0.17 say `clear_list`; both UIs show its chip under either name.
- The older `set_` tools don't follow the convention yet.
