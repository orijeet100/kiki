# Roadmap

One version is active at a time. A version's section is edited while it is active and frozen once it ships. Later versions list only what they add or change, referencing earlier IDs ("FR-1.2 replaces FR-0.5").

Requirement IDs: `FR-<version>.<n>` (functional), `NFR-<version>.<n>` (non-functional). Every requirement has a test named after it (see [AGENTS.md](AGENTS.md)).

| Version | Status | Summary |
|---|---|---|
| v0 | **Shipped** (2026-10-17) | Grocery list by voice on the laptop, plus a UI to watch it work |
| v1 | TBD | Not decided yet, see [Ideas](#ideas-not-scheduled) |

---

## v0: Grocery list

**Goal:** one household grocery list, edited and read back by voice, used daily from the kitchen.

### Build steps

| Step | Status | What |
|---|---|---|
| v0.1 | **Done** (2026-10-17) | **Terminal.** Type a command, Claude calls tools, SQLite updates, the reply prints, the turn is logged. |
| v0.2 | **Done** (2026-10-17) | **Voice on the laptop.** "hey jarvis", Python owns the mic, local STT and TTS, chimes. Same tools, unchanged. |
| v0.3 | **Done** (2026-10-17), except the week of daily use (owner) | **Tune.** Wake sensitivity, end-of-turn timing, reply style, latency. |
| v0.4 | **Done** (2026-10-17), first-cut design (owner to revise in [docs/ui.md](docs/ui.md)) | **UI.** Orb, list and run history driven by Kiki's own events. |
| v0.5 | **Done** (2026-10-17) | **Natural pauses** (from daily use). A pause mid-sentence no longer ends the command; only one Kiki runs at a time. |
| v0.6 | Reverted (2026-10-17) | Follow-up window after each reply. Rolled back: background speech (a movie) kept it listening and answering. |
| v0.7 | **Done** (2026-10-17) | **Sounds and wake word** (from daily use). Glass listening chime at a comfortable level, no closing chime, wake threshold 0.4, wake scores in the log. |
| v0.8 | **Done** (2026-10-17) | **List commas** (from daily use). The 0.4 s grace period from v0.6 comes back on its own, without the follow-up window, so a comma pause no longer ends the command. |
| v0.9 | **Done** (2026-10-17) | **Framer look.** The v0.4 UI, same layout and behavior, restyled with the colors, type and components in [DESIGN.md](DESIGN.md). Dark only. |
| v0.10 | **Done** (2026-10-17) | **Speaking Orb and a calmer layout.** The Speaking Orb replaces the CSS orb ([ADR 0024](docs/adr/0024-vendor-the-speaking-orb.md)); one centered column with a docked text box, runs move to a History sheet ([docs/ui.md](docs/ui.md)). |
| v0.11 | **Done** (2026-10-17) | **Follow-up window, again** (from daily use). Kiki listens 5 s after each reply for another command, without the wake word; speech that isn't a command gets no reply ([ADR 0025](docs/adr/0025-listen-after-each-reply-and-ignore-what-is-not-a-command.md)). |
| v0.12 | **Done** (2026-10-21) | **List model.** Kiki remembers every Item: Frequent or Occasional, Needed or Not needed, with a Usual quantity. Removing and clearing mark Items Not needed instead of deleting them ([ADR 0026](docs/adr/0026-one-item-table-holds-the-next-order-state.md), terms in [CONTEXT.md](CONTEXT.md)). |
| v0.13 | **Done** (2026-10-21) | **Whole replies** (from daily use). A reply after a quiet spell lost its first words ("Milk is added to your list" played as "your list"): the speaker output now gets silence between sounds, so Windows never lets it fall asleep. |
| v0.14 | **Done** (2026-10-21) | **Tab5 on the fridge.** An M5Stack Tab5 is Kiki's screen, mic and speaker, a thin client of the laptop over the home Wi-Fi: the real UI page streamed to it with touch and an on-screen keyboard, its mic over UDP, Kiki's voice on its speaker with a volume bar of its own ([ADR 0027](docs/adr/0027-the-tab5-is-a-thin-client-over-the-home-network.md) to [0032](docs/adr/0032-device-code-lives-in-this-repo.md)). |
| v0.15 | Owner testing | **Native Tab5 UI.** The same UI drawn by the Tab5 itself with LVGL instead of streamed: Inter text, the Speaking Orb's particles ported to the device, the List, History, keyboard and volume bar, fed by Kiki's events ([ADR 0033](docs/adr/0033-draw-the-ui-natively-on-the-tab5.md)). Also: a command with no words no longer leaves Kiki "thinking". |

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
| FR-0.11 | v0.2 | Saying "hey jarvis" starts listening, with a chime. No sound plays when listening stops (changed by the owner: the closing chime was unpleasant). |
| FR-0.12 | v0.2 | Saying "hey jarvis" while Kiki is speaking stops the speech and starts a new command. |
| FR-0.13 | v0.4 | A local browser UI shows the assistant state, the current list and the history of turns, as specified in [docs/ui.md](docs/ui.md). |
| FR-0.14 | v0.5 | A pause mid-sentence ("Can you add one ... garlic") doesn't end the command. Neither does the comma pause in a spoken list ("Add milk, two apples and some rice"). The command ends when the sentence sounds finished and no more words follow within 0.4 s, or after 3 seconds of silence. |
| FR-0.15 | v0.5 | Only one Kiki runs at a time. Starting a second one exits with "Kiki is already running". |
| FR-0.16 | v0.9 | The UI takes its look from [DESIGN.md](DESIGN.md): every color in `ui.html` is a token declared once in `:root`, each token's value is in DESIGN.md, and there is no light theme. |
| FR-0.17 | v0.10 | The orb is the vendored Speaking Orb, served by Kiki itself at `/speaking-orb.js` with its MIT notice; the page loads nothing from the network. |
| FR-0.18 | v0.11 | For 5 seconds after Kiki finishes speaking a reply (`KIKI_FOLLOW_UP_SECS`), it listens for another command without the wake word, silently, while the UI shows Listening; it goes back to idle if nobody speaks. A follow-up is a standalone command (FR-0.9). If it isn't understood (FR-0.8), Kiki says nothing, changes nothing, and opens no new window. |
| FR-0.19 | v0.12 | Every Item has a Buying pattern, Frequent or Occasional, and a status, Needed or Not needed ([CONTEXT.md](CONTEXT.md)). The List is every Frequent Item, Not needed ones labelled, plus the Occasional Items that are Needed. An Item's status and quantity change only when a command or a click changes them; nothing resets them on a schedule (a completed Order will, once Orders exist). No command deletes an Item. |
| FR-0.20 | v0.12 | Adding an Item Kiki doesn't know creates it Occasional and Needed, with the quantity said (default 1). Adding a Not needed Item makes it Needed, at the quantity said or else its Usual quantity. FR-0.1 and FR-0.2 still hold. |
| FR-0.21 | v0.12 | Replaces FR-0.5. "Remove", "got the" or "not this time" makes one or more Items Not needed, whatever their quantity. Removing something not on the List says so. |
| FR-0.22 | v0.12 | A quantity change (FR-0.3) sets the quantity for the next Order only. "We usually get three tomatoes" sets the Usual quantity, and the next Order's quantity with it. |
| FR-0.23 | v0.12 | "Make chicken frequent" makes an Item Frequent. "We don't buy beetroot any more" makes it Occasional and Not needed. |
| FR-0.24 | v0.12 | "Call yogurt Greek yogurt" renames an Item and keeps everything else about it. |
| FR-0.25 | v0.12 | Replaces FR-0.6. "What's on my list?" reads the Needed Items with their quantities, then says how many Frequent Items are Not needed. With nothing Needed it replies "Your list is empty." |
| FR-0.26 | v0.12 | Replaces FR-0.7. "Clear the list" makes every Item Not needed, immediately and with no confirmation, and replies with how many Items it took off. |
| FR-0.27 | v0.12 | The UI list shows Needed Items first, then the Not needed Frequent Items dimmed and labelled. Clicking an Item flips it between Needed and Not needed ([docs/ui.md](docs/ui.md)). |
| FR-0.28 | v0.13 | Every chime and reply plays from its first word, however long Kiki was quiet before it: the speaker output is written to continuously, silence between sounds. |
| FR-0.29 | v0.14 | With `KIKI_MIC=tab5`, Kiki listens through the Tab5: UDP packets of 20 ms of 16 kHz mono audio on `KIKI_MIC_PORT` (8768) become its mic, in order. The wake word, follow-up window and transcription are unchanged. |
| FR-0.30 | v0.14 | With `KIKI_SPEAKER=tab5`, the chime and replies play on the Tab5: 16 kHz mono over TCP to the Tab5 connected on `KIKI_SPEAKER_PORT` (8769), sent at the pace they play and at most 0.15 s ahead, none of it lost. |
| FR-0.31 | v0.14 | `python -m kiki.screen` shows the UI page on the Tab5 as it looks in a browser: a headless Chrome renders it at 720×1200, the Tab5 on `KIKI_SCREEN_PORT` (8767) gets the newest frame each time it has shown the last, and its touches are replayed in the page. |
| FR-0.32 | v0.14 | On the Tab5, focusing the text box opens an on-screen keyboard that lifts the box above it; its Send sends the command. Only the page streamed to the Tab5 gets the keyboard. |

### Non-functional requirements

| ID | Step | Requirement |
|---|---|---|
| NFR-0.1 | v0.2 | Nothing is transcribed or sent anywhere before the wake word fires, except speech in the follow-up window after a reply (FR-0.18). |
| NFR-0.2 | v0.2 | Audio never leaves the laptop. Only the command text goes to the Claude API. |
| NFR-0.3 | v0.3 | End of speech to first spoken audio is about 2 seconds or less, measured from the turn log (median over 20 commands). |
| NFR-0.4 | v0.1 | Every turn is appended as one JSON line to the turn log, in the event schema from [ARCHITECTURE.md](ARCHITECTURE.md#events). No audio is stored. |
| NFR-0.5 | v0.1 | The model name and API key come only from environment variables. No key is ever committed. |
| NFR-0.6 | v0.4 | The UI is served on localhost only. |
| NFR-0.7 | v0.14 | Replaces NFR-0.6. The UI is served on localhost only, unless `KIKI_UI_HOST` opens it to the home network for the Tab5. Either way it refuses requests addressed to any host name but `localhost` (DNS rebinding), and commands or clicks that aren't JSON. |
| NFR-0.8 | v0.14 | Replaces NFR-0.2. Audio stays in the home: with the laptop's mic it never leaves the laptop, with the Tab5 it travels only between the Tab5 and the laptop. Only the command text goes to the Claude API. |

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
| 12 | "Dot the eggs" (Whisper's mishearing of "got the eggs") | Eggs removed | FR-0.4 |

### Scenarios (text tests, v0.12)

| # | Input | Expected | Covers |
|---|---|---|---|
| 13 | "Add shrimp" (never heard of) | Shrimp is Occasional, Needed, quantity 1 | FR-0.20 |
| 14 | "Add chicken" (Frequent, Not needed, usual 1) | Chicken Needed, quantity 1 | FR-0.20 |
| 15 | "Get three tomatoes" (Frequent, Not needed, usual 2) | Tomatoes Needed, quantity 3, usual stays 2 | FR-0.20, FR-0.22 |
| 16 | "Not chicken this time" (Frequent, Needed) | Chicken Not needed, still on the List | FR-0.19, FR-0.21 |
| 17 | "Remove butter" (Occasional, Needed) | Butter Not needed, off the List, still known | FR-0.19, FR-0.21 |
| 18 | "We usually get three tomatoes" (usual 2) | Usual quantity 3, quantity 3 | FR-0.22 |
| 19 | "Make chicken frequent" (Occasional) | Chicken Frequent | FR-0.23 |
| 20 | "We don't buy beetroot any more" (Frequent, Needed) | Beetroot Occasional, Not needed | FR-0.23 |
| 21 | "Call yogurt Greek yogurt" | Same Item, new name, buying pattern, status and quantities unchanged | FR-0.24 |
| 22 | "What's on my list?" (3 Needed, 2 Frequent Not needed) | Reads the three, says two are off this time | FR-0.25 |
| 23 | "Clear the list" (4 Needed, 2 of them Frequent) | All Not needed, the 2 Frequent still on the List, reply mentions four | FR-0.26 |

### Definition of done

- **v0.1:** every v0.1 requirement has a passing test, including all 11 scenarios against the real API. `uv run --env-file .env python -m kiki.cli` runs the terminal loop and writes the turn log.
- **v0.2:** scenarios 1, 2, 5, 6, 8, 10 and 11 work by voice with "hey jarvis". FR-0.11, FR-0.12, NFR-0.1 and NFR-0.2 verified.
- **v0.3:** NFR-0.3 met. False wakes and premature cut-offs are rare enough for a week of daily use.
- **v0.4:** FR-0.13 and NFR-0.6 met.
- **v0.5:** FR-0.14 and FR-0.15 met; a command with a 1.2 s mid-sentence pause is heard as one command by voice.
- **v0.9:** FR-0.16 met; FR-0.13 tests still pass; the page checked by eye in the browser in each orb state.
- **v0.10:** FR-0.17 met; FR-0.13 and FR-0.16 tests still pass; the page checked by eye at laptop and phone widths in each orb state, with a typed command and by voice.
- **v0.11:** FR-0.18 met; by voice, a command said within 5 s of a reply works without "hey jarvis", and talking that isn't a command in the window gets no reply.
- **v0.12:** every v0.12 requirement has a passing test, including scenarios 13 to 23 against the real API; the tests for FR-0.5, FR-0.6 and FR-0.7 are replaced by those for FR-0.21, FR-0.25 and FR-0.26; FR-0.13 and FR-0.16 tests still pass; scenarios 13, 16 and 22 work by voice; the page checked by eye with Needed and Not needed Items. An existing `kiki.db` is not migrated: Kiki starts with an empty List.
- **v0.13:** FR-0.28 met; by voice, a reply after more than ten quiet seconds is heard from its first word.
- **v0.15:** the FR-0.13 tests pass, including a command with no words going back to idle. Checked by hand on the Tab5 with `device/kiki` (it has no automated tests): every orb look (idle, listening, thinking, speaking pulsing with the reply, the check), the List, History, the keyboard and the volume bar, the mic at 500 packets per 10 s; and the owner's own test.
- **v0.14:** every v0.14 requirement has a passing test; the tests for NFR-0.6 and NFR-0.2 now carry the IDs that replace them (NFR-0.7, NFR-0.8). Checked by hand on the Tab5 (the Tab5 program has no automated tests): the page and the List as in the browser, History opened by touch, a command typed on the on-screen keyboard and sent, spoken commands heard through the Tab5's mic with every mic packet arriving (500 per 10 s), replies from its speaker clean and loud enough at a volume the owner chose, nothing louder than 5% on a new Tab5, and the Tab5 reconnecting by itself after a restart.
- **v0 ships** when all four steps are done. Tag `v0`, add a CHANGELOG entry.

### Non-goals for v0

Ordering or any purchase, multi-turn conversation or follow-up questions, confirmation dialogs, decrementing quantities, multiple lists, voice recognition or per-person permissions, exporting or syncing the list to phones ([ADR 0014](docs/adr/0014-reject-list-export-to-phone.md)), access from other devices on the network, offline fallback, non-English speech, a camera, and real hardware. v0.14 brings in one device, the Tab5, and its access to the laptop over the home network; other devices are still out, and so is talking over Kiki while the Tab5 speaks ([ADR 0030](docs/adr/0030-the-tab5-mic-and-speaker-take-turns.md)). v0.12 also leaves out Orders, Groups, more than one Store, units, deleting Items, and learning which Items are Frequent from past Orders.

### Open checks

- ~~openWakeWord can run as a custom Pipecat processor in front of STT.~~ Verified in v0.2: `WakeGate` in `voice.py`, covered by `test_nfr_0_1_*`.
---

## Ideas (not scheduled)

Unordered. Each becomes a version only when we decide v1, v2 and so on.

- Double buffering on the Tab5's panel and LVGL's own PPA drawing, for a sharper full-resolution orb (an M5GFX patch, or ESP-IDF).
- Full duplex on the Tab5: one shared audio clock and echo cancellation, so "hey jarvis" works while it speaks and the chime doesn't pause the mic.
- A shared secret between the Tab5 and the laptop ([ADR 0027](docs/adr/0027-the-tab5-is-a-thin-client-over-the-home-network.md)), and finding the laptop by name (mDNS) instead of a fixed IP.
- Cart building from the list, no purchase, then read-back.
- Ordering behind a confirmation gate (likely browser automation).
- Orders ([ADR 0026](docs/adr/0026-one-item-table-holds-the-next-order-state.md)): "order placed", after a two-step confirmation, records what was ordered. When the Order is complete, the List starts over: every Frequent Item is Needed at its Usual quantity, every Occasional Item is Not needed, and Missing Items ("the blueberries didn't come") stay Needed. Occasional Items that were never ordered can then be deleted.
- Groups: "order my breakfast" makes a named set of Items Needed.
- Suggest Frequent or Occasional from past Orders ("butter was in four of the last five Orders").
- Timers, then multiple timers (first time Kiki speaks unprompted).
- Recipe read-aloud with "next" and "repeat" (needs multi-turn).
- Pantry tracking ("do we have eggs?", "we're out of milk").
- Stateless kitchen Q&A (conversions, substitutions).
- Custom wake word "hey Kiki".
- Proactive nudges.
