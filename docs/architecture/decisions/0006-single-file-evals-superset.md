# 0006 — One `evals.json` superset file

Status: Accepted

## Context

skill-creator reads `evals/evals.json` with `skill_name` and `evals[]`. agentic-forge also
needs `component`, `thresholds`, and `triggers`. We want one source of truth, not parallel
files to keep in sync.

## Decision

Make our `evals/evals.json` a **superset** of the skill-creator format. skill-creator reads
its keys; agentic-forge reads the extra keys; skill-creator ignores unknown keys. The
schema (`schemas/evals.schema.json`) requires the union and rejects malformed contracts.
Each eval's `assertions` are plain strings, matching the upstream format exactly.

## Alternatives considered

- **Two files** (`evals.json` + our `contract.json`). Rejected: duplication and drift, even
  if more isolated.
- **Our own format, adapt at runtime.** Rejected: more glue code, and loses the "just works
  with skill-creator" property.

## Consequences

- One file serves both consumers; Tier-0 validates the superset.
- We depend on skill-creator tolerating unknown keys. If that ever breaks, fall back to the
  two-file alternative; the gate logic is unaffected.
