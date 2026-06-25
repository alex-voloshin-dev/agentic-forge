# The eval loop

agentic-forge uses the official `skill-creator` loop as the engine for **skills** and adds a
deterministic threshold gate. (Subagents are evaluated by a dedicated runner instead — see
`plugin/eval/README.md` and ADR 0011.)

## 1. Write the contract (evals/evals.json)

Single superset file (schema: `plugin/schemas/evals.schema.json`). It is read by both
skill-creator (`skill_name`, `evals`) and agentic-forge (`component`, `thresholds`,
`triggers`). Copy `assets/evals.template.json` and fill in:

- `skill_name` — the component name.
- `evals[]` — 2-3 realistic cases: varied phrasing, one edge case, realistic context
  (paths, names). Add `assertions` (array of strings) — specific, verifiable, not brittle.
- `component` — `{id, type, purpose}`.
- `thresholds` — start at `tier1_trigger: {recall: 0.9, specificity: 0.9}` and
  `tier2_quality: {min_pass_rate: 0.8, runs: 5}`. Recalibrate and record why.
- `triggers` — `should_trigger` / `should_not_trigger` prompt sets for Tier 1.

## 2. Tier 0 — static (always first)

```
python dev/validate.py
pytest -q
ruff check .
mypy plugin/lib dev
```

All must be clean before spending tokens on quality evals.

## 3. Tier 1 — trigger

Run each `should_trigger` and `should_not_trigger` prompt in a fresh session and record
whether the skill activated. Routing is stochastic, so **sample each prompt N times (e.g. 3)
and take the majority** before scoring it a hit/miss — the same absorb-the-noise principle as
Tier-2's N runs; a single sample can flip a borderline prompt and fail the gate spuriously.
Compute metrics and gate:

- `agentic_forge.gate.trigger_metrics(should_trigger_rates, should_not_trigger_rates)` — per-prompt
  routing rates in [0,1]; recall/specificity are their means (ADR 0026)
- `agentic_forge.gate.tier1_trigger(measured, thresholds)`

## 4. Tier 2 — quality

Run the skill-creator loop: each eval case with and without the skill, in isolated
subagents, graded to `grading.json`. Then:

- `agentic_forge.benchmark.summarize(with_skill, without_skill)` -> benchmark.
- `agentic_forge.gate.tier2_quality(benchmark, thresholds)` — passes only if the
  pass-rate lower bound (`mean - stddev`) over `runs` >= `min_pass_rate`, within overhead.

Use `N >= 5` runs so `stddev` is meaningful; gating on the lower bound absorbs LLM noise.

## 5. Iterate (bounded)

If a tier fails, improve the component from the failed assertions, human feedback, and
transcripts; rerun in a new `iteration-N/`. Cap iterations (e.g. 3-5) and stop when
green or when improvement plateaus. Record the final numbers next to the thresholds.
