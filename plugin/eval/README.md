# Eval harness (hybrid on skill-creator)

agentic-forge does not reimplement the eval engine. It uses the official **skill-creator**
plugin (install: `/plugin install skill-creator@claude-plugins-official`; source:
[anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator))
to run and grade skills, and adds a thin **policy layer** that turns the engine's output
into a pass/fail decision against our numeric thresholds.

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

The canonical definition lives in
[docs/architecture/overview.md](../../docs/architecture/overview.md#the-eval-pyramid-cross-cutting).
In short: Tier 0 static (always blocks) → Tier 1 trigger → Tier 2 quality (LLM judge,
N≥5, lower-bound gate, overhead budget) → Tier 3 E2E. This file covers how the harness
implements Tiers 1–2.

## Flow

```
skill-creator runs ──> grading.json + timing.json (per run)
                         │
   benchmark.summarize(with_skill, without_skill, *_timing=…)
                         │
            benchmark.json (pass-rate + token/time delta)
                         │
   gate.evaluate(evals.json, benchmark=..., trigger_measured=...)
                         │
                  GateResult per tier  ──> pass/fail
```

Run artifacts (`grading.json`, `timing.json`, `benchmark.json`, iteration dirs) are
generated and git-ignored. The only hand-authored eval file is `evals/evals.json`.
