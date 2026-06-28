# 0024 — Stage 7: scheduling & observability (no daemon — declarative jobs + audit digest)

Status: Accepted (extended by [ADR 0031](0031-scheduling-cadence-persistence.md))

## Context

ADR 0019 shipped L4 as the four guardrail hooks and **deferred scheduling and observability** as a
follow-on, because scheduling is headless *cadence*, not a guardrail. This increment adds them.
Design in [scheduling-observability.md](../scheduling-observability.md). It introduces **no new
model-invocable skills**, so it is gated by `pytest` + Tier-0, not Tier-1/Tier-2.

## Decision

- **No daemon — declarative jobs + external clock.** A plugin can't run a scheduler, so scheduling
  is: a declarative job registry + **pure due-logic** in `lib/agentic_forge/schedule.py`
  (`due_jobs(jobs, last_run, now)` — timestamps passed in, fully tested), a thin runner CLI
  (`dev/run_scheduled.py`), and a cron-triggered CI workflow (`.github/workflows/scheduled.yml`,
  `schedule:`) — or OS cron — as the clock. Last-run timestamps persist as JSON under
  `.agentic-forge/`; real cadence needs that state to persist across runs (a target repo
  commits/caches it), so in an ephemeral CI checkout the run is a wiring smoke.
- **Built-in jobs reuse existing libs.** `kb-maintenance` (weekly) → `vault.validate_vault`;
  `deploy-digest` (daily) → `ops.deploy_status` (degrades to a clear "no provider source
  configured" until a connector is wired); `audit-digest` (daily) → the observability digest.
- **Observability = digest the existing audit log.** The `logging` guardrail hook already writes a
  redacted `{tool, input, session_id}` JSONL to `.agentic-forge/audit.jsonl`. `observability.py`
  **reads** it: `digest(lines)` → total / per-tool counts / distinct sessions / busiest tool
  (pure, tested), `render` → a compact report, plus a `dev/audit_digest.py` CLI. No new event
  schema — it consumes what L4 already records.
- **No new skill.** Scheduling is set-up-once infrastructure, not a conversational workflow, so it
  is lib + CLI + CI (router discipline). A thin `maintain` skill can come later if ad-hoc demand
  appears.

## Alternatives considered

- **A `schedule` / `maintain` skill** — deferred (router discipline); the work reuses `vault` /
  `ops`, and cadence is wired via CI, not invoked in chat.
- **A long-running daemon** — impossible in a plugin; CI/OS cron + a headless runner is the native
  pattern (Ralph loop / headless runs).
- **A web observability dashboard** — out of scope for a CLI plugin; the digest is a text report.
  A richer dashboard remains a possible follow-on.
- **A new audit event schema with timestamps/decisions** — rejected for now; digest what the
  logging hook actually records. Enriching the audit record is a separate, additive change.

## Consequences

- `schedule.py` + `observability.py` (pure cores, 100% covered) + two `dev/` CLIs + a cron CI
  workflow; ties Stage 7 back to the L4 audit log and the L3 vault.
- Cadence is real only where the last-run state persists; the CI template documents that.
- Follow-ons: real provider connectors for `deploy-digest`, persisted-state cadence in a target
  repo, and (if wanted) a richer dashboard.

## Exit criteria

- `schedule.py` + `observability.py` unit-tested (100%); `due_jobs` / `digest` pure + deterministic.
- `run_scheduled.py --dry` green; `audit_digest.py` runs on an empty/sample log.
- `scheduled.yml` valid; Tier-0 + full suite green.
- Docs: this ADR, scheduling-observability.md, roadmap (Stage 7 → built) / overview, CHANGELOG.
