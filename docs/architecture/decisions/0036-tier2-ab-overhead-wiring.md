# 0036 — Tier-2 A/B + overhead: wire the without-skill baseline and time-overhead gate

Status: Accepted — **implemented** (see the [Unreleased] CHANGELOG entry).

## Context

ADR 0035 deferred (did not delete) the dormant Tier-2 overhead / A-B scaffolding in
`benchmark.summarize` + `gate.tier2_quality`: those functions already compute a with/without
pass-rate delta and a token/time overhead delta, but the runners only ever passed `gradings` to
`summarize`, so the delta branches never fired — "harness-ready for when the runners capture
timing". Pass-rate (`mean − stddev ≥ min_pass_rate`) was the only live Tier-2 signal.

This ADR closes that gap for the two signals that are cheap and always available — **wall-clock
time-overhead** and the **with/without A-B pass-rate lift** — by capturing per-run timing in the
shared eval core and adding an opt-in without-skill baseline pass. Token-overhead and
version-over-version A-B stay deferred, with reasons below.

## Decision

1. **The shared eval core captures per-run wall-clock timing, always.**
   `agent_eval.run_eval_cases` (used by both the role and skill runners) now records one
   `{"duration_ms": …}` per run and feeds it to `benchmark.summarize(with_skill_timing=…)`. This is
   free (no transport change) and populates `with_skill.time_seconds` on every Tier-2 benchmark.

2. **An opt-in without-skill baseline produces the A-B delta.** `run_eval_cases` gained a
   `baseline_system_body` parameter; when set it runs every case a second time under that system and
   calls `summarize(with, without, with_timing, without_timing)`, producing
   `run_summary.delta = {pass_rate, time_seconds}` — exactly the shape `gate.tier2_quality` already
   consumes. `skill_eval.run_skill(with_baseline=True)` wires it; `dev/run_skill_evals.py --baseline`
   exposes it. It is **off by default** because it doubles eval cost.

3. **The baseline is the same executor with the skill under test removed.**
   `build_skill_baseline_system` returns: for an off-listing knowledge skill, the base role
   (+ `engineering-standards`, unless the skill under test *is* `engineering-standards`); for an
   on-listing skill, the bare base model (empty system). Holding the executor constant makes the
   delta isolate the skill's marginal contribution rather than a model swap. **Skills only** — a
   subagent role has no "without itself" baseline (ADR 0011), so the role runner passes no baseline
   and only the pass-rate lower bound applies to it.

4. **`gate.tier2_quality` gains a `min_lift` check.** When a contract sets `min_lift` *and* a
   baseline delta exists, `delta.pass_rate` must be `≥ min_lift` (the "A-B not worse / better by X"
   bar). Like the overhead checks it **skips when no baseline was run**, so a normal single-pass run
   is unaffected. `_EPS` boundary tolerance is reused.

5. **A-B thresholds are opt-in and calibrate-on-first-baseline-run.** We do **not** pre-set
   `min_lift` / `max_overhead_seconds` on any existing contract: a numeric bar can only be set
   honestly from a real baseline measurement, and CLAUDE.md forbids un-calibrated or lowered gates.
   The schema now accepts `min_lift`; `docs/eval-runbook.md` documents how to enable `--baseline`,
   read the delta, and set the bar.

6. **Token-overhead and version-over-version A-B remain deferred, deliberately.** Token-overhead
   needs the model transport (the `Runner` seam, which returns `str`) to surface usage — a
   cross-cutting seam change for a second-order signal; time is the cheap proxy. So `summarize` no
   longer emits a misleading `tokens: 0.0` when timing carries no token counts (it omits `tokens`
   and `delta.tokens` unless a count is present). Version-over-version A-B needs a stored benchmark
   history; the with/without baseline is the more actionable signal and is what `delta` models.
   **Update: both are now closed** — token-overhead by [ADR 0038](0038-token-overhead-wiring.md),
   version-over-version by [ADR 0047](0047-version-over-version-ab.md) (the stored history + a
   `max_regression` gate).

## Alternatives considered

- **Make `--baseline` the default (always double-run):** rejected — it doubles the most expensive
  eval (a full software-engineer session per case × N) for a refinement signal; pass-rate already
  gates quality. Opt-in, with the cost called out in the runner help and runbook.
- **Rewrite the `Runner` seam to return `(text, usage)` to wire token-overhead now:** rejected as
  scope creep — it touches every transport and stub test for a second-order metric. Time-overhead
  delivers the "is this skill expensive?" signal today; tokens are tracked as future work.
- **Pre-set `min_lift` on the knowledge skills to make the gate active immediately:** rejected — an
  un-calibrated threshold is exactly the un-calibrated gate the constitution forbids. Wire the
  mechanism now; set the bar from a real baseline run later.
- **Delete the scaffolding (ADR 0035's deferred option):** superseded — we wired the live half
  instead of removing it.

## Consequences

- The Tier-2 overhead / A-B code path is now real and exercised (under `--baseline`), not dormant:
  time-overhead and pass-rate lift gate when a contract opts in. The 4-tier pyramid no longer
  carries a "scaffolded but not wired" caveat for these two signals.
- Default runs are unchanged: single-pass, pass-rate-gated, no cost increase unless `--baseline` is
  set. Every benchmark now also reports `with_skill.time_seconds` (informational).
- `summarize` is honest about tokens: it reports them only when a transport supplies counts, so a
  time-only run shows no phantom `tokens: 0.0`.
- CLAUDE.md §4, `overview.md`, `meta-core.md`, and `eval-runbook.md` now state what is wired (time +
  A-B lift) and what is still deferred (token-overhead, version-A-B) with the reasons here.
