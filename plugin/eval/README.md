# Eval harness (hybrid on skill-creator)

agentic-forge does not reimplement the eval engine. It uses the official
[`skill-creator`](https://github.com/anthropics/skills/tree/main/skills/skill-creator)
loop to run and grade skills, and adds a thin **policy layer** that turns the engine's
output into a pass/fail decision against our numeric thresholds.

## Division of labour

| Concern | Owner |
| --- | --- |
| Run each test case with/without the skill in isolated subagents | skill-creator |
| Grade assertions -> `grading.json` (`text`/`passed`/`evidence`) | skill-creator |
| Capture `timing.json` (`total_tokens`, `duration_ms`) | skill-creator |
| Aggregate runs -> `benchmark.json` shape | `lib/agentic_forge/benchmark.py` |
| Apply threshold gate (Tier 1 trigger, Tier 2 quality) | `lib/agentic_forge/gate.py` |
| Static checks (Tier 0) | `lib/agentic_forge/validation.py` + `dev/validate.py` |
| Scripts / hooks tests | `pytest` |

## Single-file contract

Each component ships exactly one `evals/evals.json`. It is a **superset** of the
skill-creator format (see `plugin/schemas/evals.schema.json`):

- `skill_name`, `evals[]` — read by skill-creator.
- `component`, `thresholds`, `triggers` — read by agentic-forge; ignored by skill-creator.

This keeps one source of truth while staying compatible with the upstream engine.

## The eval pyramid (definition of done)

1. **Tier 0 — static** (always blocks): `dev/validate.py`, `pytest`, `ruff`, `mypy`.
2. **Tier 1 — trigger**: `should_trigger` recall and `should_not_trigger` specificity,
   gated by `thresholds.tier1_trigger`.
3. **Tier 2 — quality**: LLM-judged pass-rate over N>=5 runs, gated on the lower bound
   (`mean - stddev`) by `thresholds.tier2_quality`, plus token/time overhead budgets.
4. **Tier 3 — E2E**: workflow scenarios (added with the workflow layer).

## Flow

```
skill-creator runs ──> grading.json (per run)
                         │
        benchmark.summarize(with_skill, without_skill)
                         │
                    benchmark.json
                         │
   gate.evaluate(evals.json, benchmark=..., trigger_measured=...)
                         │
                  GateResult per tier  ──> pass/fail
```

Run artifacts (`grading.json`, `timing.json`, `benchmark.json`, iteration dirs) are
generated and git-ignored. The only hand-authored eval file is `evals/evals.json`.
