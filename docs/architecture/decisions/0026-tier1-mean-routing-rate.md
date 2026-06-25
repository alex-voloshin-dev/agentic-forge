# 0026 — Tier-1 recall/specificity = mean routing-rate, not fraction-of-prompt-majorities

Status: Accepted (refines the metric of [ADR 0016](0016-tier1-trigger-runner.md))

## Context

The Tier-1 trigger gate (ADR 0016) measures, per skill, `recall = (# should_trigger prompts whose
majority-of-N routing selects the skill) / (# should_trigger prompts)`, and analogously
`specificity`, gated at ≥ 0.9. Concretely (`tier1_runner.eval_skill`):

```python
st_hits[i] = (majority_selection(prompt, runs) == skill)   # a BOOL per prompt (majority wins?)
recall = sum(st_hits) / len(st_hits)                        # fraction of prompt-majorities
```

This double-thresholds — a majority cliff at 50% per prompt, then a 0.9 fraction across prompts —
with two bad consequences:

- **Brittle.** A prompt that routes at ~50% has a coin-flip majority, so `recall` flickers between
  e.g. 0.8 and 1.0 across identical runs. This cost real re-runs in Stages 4–6 (e.g.
  `repo-onboarding` failed at 0.75 on one run while all four prompts route ~100%, and passed on
  re-roll).
- **Paradoxically weak.** A skill that routes *every* prompt at 55% has every majority "technically"
  on the skill, so `recall = 1.0` (PASS) — the gate rubber-stamps 55% routing.

## Decision

Measure recall/specificity as the **mean per-prompt routing rate** over the N samples, threshold
**0.9 unchanged**:

```python
st_rates[i] = selection_rate(prompt, runs)   # fraction of N samples routed to the skill (0..1)
recall = mean(st_rates)                       # mean routing rate
# specificity = mean per-prompt rate of NOT wrongly selecting the skill
```

`selection_rate` (fraction of N classifications equal to the skill) replaces the
majority-collapse in the metric; `gate.trigger_metrics` averages rates instead of summing bools.

### Why this is not a lowering — it is higher-fidelity *and* stricter

| Scenario (5 prompts) | Current | Mean-rate (this ADR) |
| --- | --- | --- |
| 4×100% + 1×~50% (flicker zone) | recall **swings 0.8 ↔ 1.0** | ≈ 0.90, **stable** |
| **every prompt routes 55%** | all majorities on skill → **1.0 PASS** ⚠️ | 0.55 → **FAIL** ✅ |
| 4×100% + 1×45% | 0.8 FAIL | 0.89 FAIL (agrees) |

The mean rate demands ~90% *actual* routing rather than ">50% majority on each prompt"; it catches
the barely-majority skills the current metric passes, and it is stable for genuinely-good skills.

## Migration

- Change `tier1_runner` (add `selection_rate`; `eval_skill` collects rates) and
  `gate.trigger_metrics` (mean of rates). `majority_selection` is retained only if still used
  elsewhere, else removed. Threshold config (`tier1_trigger.recall/specificity = 0.9`) is untouched.
- Update `tests/test_tier1_runner.py` + `tests/test_gate.py` for the rate-based metric.
- **Re-validate Tier-1 for all on-listing skills** under the new metric (the deferred "debt
  sweep"). Diagnostics show the skills route ~95–100%, so they pass at mean ≥ 0.9; any skill that
  was only passing on barely-majority routing will now (correctly) fail and gets its description
  sharpened.

## Alternatives considered

- **Keep the majority metric, raise N** to damp the flicker — rejected: more expensive every run,
  and it does not fix the "55%-everywhere passes" weakness (the cliff remains).
- **Lower the 0.9 threshold** — rejected outright; the goal is a *fairer* metric at the *same* bar,
  not an easier bar.
- **Report both metrics** — rejected as noise; the mean rate strictly dominates for the gate.

## Consequences

- Tier-1 stops flaking → far fewer wasted re-runs on future stages/connectors; the gate also
  becomes a stronger routing-accuracy signal.
- The runner reports per-prompt rates (richer diagnostics: you see *how* well each prompt routes,
  not just pass/fail).
- Refines ADR 0016's metric; the runner architecture, transports, and 0.9 thresholds are unchanged.

## Exit criteria

- `gate.trigger_metrics` + `tier1_runner` rate-based; tests updated; Tier-0 + suite green.
- All on-listing skills re-validated at mean recall/specificity ≥ 0.9 (numbers recorded).
- `eval-runbook.md` Tier-1 section updated to describe the mean-rate metric.
