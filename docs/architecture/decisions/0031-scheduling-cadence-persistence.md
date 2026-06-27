# 0031 — Scheduling cadence persistence: per-job state with retry

Status: Accepted (extends [ADR 0024](0024-stage7-scheduling-observability.md))

## Context

[ADR 0024](0024-stage7-scheduling-observability.md) shipped headless scheduling as a deterministic
registry + a pure `due_jobs` due-logic, persisting only a flat `{job_name: last_run}` timestamp
map. That minimal state has two gaps that surface in real headless operation:

- **No retry.** A job that *failed* still advanced its `last_run`, so a broken weekly job would
  not run again for a whole week — the failure is silently swallowed until the next cadence window.
- **No history / outcome.** The state recorded *when* a job ran, never *whether it succeeded* or
  *how often* — so there is nothing for observability to report on (run counts, failure streaks).

## Decision

Enrich the persisted per-job state and the due-logic, keeping the pure/tested core and the
no-daemon model.

- **`JobState`** replaces the bare timestamp: `last_run`, `status` (`ok` | `failed` | `""`),
  `runs`, and `failures` (consecutive, reset on success).
- **`due_jobs`** is now retry-aware: a job is due when it has never run, when its cadence has
  elapsed, **or when its last run failed and it has not exhausted `MAX_RETRIES`** (a bounded retry
  on the next poll, after which it backs off to its normal cadence so a persistently-broken job
  can't run every poll).
- **`record_run(state, name, now, *, ok)`** is the pure outcome-recorder (advances `last_run`,
  increments `runs`, sets `status`, resets/increments `failures`); the runner calls it after
  executing each action, **wrapping the action so a job failure is recorded rather than crashing
  the whole run** (fail-open, consistent with the guardrail hooks).
- **`load_state` migrates** legacy flat `{name: last_run}` files into `JobState` transparently, so
  upgrading an existing project needs no manual step.

## Alternatives considered

- **Keep the flat `{name: last_run}` map:** rejected — it cannot express retry or history, the two
  things real headless cadence needs.
- **Unbounded retry of failed jobs:** rejected — a poison job would run on *every* poll forever;
  `MAX_RETRIES` then cadence-backoff bounds the blast radius.
- **Anchored, drift-free schedules** (persist a `next_due` computed from `last_scheduled + interval`
  rather than "elapsed since the last actual run"): deferred — a larger semantic change, not needed
  while the external cron sets the polling rhythm; the `JobState` shape leaves room to add it later.
- **Per-(job, environment) state keys** (so `deploy-digest` tracks each environment separately):
  deferred behind the same state shape until a multi-environment digest is actually configured.

## Consequences

- Failed scheduled jobs **self-heal within the polling rhythm** instead of waiting a full cadence,
  bounded by `MAX_RETRIES`.
- The state now carries **run history** (`runs` / `failures` / `status`) — available for a future
  observability rollup of scheduled-job health (no consumer yet; the data is now there).
- The state-file shape changed, but `load_state`'s migration keeps old files working; `schedule.py`
  stays 100% covered and the due-logic stays pure (timestamps passed in).
- Scope held tight: anchored scheduling and per-environment keys are explicitly deferred, recorded
  here so the omission is a decision, not an oversight.
