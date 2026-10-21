# UI

> Owner's document: what the UI shows and does. How it looks (colors, type, components) is in [DESIGN.md](../DESIGN.md); its "Kiki overrides" section maps every element named here to a Framer component. Edit this file, then the UI follows it.

## What it's for

Watching Kiki work, at a glance from across the kitchen: what state it's in, what it just heard and did, and what's on the list. Nothing else competes for attention.

## Already decided

- Runs in a browser on the laptop, localhost only (NFR-0.6).
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
| State label | Idle, Listening…, Thinking…, Speaking, Something went wrong (in red). The one display-size line on the page |
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

In two columns. Title "Grocery list" with the count of Needed items ("4 items") on the right. Needed items come first; each row is the item name, capitalized, and its quantity on the right only when it's more than one ("× 2"). Then the Frequent items that are Not needed this time, dimmed, with "Not needed" where the quantity goes. Occasional items that aren't needed aren't shown (v0.12, [CONTEXT.md](../CONTEXT.md)).

Clicking a row flips it between Needed and Not needed, through the same tools as saying "add" or "remove" (FR-0.27). A Needed Occasional item disappears when clicked; say "add" to bring it back. Rows that are new or changed get a blue ring for 1.5 s. Empty: "Nothing on the list yet." with a hint to say "hey jarvis, add milk".

## Run cards

Time and source (voice or text), total latency; Heard, Did (chips such as "added bread, milk ×2", "already there: bread", "removed eggs", "milk → 3"), Said. An error shows in red under them. In the History sheet each card also has Details: per-stage latency, model, raw tool calls. The sheet holds the last 50 runs, newest first: the log's runs on load, live runs added on top.

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

## Still open

- **Real voice envelope:** the orb's swell while speaking is estimated from syllables. Following Piper's real audio needs volume events from the voice loop.
- **Searching state:** the orb has a fifth shape (searching, blue bands), unused until Kiki has a tool that searches.
- **Not needed Occasional items:** they vanish from the list; the run card shows them. A brief strike-through could show it in the list too.
- **The M5 screen:** a much smaller layout for the fridge device; the orb alone might be the whole screen.

## Sketches

(add images or links here)
