# 0047 — Version-over-version A/B: stored benchmark history + regression gate

Status: Accepted — **implemented** (closes the deferral in [ADR 0036](0036-tier2-ab-overhead-wiring.md)
§6 / [ADR 0038](0038-token-overhead-wiring.md); see the [Unreleased] CHANGELOG entry).

## Context

ADR 0036 / 0038 wired the **live** Tier-2 A/B (the component *with* vs *without* its body) — the
pass-rate lift (`min_lift`) and the time / token overhead — but explicitly **deferred**
version-over-version A/B because it "needs a stored benchmark history" (0036:55, 0038:52).

The two measure different things. With/without measures the value the component adds **now**.
Version-over-version measures whether an **edit** to the component **regressed** its quality versus
the **prior version** — the classic "did my prompt change make the reviewer worse?" There is nothing
to compare a fresh run against without a stored baseline of the prior run's numbers; that store is
exactly what was deferred.

## Decision

1. **A stored benchmark history** (`benchmark.py`): an append-only JSON list of records
   `{component, model, mean, stddev, n}`. `load_history` / `save_history` (I/O); `make_record`
   (pure extract from a benchmark dict) and `prior_record(history, component, model)` (pure — the
   most recent matching record). Keyed by **(component, model)** because Tier-2 is model-dependent:
   a regression check only compares same-model runs (a model switch starts a fresh baseline).

2. **A regression gate** — `gate.version_regression(benchmark, prior, thresholds)`. FAIL if the
   current `with_skill` mean dropped more than `max_regression` below the prior recorded mean.
   Returns **None — skip** — when there is no prior (first run) or no `max_regression` threshold, so
   version-over-version is **opt-in** and engages only once a baseline exists. It is a distinct,
   **cross-run** gate, separate from the single-run `tier2_quality`.

3. **Runner wiring** — `--record` + `--benchmark-history PATH` on both eval runners, via a shared
   `_eval_cli.version_check` helper. After each component's run it compares against the latest
   same-model record (the result is folded into the run's pass/fail) and, with `--record`, appends
   the current numbers — but **only for a healthy run** (it passed `tier2_quality` *and* did not
   regress), so a failing run never poisons the baseline. Default history path is the per-repo
   `.agentic-forge/benchmark-history.json`; point `--benchmark-history` at a committed path for
   cross-version / CI gating.

4. **`max_regression` in the evals.json schema** (`tier2_quality`), a number in `[0, 1]` (a
   pass-rate drop can't exceed 1.0 — same bounds as `min_lift`).

## Alternatives considered

- **Re-run BOTH versions live** (read the prior component body from git, run it now): rejected — 2×
  cost every run, and the deferral specifically called for a *stored* history (cheap: the prior
  run's numbers are reused). The live two-body path is already covered by with/without.
- **Store the baseline in `evals.json`:** rejected — Tier-2 numbers are run artifacts
  (model / time-dependent), not contract fields (CLAUDE.md); a separate history file keeps the
  contract clean.
- **Always-on (no threshold):** rejected — opt-in via `max_regression` + requires a prior, so normal
  runs are unaffected and a first run cannot "regress against nothing".
- **Record every run (incl. failing):** rejected — a failing or regressed run recorded as the
  baseline would hide the next regression; only healthy runs advance the baseline.

## Consequences

- The harness can now catch a **cross-version quality regression** — an edit that drops a component
  below its prior validated mean — closing the last deferred A/B piece. Opt-in; no behaviour change
  until `--record` builds a baseline and `max_regression` is set.
- History is per-(component, model); switching tiers (ADR 0043 / 0046) starts a fresh baseline,
  which is correct — the numbers are not comparable across models.
- The default history is per-repo (gitignored under `.agentic-forge/`); committing it (or pointing
  `--benchmark-history` at a tracked path) enables CI cross-version gating.
