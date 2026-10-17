# 0019. Whisper `base.en` with a grocery-vocabulary prompt

- Status: Accepted
- Date: 2026-10-17
- Related: NFR-0.3, FR-0.4. Supersedes the STT model choice in 0004.

## Context
`small.en` took ~1.6 s per command on this laptop's CPU, the largest stage of the voice latency. Pipecat's Whisper service exposes the model name and an `initial_prompt`, not the beam size.

## Options considered
Measured on 13 Piper-spoken commands:
- `small.en`: 1.6 s, no real errors.
- `base.en`, no prompt: 0.5 s; "braid" for bread, "cut the eggs", "milk to apples" (loses a quantity).
- `distil-small.en`: 1.5 s, still "milk to apples".
- `base.en` with the prompt "Grocery list. Add two apples, three milks, bread and eggs. Got the milk. Remove the eggs. What's on my list?": 0.5 s, no real errors.

## Decision
`base.en` with that prompt (`WHISPER_PROMPT` in `voice.py`). `KIKI_WHISPER_MODEL=small.en` is the fallback. The agent instructions also say that "got the X" is often heard as "cut", "dot" or "gut" (scenario 12).

## Consequences
+ About 1.1 s faster per command.
- Accuracy now leans on the prompt. Real voices in a real kitchen may differ from Piper; if misheard commands show up in the log, switch to `small.en` or extend the prompt.
