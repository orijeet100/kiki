# Roadmap

One version is active at a time. A version's section is edited while it is active and frozen once it ships. Later versions list only what they add or change, referencing earlier IDs ("FR-1.2 replaces FR-0.5").

Requirement IDs: `FR-<version>.<n>` (functional), `NFR-<version>.<n>` (non-functional). Every requirement has a test named after it (see [AGENTS.md](AGENTS.md)).

| Version | Status | Summary |
|---|---|---|
| v0 | **Active** | Grocery list by voice on the laptop, plus a UI to watch it work |
| v1 | TBD | Not decided yet, see [Ideas](#ideas-not-scheduled) |

---

## v0: Grocery list

**Goal:** one household grocery list, edited and read back by voice, used daily from the kitchen.

### Build steps

| Step | Status | What |
|---|---|---|
| v0.1 | **Done** (2026-10-17) | **Terminal.** Type a command, Claude calls tools, SQLite updates, the reply prints, the turn is logged. |
| v0.2 | **Done** (2026-10-17) | **Voice on the laptop.** "hey jarvis", Python owns the mic, local STT and TTS, chimes. Same tools, unchanged. |
| v0.3 | Next | **Tune.** Wake sensitivity, end-of-turn timing, reply style, latency. |
| v0.4 | Planned | **UI.** Orb, list and run history driven by Kiki's own events. Starts only after [DESIGN.md](DESIGN.md) is written. |

### Functional requirements

| ID | Step | Requirement |
|---|---|---|
| FR-0.1 | v0.1 | Add one or more items from a single sentence, each with a quantity (default 1). "Add milk, two apples and some rice" adds three items. |
| FR-0.2 | v0.1 | Adding an item already on the list replies "Bread's already on the list" and leaves the quantity unchanged. |
| FR-0.3 | v0.1 | An explicit quantity change ("add another milk", "make it three milks") sets the new quantity. |
| FR-0.4 | v0.1 | Singular and plural match the same item ("egg" = "eggs"). Obvious speech-to-text slips are corrected ("bred" to "bread"). |
| FR-0.5 | v0.1 | Remove one or more items in one sentence ("got the milk, eggs and bread"). Removing deletes the item completely, whatever its quantity. Removing something not on the list says so. |
| FR-0.6 | v0.1 | "What's on my list?" reads the whole list. An empty list replies "Your list is empty." |
| FR-0.7 | v0.1 | "Clear the list" wipes it immediately, with no confirmation, and replies with how many items were removed. The removed items are recorded in the turn log. |
| FR-0.8 | v0.1 | Garbled or ambiguous input replies "Sorry, I didn't catch that." and changes nothing. No clarifying questions. |
| FR-0.9 | v0.1 | Every command is single-turn. Claude receives only the system prompt, the current list and the command. No previous turns. |
| FR-0.10 | v0.1 | Replies are one or two short sentences, with no markdown, bullets or emojis, and numbers written as spoken ("two milks"). |
| FR-0.11 | v0.2 | Saying "hey jarvis" starts listening. A chime plays when listening starts and a different chime when it stops. |
| FR-0.12 | v0.2 | Saying "hey jarvis" while Kiki is speaking stops the speech and starts a new command. |
| FR-0.13 | v0.4 | A local browser UI shows the assistant state, the current list and the history of turns, as specified in [DESIGN.md](DESIGN.md). |

### Non-functional requirements

| ID | Step | Requirement |
|---|---|---|
| NFR-0.1 | v0.2 | Nothing is transcribed or sent anywhere before the wake word fires. |
| NFR-0.2 | v0.2 | Audio never leaves the laptop. Only the command text goes to the Claude API. |
| NFR-0.3 | v0.3 | End of speech to first spoken audio is about 2 seconds or less, measured from the turn log (median over 20 commands). |
| NFR-0.4 | v0.1 | Every turn is appended as one JSON line to the turn log, in the event schema from [ARCHITECTURE.md](ARCHITECTURE.md#events). No audio is stored. |
| NFR-0.5 | v0.1 | The model name and API key come only from environment variables. No key is ever committed. |
| NFR-0.6 | v0.4 | The UI is served on localhost only. |

### Scenarios (text tests, v0.1)

| # | Input | Expected | Covers |
|---|---|---|---|
| 1 | "Add bread and eggs" | Both added, one short confirmation | FR-0.1, FR-0.10 |
| 2 | "Add bread" (already there) | "Bread's already on the list", quantity stays 1 | FR-0.2 |
| 3 | "Add another bread" | Quantity becomes 2 | FR-0.3 |
| 4 | "Add egg" (eggs on list) | Treated as a duplicate | FR-0.4 |
| 5 | "Add milk, two apples and some rice" | Three items, apples quantity 2 | FR-0.1 |
| 6 | "Got the milk and eggs" (milk quantity 3) | Both removed completely | FR-0.5 |
| 7 | "Remove bananas" (not on list) | Says it isn't on the list | FR-0.5 |
| 8 | "What's on my list?" (8 items) | All 8 read in one reply | FR-0.6 |
| 9 | "What's on my list?" (empty) | "Your list is empty." | FR-0.6 |
| 10 | "Clear the list" (5 items) | List empty, reply mentions five, log has the five items | FR-0.7, NFR-0.4 |
| 11 | "Blorp the frim" | "Sorry, I didn't catch that.", list unchanged | FR-0.8 |

### Definition of done

- **v0.1:** every v0.1 requirement has a passing test, including all 11 scenarios against the real API. `uv run --env-file .env python -m kiki.cli` runs the terminal loop and writes the turn log.
- **v0.2:** scenarios 1, 2, 5, 6, 8, 10 and 11 work by voice with "hey jarvis". FR-0.11, FR-0.12, NFR-0.1 and NFR-0.2 verified.
- **v0.3:** NFR-0.3 met. False wakes and premature cut-offs are rare enough for a week of daily use.
- **v0.4:** FR-0.13 and NFR-0.6 met.
- **v0 ships** when all four steps are done. Tag `v0`, add a CHANGELOG entry.

### Non-goals for v0

Ordering or any purchase, multi-turn conversation or follow-up questions, confirmation dialogs, decrementing quantities, multiple lists, voice recognition or per-person permissions, exporting or syncing the list to phones ([ADR 0014](docs/adr/0014-reject-list-export-to-phone.md)), access from other devices on the network, offline fallback, non-English speech, a camera, and real hardware.

### Open checks

- ~~openWakeWord can run as a custom Pipecat processor in front of STT.~~ Verified in v0.2: `WakeGate` in `voice.py`, covered by `test_nfr_0_1_*`.

---

## Ideas (not scheduled)

Unordered. Each becomes a version only when we decide v1, v2 and so on.

- Fridge hardware: M5Stack CoreS3 as a thin mic, speaker and screen streaming to the laptop. Transport (WebSocket vs WebRTC) decided by ADR at that time.
- Cart building from the list, no purchase, then read-back.
- Ordering behind a confirmation gate (likely browser automation).
- Timers, then multiple timers (first time Kiki speaks unprompted).
- Recipe read-aloud with "next" and "repeat" (needs multi-turn).
- Pantry tracking ("do we have eggs?", "we're out of milk").
- Stateless kitchen Q&A (conversions, substitutions).
- Custom wake word "hey Kiki".
- Proactive nudges.
