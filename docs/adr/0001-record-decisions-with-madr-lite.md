# 0001. Record decisions with MADR-lite ADRs

- Status: Accepted
- Date: 2026-10-17
- Related: —

## Context
We want production-level organization where nothing gets lost: what was decided, why, and what replaced it.

## Options considered
- Decisions inside one big plan document: easy, but history gets overwritten.
- Full MADR template: thorough, but heavy for a small project.
- MADR-lite: numbered files, status line, five short sections, index.

## Decision
MADR-lite in `docs/adr/`, with the index and template in [README.md](README.md). Accepted ADRs are never edited, only superseded. Rejected options are recorded too.

## Consequences
+ Full decision history, traceable from requirements, tests and commits.
- Each decision costs a small file. Keep them short.
