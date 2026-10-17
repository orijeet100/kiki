# 0009. Every command is single-turn

- Status: Accepted; amended by 0022 (a follow-up gets the previous command as context)
- Date: 2026-10-17
- Related: FR-0.6, FR-0.7, FR-0.8, FR-0.9

## Context
Multi-turn conversation adds chat-history handling, follow-up windows and context trimming on interruption. v0 should be as simple as possible.

## Options considered
- Multi-turn with history: supports confirmations, clarifying questions and paging.
- Single-turn: each wake word is one command and one fresh Claude call.

## Decision
Single-turn. Claude gets only the system prompt, the current list and the command. As a result: no confirmation for clear (ADR 0012), the whole list is read in one reply, and garbled input gets "Sorry, I didn't catch that." instead of a question.

## Consequences
+ No conversation state at all. Interruptions just stop speech.
- Recipes, confirmations and follow-ups will need a new ADR when they arrive.
