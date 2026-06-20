# 0007 — Python-only, tested scripts

Status: Accepted

## Context

Skills can bundle executables. Shell scripts are hard to test and reason about. We want all
embedded logic deterministic and verifiable.

## Decision

No shell scripts. All scripts and hooks are Python. Shared code lives in
`plugin/lib/agentic_forge/` (importable, tested); skill-specific executables live in
`skills/<name>/scripts/` and are referenced via `${CLAUDE_SKILL_DIR}`. Everything is covered
by `pytest` (target ≥ 80% line coverage) and passes `ruff` and `mypy`.

## Alternatives considered

- **Shell for glue, Python for logic.** Rejected: two toolchains, weaker testability.
- **Per-skill scripts only (no shared lib).** Rejected: duplication across skills.
- **Shared lib only (no per-skill scripts).** Rejected: breaks the standard's
  `scripts/` convention and `${CLAUDE_SKILL_DIR}` portability.

## Consequences

- Uniform tooling (uv, pytest, ruff, mypy) and a single import surface.
- Skill-specific scripts add `plugin/lib` to `sys.path` or use the installed package.
