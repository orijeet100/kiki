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
| [0004](0004-run-stt-and-tts-locally.md) | Run STT and TTS locally (faster-whisper, Piper) | Accepted; STT model superseded by 0019 |
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
| [0015](0015-use-pydantic-ai-for-the-agent.md) | Use Pydantic AI for the agent | Accepted |
| [0016](0016-one-utterance-per-wake-word.md) | The wake gate lets through one utterance per wake word | Accepted; end detection superseded by 0021; amended by 0025 |
| [0017](0017-test-voice-with-synthesized-speech.md) | Test the voice loop with speech synthesized by Piper | Accepted |
| [0018](0018-one-model-request-per-command.md) | One model request per command: the `update_list` output function | Accepted |
| [0019](0019-whisper-base-with-vocabulary-prompt.md) | Whisper `base.en` with a grocery-vocabulary prompt | Accepted |
| [0020](0020-ui-over-server-sent-events.md) | The UI is one HTML page over Server-Sent Events, standard library only | Accepted; orb superseded by 0024 |
| [0021](0021-smart-turn-ends-the-command.md) | Smart Turn decides when a spoken command is finished | Accepted; amended by 0023 |
| [0022](0022-follow-up-window-after-each-reply.md) | Listen for five seconds after each reply, with the previous command as context | Reverted; superseded by 0025 |
| [0023](0023-grace-period-after-a-finished-sounding-pause.md) | Wait a short grace period after a pause sounds finished | Accepted |
| [0024](0024-vendor-the-speaking-orb.md) | The orb is the Speaking Orb web component, vendored as one file | Accepted |
| [0025](0025-listen-after-each-reply-and-ignore-what-is-not-a-command.md) | Listen for five seconds after each reply, and stay quiet if what's heard isn't a command | Accepted |
| [0026](0026-one-item-table-holds-the-next-order-state.md) | One item table holds both the item and its state for the next order | Accepted |
| [0027](0027-the-tab5-is-a-thin-client-over-the-home-network.md) | The Tab5 is a thin client of the laptop over the home network, with plain sockets and no password yet | Accepted |
| [0028](0028-stream-the-real-ui-page-to-the-tab5.md) | The Tab5 shows the real UI page, rendered by a headless Chrome on the laptop and streamed as JPEG frames | Accepted |
| [0029](0029-tab5-mic-over-udp-speaker-over-tcp-paced-by-the-clock.md) | The Tab5's mic reaches Kiki over UDP from its own task; Kiki's voice reaches the Tab5 over TCP, paced by the clock | Accepted |
| [0030](0030-the-tab5-mic-and-speaker-take-turns.md) | The Tab5's mic and speaker take turns | Accepted |
| [0031](0031-tab5-volume-in-the-samples-under-a-fixed-ceiling.md) | The Tab5's volume is applied to the samples, under a fixed ceiling, after a compressor | Accepted |
| [0032](0032-device-code-lives-in-this-repo.md) | Device code lives in this repo, one Arduino sketch per folder under `device/`, built with arduino-cli | Accepted |
| [0033](0033-draw-the-ui-natively-on-the-tab5.md) | Draw the UI natively on the Tab5 with LVGL, alongside the streamed page | Proposed |
