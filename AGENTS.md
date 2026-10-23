# AGENTS.md

Rules for anyone writing code in this repo, human or coding agent. More detail will be added by the owner.

## Before you start

Read in this order: [README.md](README.md), the active version in [ROADMAP.md](ROADMAP.md), [ARCHITECTURE.md](ARCHITECTURE.md).
For UI work, also read [docs/ui.md](docs/ui.md) (what it shows and does) and [DESIGN.md](DESIGN.md) (how it looks; its "Kiki overrides" section wins). Check [docs/adr/](docs/adr/README.md) before changing anything a decision covers.

## Rules

1. **Work only on the active build step** in ROADMAP.md. Don't scaffold future steps or ideas.
2. **Docs move with code.** A change to behavior updates ARCHITECTURE.md in the same commit. A new decision gets a new ADR. Never edit an accepted ADR's content; write a new one that supersedes it, and change only the old one's status line.
3. **Requirements and tests are 1:1.** Every FR/NFR has a test named after its ID. No requirement without a test, no test without a requirement.
4. **No new dependency without the owner's yes.** The approved list is in ARCHITECTURE.md. Adding one means an ADR and updating that list.
5. **Tools are plain functions.** JSON-compatible input and output, no knowledge of voice, Pipecat or Claude inside `tools.py`.
6. **Secrets only from env vars.** Model name and API key come from the environment. Never commit `.env`, a key, `kiki.db` or `logs/`.
7. **Shipping a step:** its definition of done passes, add a CHANGELOG entry, tag it (`v0.1`, `v0.2`...).
8. **Keep it single-turn** in v0 ([ADR 0009](docs/adr/0009-single-turn-commands.md)). Don't pass previous turns to Claude.

## Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Requirements | `FR-<ver>.<n>`, `NFR-<ver>.<n>` | `FR-0.2`, `NFR-0.1` |
| Tests | `test_<req id>_<what>` | `test_fr_0_2_duplicate_add` |
| ADRs | `docs/adr/NNNN-kebab-title.md`, title states the decision | `0003-gate-audio-with-local-wake-word.md` |
| Versions and tags | `v0.1`, `v0.2`, `v1` | |
| Python | PEP 8: `snake_case` functions and files, `PascalCase` classes | `add_items()` |
| Tools | verb, then what it changes, then `_for_item` when it changes one Item ([ADR 0036](docs/adr/0036-tool-names-say-what-they-change.md)) | `clear_all_items()`, `set_product_for_item()` |
| Browser extensions | `browser/<name>/`, Manifest V3, loaded unpacked; no build step | `browser/instacart/worker.js` |
| Env vars | `KIKI_` prefix (except `ANTHROPIC_API_KEY`) | `KIKI_MODEL` |
| Device sketches | `device/<name>/<name>.ino`, `camelCase` functions, `secrets.h` git-ignored | `device/stream/stream.ino` |
| Commits | `<area>: <what>` plus IDs when relevant | `tools: add_items keeps existing quantity (FR-0.2)` |

## How things tie together

```
FR-0.2 ──tested by──> test_fr_0_2_duplicate_add
  │                          │
decided in               changed in
  ▼                          ▼
ADR 0009 ──referenced by──> commit "tools: ... (FR-0.2, ADR-0009)"
                             │
                        shipped in
                             ▼
                      CHANGELOG v0.1 ──> git tag v0.1
```

## Commands

```bash
uv sync                                       # install
uv run pytest -m "not scenario"               # no API calls (voice tests take about a minute)
uv run --env-file .env pytest                 # all tests, scenarios need ANTHROPIC_API_KEY in .env
uvx ruff check . && uvx ruff format .         # lint and format
uv run --env-file .env python -m kiki.cli     # terminal loop (v0.1)
uv run --env-file .env python -m kiki.voice   # voice loop + UI at http://127.0.0.1:8765
uv run --env-file .env python -m kiki.ui      # UI only, with a text box (no microphone)
uv run pytest -m "not voice and not scenario" # instant tests only
uv run python -m kiki.latency                 # median voice latency from the turn log (NFR-0.3)
uv run python -m kiki.stt_bench [model ...]   # Whisper models compared: time and word accuracy
uv run python -m kiki.screen                  # stream the UI to the Tab5 (start Kiki first)
# chrome://extensions > Developer mode > Load unpacked > browser/instacart  # once, for ordering (v0.17)
arduino-cli compile --upload -p COM9 -b m5stack:esp32:m5stack_tab5:CDCOnBoot=cdc device/stream  # flash the Tab5
powershell -ExecutionPolicy Bypass -File device/kiki/build.ps1 -Port COM9  # flash the native Tab5 UI
powershell -ExecutionPolicy Bypass -File device/kiki/serial.ps1 "tapitem 0" "wait 2"  # Tab5 test commands, prints its log
powershell -ExecutionPolicy Bypass -File device/kiki/shot.ps1 -Out screen.png        # what the Tab5 shows, as a PNG
```

With `KIKI_MIC=tab5` and `KIKI_SPEAKER=tab5`, `kiki.voice` uses the Tab5's mic and speaker instead of the laptop's. Never play test sounds through a device's speaker at an untested volume; the Tab5 starts at 5%.
