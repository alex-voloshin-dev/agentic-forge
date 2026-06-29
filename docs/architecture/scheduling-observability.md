# Stage 7 — Scheduling & observability

Status: **Built** (ADR 0024).

The L4 guardrail hooks shipped in ADR 0019; **scheduling and observability** were deferred as a
follow-on because scheduling is headless *cadence*, not a guardrail (see ADR 0019). This increment
adds them. It introduces **no new model-invocable skills** — it is deterministic infrastructure
(lib + CLI + CI), so it is gated by `pytest` + Tier-0, not Tier-1/Tier-2.

## Constraint: a plugin has no daemon

A Claude Code plugin can't run a long-lived scheduler. So "scheduling" is three pieces:

1. a **declarative job registry** + due-logic in `lib/` (pure, tested),
2. a **headless runner CLI** (`dev/run_scheduled.py`) that runs the due jobs and records when each
   last ran,
3. a **cron-triggered CI workflow** (`.github/workflows/scheduled.yml`, GitHub Actions
   `schedule:`) that invokes the runner — the external clock.

Users who don't use GitHub Actions can invoke the same CLI from OS cron.

## Scheduling — `lib/agentic_forge/schedule.py`

- `Job(name, cadence, description, action)` — `cadence` is a coarse interval (`daily` / `weekly` /
  `monthly`); `action` is the seam (a callable / command id the runner maps to work).
- `JOBS` registry (the built-in scheduled work):
  - `kb-maintenance` (weekly): `vault.validate_vault` + a health report; flag broken links/orphans.
  - `deploy-digest` (daily): `ops.deploy_status` summary per configured environment.
  - `audit-digest` (daily): roll up the guardrail audit log (below).
  - `diagnostics-digest` (daily): roll up the diagnostics log into top recurring problems (ADR 0039).
- `due_jobs(jobs, state, now)` — **pure**: returns the jobs that should run — never-run, cadence
  elapsed, **or the last run failed and it is within `MAX_RETRIES`** (a bounded retry on the next
  poll, then back off to cadence). Deterministic + fully tested (timestamps passed in, never
  `Date.now()`).
- `record_run(state, name, now, *, ok)` — **pure**: record a job's outcome (advance `last_run`,
  bump `runs`, set `status`, reset/increment consecutive `failures`).
- State = a small JSON of per-job `JobState` (`last_run`, `status`, `runs`, `failures`) under
  `${CLAUDE_PROJECT_DIR}/.agentic-forge/`; legacy flat `{name: last_run}` files migrate on load
  (cadence persistence — ADR 0031).
- `health(jobs, state)` + `format_health(report)` — **pure**: a per-job health view (status /
  runs / consecutive failures / last-run, or `never-run`) from the persisted state — the
  scheduled-job observability rollup ADR 0031 left open.

## Observability — `lib/agentic_forge/observability.py`

The `logging` guardrail hook already writes a redacted audit JSONL (tool, brief, ts) under
`.agentic-forge/`. This module **reads** it:

- `digest(lines)` — **pure**: parse the JSONL records → a summary (total tool uses, counts by tool
  descending, distinct sessions, busiest tool). Deterministic + tested.
- `render(digest)` — a compact text report for the CLI / CI job.

This is the **usage** view (what ran). Errors, denials, and behaviour anomalies are a *separate*
channel — see Diagnostics below (ADR 0039); the earlier sketch of folding blocks/warnings/errors
into this usage digest was dropped in favour of that dedicated channel.

## Diagnostics — `lib/agentic_forge/diagnostics.py` (ADR 0039)

Self-troubleshooting: collect the plugin's own **errors + behaviour anomalies** so maintainers can
fix it. The guardrail hooks (security / commit_gate denials, budget warn/block, hook crashes) and
the dev eval runners (uncaught exceptions, gate FAILs) `emit` a redacted event to
`.agentic-forge/diagnostics.jsonl` **when capture is enabled** (`AGENTIC_FORGE_DIAGNOSTICS`). It is
**opt-in, never blocks, never leaks secrets** (`guardrails.redact_secrets`), and **local-only** (no
outward routing). `digest(lines)` groups events by **signature** into ranked "top problems";
`render` reports them. Pure logic + a thin I/O seam, mirroring observability.

## CLIs

- `dev/run_scheduled.py` — compute due jobs (`schedule.due_jobs`), run each (seam), and record each
  outcome (`schedule.record_run`; a failed job is retried next poll, not fatal). `--dry` lists what
  *would* run without running it (the roadmap's "dry-run green"); `--health` prints the per-job run
  history (status / runs / failures) without running anything.
- `dev/audit_digest.py` — print `observability.digest` of the audit log (a window flag).
- `dev/diagnostics_digest.py` — print `diagnostics.digest` of the diagnostics log (the "top
  problems" rollup of errors / denials / anomalies).

## CI

- `.github/workflows/scheduled.yml` — `on: schedule:` (e.g. daily cron) runs `run_scheduled.py`;
  also `workflow_dispatch` for manual runs. Mirrors the cost-gating pattern of `eval.yml` (jobs
  that call the model use the subscription token; pure jobs don't).

## Eval / gate approach

No skills → no Tier-1/Tier-2. Gated by **`pytest`** (schedule + observability cores, aim 100%) and
**Tier-0**, plus a **dry-run** of `run_scheduled.py`. The deterministic cores are the contract
(per the script convention; ADR 0020's note that `script`-type evals.json is reserved — pytest is
the contract).

## Alternatives considered

- **A `schedule` / `maintain` skill** — rejected for now (router discipline): scheduling is set up
  once via CI, not invoked conversationally; the work it runs reuses existing libs (`vault`, `ops`).
  Add a thin `maintain` skill later only if ad-hoc "run maintenance now" demand appears.
- **A real daemon / long-running scheduler** — impossible in a plugin; the CI/OS-cron + headless
  runner is the native pattern (Ralph loop / headless runs, CLAUDE.md L1).
- **A web observability dashboard** — out of scope for a CLI plugin; the digest is a text report.
  A richer dashboard remains a possible future follow-on.

## Exit criteria

- `schedule.py` + `observability.py` unit-tested (aim 100%); `due_jobs` / `digest` pure and
  deterministic.
- `run_scheduled.py --dry` green; `audit_digest.py` runs on a sample log.
- `scheduled.yml` valid; Tier-0 + full suite green.
- Docs: this design, an ADR, roadmap (Stage 7 → built) / overview, CHANGELOG.
