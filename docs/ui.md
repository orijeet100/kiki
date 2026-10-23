# UI

> Owner's document: what the UI shows and does. How it looks (colors, type, components) is in [DESIGN.md](../DESIGN.md); its "Kiki overrides" section maps every element named here to a Framer component. Edit this file, then the UI follows it.

## What it's for

Watching Kiki work, at a glance from across the kitchen: what state it's in, what it just heard and did, and what's on the list. Nothing else competes for attention.

## Already decided

- Runs in a browser on the laptop, localhost only (NFR-0.7). The Tab5 on the fridge shows this same page, streamed from the laptop (FR-0.31).
- Driven by Kiki's own `state`, `turn` and `list` events ([ARCHITECTURE.md](../ARCHITECTURE.md#ui-v04)).
- One HTML file plus the vendored Speaking Orb script; nothing loaded from the network ([ADR 0020](adr/0020-ui-over-server-sent-events.md), [ADR 0024](adr/0024-vendor-the-speaking-orb.md)).
- Dark only, Framer palette ([DESIGN.md](../DESIGN.md#kiki-overrides)).

## Layout (v0.10)

```
┌────────────────────────────────────────────────────────────┐
│ Kiki                                  ● live  [History 46] │  top bar
│                                                            │
│                       ( speaking orb )                     │
│                “Added ice cubes to your list.”             │  caption
│                         Listening…                         │  state
│             “Can we add ice cubes?”  [added ice cubes]     │  last run
│                                                            │
│      ┌ Grocery list ─────────────────────────── 12 items ┐ │
│      │ Tomatoes          × 2  │ Wraps                     │ │
│      │ Potato                 │ Capsicums                 │ │
│      └──────────────────────────────────────────────────┘ │
│      ( Type a command                           [Send] )   │  docked
│              Or say “hey jarvis”, then the command.        │
└────────────────────────────────────────────────────────────┘
```

- **One column, one axis.** Everything is centered in a single 640px column, top to bottom: the orb, what Kiki is doing, what it last heard and did, the list, the text box. Nothing sits to the left or right of anything else, so the eye only ever moves down.
- **The text box stays put.** It docks to the bottom of the window; the list scrolls under it and fades out behind it. On a short list nothing scrolls at all.
- **History is one click away, not on screen.** All runs are in a sheet that slides in from the right (History button in the top bar, with the run count, or click the last-run line). Esc, the close button or a click outside closes it.
- **Same layout on a phone.** The list drops to one column under 520px wide.

## The column

From top to bottom:

| Element | Shows |
|---|---|
| Orb | The Speaking Orb. Its shape follows the state (table below). When a run arrives, Kiki's reply appears as the orb's caption, word by word, the words flying out of the orb as particles. The browser never speaks it; Piper already did |
| State label | Idle, Listening…, Thinking…, Speaking, Something went wrong (in red). The one display-size line on the page. While Kiki fills the Cart it says how far it is: "Filling cart, 4 of 12" (v0.17) |
| Last run | One quiet line: what Kiki heard, in quotes, then what it did as chips ("added ice cubes"). Clicking it opens History. Before the first run: three example commands that fill the text box when clicked |
| List | See below |
| Text box | A pill composer with a white Send button, so the UI works without a microphone. Under it: “Or say “hey jarvis”, then the command.” A failed send shows the error under the box |

### Orb states

| Kiki state | Orb |
|---|---|
| idle | Listening shape, still, smaller and dimmed, in white |
| listening | Listening shape at full size and brightness, rippling, in white: "hey jarvis" visibly wakes it. Also for 5 s after each reply, while Kiki listens for a follow-up |
| thinking | Ribbons orbiting, in violet |
| speaking | A lobed sphere swelling with each syllable, a lit ring rising per syllable, in magenta |
| error | Listening shape, still, gray and faded; the label turns red |
| after a run with no error, back to idle | A green check mark for 1.8 s, then idle |

Under "reduce motion" the sphere freezes; captions still appear.

## The list

In two columns. Title "Grocery list" with the count of Needed items ("4 items") beside it, and a Reset button on the right (v0.17, FR-0.35): the first tap turns it into "Tap again to reset" for three seconds, the second starts the List over (every Frequent item Needed at its usual quantity, every Occasional one Not needed) and shows as a run in History. Needed items come first; each row is the item name, capitalized, and its quantity on the right only when it's more than one ("× 2"). In the browser, an item with a Product shows its name under the item's, small, muted and on one line ("Wegmans Grade AA Large Eggs, 18 Count"); the Tab5 keeps rows to the name and shows the Product in the item sheet. Then the Frequent items that are Not needed this time, dimmed, with "Not needed" where the quantity goes. Occasional items that aren't needed aren't shown (v0.12, [CONTEXT.md](../CONTEXT.md)).

Every row ends with one quiet letter in a small dark circle: **F** for Frequent, **O** for Occasional (v0.18, FR-0.41), after the quantity.

Under the List, a closed row says **Not on the list · 19** (with a chevron in the browser, "Show" or "Hide" on the Tab5). Opened, it lists every other item Kiki knows, the Occasional ones that aren't needed this time, dimmed and in name order, each with its letter and, in the browser, its Product. Clicking one in the browser puts it on the List (Needed); tapping one on the Tab5 opens its item sheet. It starts closed every time the page loads. On the Tab5 the List card stops at four and a half rows and scrolls inside, so the text box and the volume bar always stay on screen.

Clicking a row flips it between Needed and Not needed, through the same tools as saying "add" or "remove" (FR-0.27). A Needed Occasional item disappears when clicked; say "add" to bring it back. Rows that are new or changed get a blue ring for 1.5 s.

On the Tab5, tapping a row opens the item sheet instead (FR-0.33; the browser gets it next). It rises from the bottom with a grab handle; the item's name, large, under a spaced-out eyebrow saying FREQUENT or OCCASIONAL, with Rename and × beside it; then two groups, each a raised plate in a dark tray with a hairline edge:

- **This order:** the quantity with round – and + on the same line, and a Needed | Not needed switch under it.
- **On the list:** a Frequent | Occasional switch, with one line saying what it means: Frequent "stays on the list, dimmed, when it's not needed", Occasional "leaves the list when it's not needed".
- **Product** (v0.17, FR-0.34): the Product the Cart gets for this item, on one line ("No product yet", muted, when there's none), with a Forget pill beside it. Forget clears it; the next Cart finds one again. Choosing a Product is by voice for now ("use Diamond walnuts for walnuts").

Then Remove (Not needed, the item stays known) in red on a charcoal pill, and Done as the white pill with its check in a black circle. Rename swaps the groups for the name in a large field (same tray, its edge blue while typing), a line saying Kiki will use the new name by voice too, and the keyboard with Save as its white key; its hide key or × goes back to the sheet with the old name. The sheet rises to fit.

**The Tab5's keyboard** (for the text box and for renaming) is laid out like a phone's: three rows of letters, the middle one inset half a key; shift and backspace beside the last row; then 123, hide, a wide space bar and the action key (Send for the text box, Save for renaming). Letters are raised charcoal keys with large bold labels and a hairline along their top; shift, 123, hide and backspace are quieter, darker keys with small muted labels; the action key is the one white key. Shift capitalizes one letter, and holding backspace repeats. The keyboard sits in a dark tray with a hairline edge, like the sheet's groups.

Every change is on the screen at once and goes to Kiki after; one Kiki refuses goes back, with the reason in red under the name. Tapping another row while it's open switches it to that item; × or Done closes it. It has no dimmed backdrop: on the Tab5 that would redraw the whole screen. Empty: "Nothing on the list yet." with a hint to say "hey jarvis, add milk".

## Run cards

Time and source (voice, text, or button for Reset), total latency; Heard, Did (chips such as "added bread, milk ×2", "already there: bread", "removed eggs", "milk → 3"), Said. Ordering (v0.17) keeps its chips short ("read 5 new orders", "matched 15", "7 without a product"; "cart: 16 of 17", "1 top match", "1 failed" in red; "Instacart: signed_out" in red) and adds a Products row under Did with one line per item: the item, then its Product muted and cut to one line ("Eggs  Wegmans Grade AA Large Eggs, 18…"); a guess carries a small "top match" tag, a failure says why in red ("Blueberries  sold out"); the items still without a Product are one line that wraps, since every name matters. The last-run line shows only the chips. Both screens show it the same way. An error shows in red under them. In the History sheet each card also has Details: per-stage latency, model, raw tool calls. The sheet holds the last 50 runs, newest first: the log's runs on load, live runs added on top.

## Other behavior

| Topic | Decision |
|---|---|
| Connection | A dot and a word in the top bar: green "live", red "reconnecting…" (the page reconnects by itself) |
| Sounds | Soft glass chimes (owner's pick of glass, marimba and bell): rising fifth when Kiki starts listening, at a peak of 0.45 (`KIKI_CHIME_VOLUME`); no sound when it stops |
| Motion | The column rises in piece by piece on load and the list rows cascade in; the orb grows when Kiki wakes; the History sheet slides in; buttons press in slightly. Entry motion is off under "reduce motion" |
| Keyboard | Every control is reachable with Tab and shows a blue focus ring; the composer's border turns blue while typing |

## History of this page

- v0.4: first cut. Three panels side by side (assistant, list, runs) with a CSS conic-gradient orb; the runs column grew down the page.
- v0.9: same layout, Framer look.
- v0.10: the Speaking Orb, one centered column with a docked text box, and the History sheet. (A first v0.10 draft put the stage and the list side by side; it read as left, right, then down, so everything moved onto one axis.)
- v0.12: Needed and Not needed items; clicking a row flips it.
- v0.16: on the Tab5, tapping a row opens the item sheet (Needed, quantity, Frequent or Occasional, rename, remove).
- v0.18: F or O on every row; "Not on the list" under the List with every other item.
- v0.17: the Product line with Forget on the Tab5's item sheet, a two-tap Reset on the List, ordering chips, "Filling cart, 4 of 12" in the state line.

## Still open

- **Item sheet in the browser:** the Tab5 has it (v0.16); the browser still flips a row on click, and shows an item's Product under its name.
- **Choosing a Product by touch:** a list of Products to pick from on the item sheet, in place of Forget (by voice only for now).
- **Real voice envelope:** the orb's swell while speaking is estimated from syllables. Following Piper's real audio needs volume events from the voice loop.
- **Searching state:** the orb has a fifth shape (searching, blue bands), unused until Kiki has a tool that searches.
- **The M5 screen:** the Tab5 (720×1280) shows this page as it is, streamed from the laptop (v0.14, [ADR 0028](adr/0028-stream-the-real-ui-page-to-the-tab5.md)), with an on-screen keyboard and its own volume bar along the bottom. A layout drawn natively on the Tab5 is being tried.

## Sketches

(add images or links here)
