# 0049 — User-level (cross-project) plugin config layer

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

Plugin settings (ADR 0041) resolved from one file only — the per-repo `.agentic-forge/config.json`
— with precedence DEFAULTS < repo file < env. A user who wants the same preference in every project
(e.g. "always enable the diagnostics log", "route the router/grader to a cheaper model tier") had to
copy the file into every repo. There was no place to set a personal default once.

## Decision

Add a **user-level config layer**: `~/.agentic-forge/config.json` (the same relative path as the
repo file, under the user's home). `settings.resolve` now layers four sources, lowest to highest:

1. built-in `DEFAULTS`
2. **user-level** `~/.agentic-forge/config.json` (cross-project)
3. **per-repo** `<repo>/.agentic-forge/config.json` (overrides the user-level file)
4. documented **env vars** (override both files)

Both files are validated against the **same** `schemas/config.schema.json` and deep-merged, so a
repo overrides only the keys it sets and inherits the rest from the user-level file. `resolve` gains
a `home=` parameter (defaults to `Path.home()`) for tests/embedding. A committed, schema-valid
example with every key ships at `plugin/config.example.json`, documented in `docs/configuration.md`.

## Alternatives considered

- **XDG (`~/.config/agentic-forge/config.json`) or `~/.claude/...`:** rejected for now — mirroring
  the repo path (`~/.agentic-forge/config.json`) is the least surprising and keeps one mental model.
- **Merge order user > repo:** rejected — a repo's committed config is more specific to the work at
  hand and should win; the user layer is the personal *default*.
- **A separate user schema:** rejected — the knobs are identical; one schema avoids drift.

## Consequences

- A user sets a preference once in their home and it applies across projects, still overridable
  per-repo and by env. Both files stay secret-free (committed / home-local; secrets via env vars).
- Tests must isolate `HOME` so they never read the developer's real user config — an autouse
  `conftest` fixture points `HOME` at an empty dir (hermeticity).
- Extends ADR 0041; no change to the schema shape or the env-var contract.
