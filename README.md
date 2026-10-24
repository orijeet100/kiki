# Kiki

A voice assistant for the kitchen. Say the wake word, say a command ("add bread and two milks"), and Kiki updates the household grocery list and answers in one short spoken sentence.

It lives on the fridge as an M5Stack Tab5: a touchscreen, mic and speaker that streams to a laptop at home, where all the real work happens. It also runs on the laptop alone.

## Run it

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), a microphone and speakers. Put your key in `.env` (never committed):

```bash
echo ANTHROPIC_API_KEY=sk-ant-... > .env
uv sync
```

Then one of:

```bash
uv run --env-file .env python -m kiki.voice
```

Say "hey jarvis", wait for the chime, say a command. The UI is at http://127.0.0.1:8765.

```bash
uv run --env-file .env python -m kiki.ui
```

The UI alone, with a text box. `python -m kiki.cli` is the plain terminal version. The first voice start downloads the Whisper and Piper models (a few hundred MB).

## Run it on the Tab5

The Tab5 is only a screen, mic and speaker for the laptop ([ADR 0027](docs/adr/0027-the-tab5-is-a-thin-client-over-the-home-network.md)). Once: install [arduino-cli](https://arduino.github.io/arduino-cli/) with M5Stack's board package and the M5Unified and M5GFX libraries, copy `device/stream/secrets.h.example` to `secrets.h` with your Wi-Fi and the laptop's IP, plug the Tab5 in and flash it:

```bash
arduino-cli compile --upload -p COM9 -b m5stack:esp32:m5stack_tab5:CDCOnBoot=cdc device/stream
```

Then, on the laptop, Kiki on the Tab5's mic and speaker, and the UI streamed to its screen (Google Chrome must be installed):

```powershell
$env:KIKI_MIC="tab5"; $env:KIKI_SPEAKER="tab5"; uv run --env-file .env python -m kiki.voice
uv run python -m kiki.screen
```

Say "hey jarvis" to the Tab5, wait for the chime, say a command. Drag the bar along the bottom of its screen for the volume; it starts at 5%.

Better, since v0.15: let the Tab5 draw the UI itself, smoother and without Chrome: flash `device/kiki` with `powershell -ExecutionPolicy Bypass -File device\kiki\build.ps1 -Port COM9`, and run Kiki with `$env:KIKI_UI_HOST="0.0.0.0"` as well; `kiki.screen` isn't needed. Details, ports and what was learned: [ARCHITECTURE.md](ARCHITECTURE.md#tab5-v014).

To skip the `$env:` lines every time, put `KIKI_MIC=tab5`, `KIKI_SPEAKER=tab5` and `KIKI_UI_HOST=0.0.0.0` in `.env`; then `uv run --env-file .env python -m kiki.voice` alone starts Kiki for the Tab5.

## Order the groceries

Since v0.17 Kiki fills your Instacart cart at Wegmans; you check out in the Instacart app. Once, in your own Chrome (signed in to Instacart): open `chrome://extensions`, turn on Developer mode, click **Load unpacked** and pick `browser/instacart`. Set `KIKI_ADDRESS` in `.env` if your delivery address isn't 30 River Court. Then:

- "Analyze my order": Kiki reads your past Wegmans orders and learns which product each item is.
- "Order the groceries": every Needed item goes into the cart at its quantity. Items it had to guess are listed in History.
- "Use Diamond walnuts for walnuts", "forget the walnut product": change an item's product.
- **Reset** on the list (tap twice) when the groceries have come: Frequent items come back, Occasional ones go.

Kiki opens its own Instacart tab in your Chrome, works there and closes it; it never touches your other tabs and never checks out ([ADR 0034](docs/adr/0034-reach-instacart-through-a-kiki-extension-in-the-owners-chrome.md)).

## Why

We order groceries from home. The list is the first useful thing and the base for the next rungs: filling the cart (v0.17), then ordering. It also exercises every hard part of a voice agent (parsing, persistent state, short replies, latency) with almost no external risk.

## Who and where

- **Users:** anyone in the household. No voice recognition, so every voice action must be safe for whoever is standing in the kitchen.
- **Host:** the laptop, now and later. Devices are thin clients. Kiki works only while the laptop is on and online.
- **Success:** used daily, not a demo.

## Principles

1. **Privacy by design.** Wake-word detection runs locally, before anything is transcribed. Audio never leaves the laptop. Only the text of the command after the wake word goes to Claude.
2. **State lives in tools and the database, not in the chat.** Every command is a fresh, single-turn call that sees only the current list.
3. **Use existing frameworks.** Pipecat handles audio, turn detection and streaming. We don't hand-build them.
4. **Small blocks, text before voice.** Every feature passes text tests before it is tried by voice.
5. **Risk decides confirmation.** Read-only and reversible actions just happen. Anything that spends money or can't be recovered must read back and wait for an explicit yes. (Clearing the list counts as recoverable because the log keeps the removed items, see [ADR 0012](docs/adr/0012-clear-list-without-confirmation.md).)
6. **Voice style, not chat style.** One or two short sentences, no markdown or lists, numbers the way they are spoken.

## Where things live

| File | What it answers | How it changes |
|---|---|---|
| [README.md](README.md) | What and why, principles | Rarely |
| [ROADMAP.md](ROADMAP.md) | Versions, requirements (FR/NFR), definition of done | Edited while a version is active, frozen once shipped |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the system works right now | Updated in the same commit as the code |
| [docs/ui.md](docs/ui.md) | What the UI shows and how it behaves | Owned by the project owner |
| [DESIGN.md](DESIGN.md) | How the UI looks: colors, fonts, components (Framer template + Kiki overrides) | Owned by the project owner |
| [docs/adr/](docs/adr/README.md) | Why each decision was made | Never edited, only superseded |
| [CHANGELOG.md](CHANGELOG.md) | What actually shipped | Append-only |
| [AGENTS.md](AGENTS.md) | Rules for anyone (human or agent) writing code here | As rules are added |
