# 0013. Tooling: uv, pytest, ruff

- Status: Accepted
- Date: 2026-10-17
- Related: —

## Context
We need environment and dependency management, a test runner and a linter. uv is already installed.

## Options considered
- venv + pip + requirements.txt: stdlib-ish, no lockfile.
- uv + `pyproject.toml`: fast, lockfile, already installed.
- Plain asserts vs pytest: plain asserts get messy across eleven scenarios.

## Decision
uv with `pyproject.toml`. pytest as a dev dependency. ruff run via `uvx`, not installed into the project.

## Consequences
+ Reproducible installs with `uv sync`.
- pytest is one extra dev dependency.
