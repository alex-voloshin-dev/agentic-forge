# 0041 — Plugin settings & configuration

Status: Accepted — **implemented** (planned-increment 3; see the [Unreleased] CHANGELOG entry).

## Context

Plugin configuration is scattered, ad-hoc env vars (`AGENTIC_FORGE_DIAGNOSTICS`,
`AGENTIC_FORGE_SUBAGENT_SOFT` / `_HARD`, `AGENTIC_FORGE_SKIP_TEST_GATE`), each read independently at
its consumer. The roadmap's planned increments need a single, documented, validated configuration
surface — "enable the log collector", "enable the external reviewer", "set the review passes",
"pick a model tier". This is **planned-increment 3**, the foundational one: increments 2 (external
reviewer) and 4 (multi-model) read their toggles from it.

## Decision

1. **One settings module + a per-repo config file.** `lib/agentic_forge/settings.py` resolves a
   `Settings` (frozen dataclass) from `.agentic-forge/config.json` in the target repo, validated
   against `plugin/schemas/config.schema.json` (Draft-7, reusing the existing `jsonschema` dep). The
   file is **committed** (un-ignored via `!.agentic-forge/config.json`, since `.agentic-forge/` is
   otherwise the gitignored runtime dir for logs / state).

2. **Precedence: defaults < file < env.** Built-in `DEFAULTS` (= today's behaviour) are overlaid by
   the config file, then by the documented env vars — so CI / one-off overrides still work and the
   existing env vars stay back-compatible. `resolve(repo, *, env=None)` is the single entry; the
   merge + precedence is unit-tested.

3. **Never raises; degrades to defaults.** A missing file → defaults. A malformed / schema-invalid
   file → defaults + a one-line stderr warning. Settings must not break a session, and must **not
   depend on diagnostics** (that would be circular — diagnostics reads settings).

4. **Unify the existing consumers.** `diagnostics` (the log-collector toggle), `budget` (subagent
   soft/hard caps), and `commit_gate` (skip-test-gate) now read `settings.resolve(...)` instead of
   `os.environ` directly — same env vars, one resolver. The diagnostics enabled-check moves behind
   settings, so the **config file** can enable the channel (not only the env var).

5. **Forward keys for the next increments.** The schema / `DEFAULTS` already declare `review.passes`
   (the bounded-loop `N` — consumed now as the `review-scan` cap), `external_reviewer.{enabled,
   command}` (increment 2), and `models` (a tier → model map, increment 4). They are inert until
   those increments consume them — declared here so the config surface is stable.

## Alternatives considered

- **TOML config:** rejected — JSON matches the repo's existing schema tooling (`jsonschema` + the
  evals / handoff schemas); no new parser, one validation path.
- **Keep per-consumer env vars only:** rejected — the status quo the roadmap flagged; it can't
  express "enable the log collector" from a committed file and doesn't scale to increments 2 / 4.
- **A `Settings` singleton / global:** rejected — `resolve(repo, env)` is explicit + testable (no
  hidden global state; consistent with the lib's pure-core style).

## Consequences

- A single, validated, documented config surface; the three existing env vars keep working (now via
  settings) and the config file can set them durably.
- `diagnostics` / `budget` / `commit_gate` behaviour is unchanged by default (`DEFAULTS` = today);
  only the *source* of config is unified.
- Increments 2 (external reviewer) and 4 (multi-model) have their config keys ready;
  `review.passes` already drives the `review-scan` cap.
