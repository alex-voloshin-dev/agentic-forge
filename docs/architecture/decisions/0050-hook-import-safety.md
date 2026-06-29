# 0050 — Guardrail hooks import on a dependency-light, version-robust path

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

The L4 guardrail hooks (ADR 0019) are wired in `hooks.json` as
`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<hook>.py"`. Claude Code runs that command with
whatever `python3` is first on PATH — which is **not** guaranteed to be the project's venv. On a
machine whose system `python3` is 3.9 without the plugin's third-party deps, every Bash tool call
raised a traceback:

    from datetime import UTC, datetime
    ImportError: cannot import name 'UTC' from 'datetime'

`datetime.UTC` is 3.11+, and `jsonschema` / `PyYAML` were absent. The crash happened at module
**import**, before each hook's fail-open `try/except`, so the guardrail both spammed errors and was
disabled — violating ADR 0019's "a guardrail must never break the session."

## Decision

The hook-reachable import path must be **stdlib-only at import time** and must not assume Python
≥ 3.11:

- `diagnostics` uses `datetime.now(timezone.utc)` instead of `datetime.UTC` (3.9-compatible; the
  same value).
- `jsonschema` (in `settings`, `handoff`) and `PyYAML` (in `frontmatter`) are imported **lazily**
  inside the functions that use them, and **degrade gracefully** when absent: `settings` loads a
  committed config *unvalidated* (and coerces every value defensively, so `resolve` still never
  raises); `handoff.validate_header` skips validation; `frontmatter.parse` raises a clear
  `FrontmatterError` the callers already handle.

So the critical guardrails (security deny-list, test-gate, audit log) work on a bare `python3`;
only schema validation and vault parsing degrade when their optional deps are missing.

## Alternatives considered

- **Point `hooks.json` at the project venv:** rejected — the plugin cannot know the user's venv
  path; `${CLAUDE_PLUGIN_ROOT}` is the plugin dir, not their interpreter.
- **Wrap each hook's imports in `try/except` → exit 0:** rejected as the primary fix — it silently
  *disables* the guardrails instead of making them work; the existing per-hook fail-open stays, now
  backed by an import path that actually succeeds.
- **Vendor the deps into the plugin:** rejected — heavy; the logic only needs stdlib.

## Consequences

- No more import-time tracebacks regardless of which `python3` runs the hooks; guardrails function
  on a deps-less interpreter (config validation + vault injection degrade, security / test-gate /
  audit do not).
- A subprocess regression test (`tests/test_hook_import_safety.py`) blocks `jsonschema` / `PyYAML`
  and imports the whole hook chain, so a future top-level dep import fails the gate.
- Upholds ADR 0019; installing the deps (`pip install -e .`) still unlocks config validation + vault
  injection.
