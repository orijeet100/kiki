# Kiki

A voice assistant for the kitchen. Say the wake word, say a command ("add bread and two milks"), and Kiki updates the household grocery list and answers in one short spoken sentence.

It will live on the fridge as a small device (M5Stack CoreS3) that streams audio to a laptop at home, where all the real work happens. v0 runs entirely on the laptop.

## Why

We order groceries from home. The list is the first useful thing and the base for later rungs (cart building, ordering). It also exercises every hard part of a voice agent (parsing, persistent state, short replies, latency) with almost no external risk.

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
| [DESIGN.md](DESIGN.md) | UI design (v0.4) | Owned by the project owner |
| [docs/adr/](docs/adr/README.md) | Why each decision was made | Never edited, only superseded |
| [CHANGELOG.md](CHANGELOG.md) | What actually shipped | Append-only |
| [AGENTS.md](AGENTS.md) | Rules for anyone (human or agent) writing code here | As rules are added |
