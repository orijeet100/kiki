# Architecture Decision Records

Why each decision was made. Format: MADR-lite (see [0001](0001-record-decisions-with-madr-lite.md)).

- Numbers are sequential and never reused.
- An accepted ADR is never edited. To change a decision, write a new ADR and set the old one's status to `Superseded by NNNN`.
- Rejected options get ADRs too, so they aren't re-argued.
- Status values: `Proposed`, `Accepted`, `Rejected`, `Deprecated`, `Superseded by NNNN`.

## Template

```markdown
# NNNN. <Decision, stated as a sentence>

- Status: Proposed
- Date: YYYY-MM-DD
- Related: FR/NFR IDs, supersedes —, superseded by —

## Context
## Options considered
## Decision
## Consequences
```

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-decisions-with-madr-lite.md) | Record decisions with MADR-lite ADRs | Accepted |
| [0002](0002-use-pipecat-for-voice-orchestration.md) | Use Pipecat for voice orchestration | Accepted |
| [0003](0003-gate-audio-with-local-wake-word.md) | Gate audio with a local wake word ("hey jarvis") before STT | Accepted |
| [0004](0004-run-stt-and-tts-locally.md) | Run STT and TTS locally (faster-whisper, Piper) | Accepted |
| [0005](0005-use-claude-haiku-by-default.md) | Use Claude Haiku by default | Accepted |
| [0006](0006-store-state-in-sqlite.md) | Store state in SQLite | Accepted |
| [0007](0007-laptop-is-the-permanent-host.md) | The laptop is the permanent host; devices are thin clients | Accepted |
| [0008](0008-tools-are-plain-functions.md) | Tools are plain functions | Accepted |
| [0009](0009-single-turn-commands.md) | Every command is single-turn | Accepted |
| [0010](0010-own-event-schema.md) | Kiki owns its event schema | Accepted |
| [0011](0011-python-owns-the-mic-in-v0.md) | Python owns the mic in v0 (LocalAudioTransport) | Accepted |
| [0012](0012-clear-list-without-confirmation.md) | Clear the list without confirmation | Accepted |
| [0013](0013-tooling-uv-pytest-ruff.md) | Tooling: uv, pytest, ruff | Accepted |
| [0014](0014-reject-list-export-to-phone.md) | Don't export or sync the list to phones | Rejected |
