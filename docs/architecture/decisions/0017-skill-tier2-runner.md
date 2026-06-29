# 0017 — Automated skill Tier-2 quality runner

Status: Accepted

## Context

Tier-2 quality (pass-rate lower bound `mean − σ ≥ 0.8` over N ≥ 5 runs) is declared by twelve
**skills** — `deep-review`, `skill-factory`, `engineering-standards`, and the nine `*-patterns`
stack packs — but had **no automated runner**. The eval-runbook honestly scoped it as a manual
LLM-judge step (the deep-review pass corrected an earlier overstatement that the packs were
"exercised through the software-engineer's Tier-2"; in fact nothing wired them). The agent
runner (`agent_eval`, ADR 0011) gates Tier-2 for the six **roles** with exactly this machinery —
run the component on its cases, grade each output against the case's assertions with the
`grader` role, aggregate with `benchmark.summarize`, gate with `gate.tier2_quality`. Skill
Tier-2 is the same shape; the only differences are where the contract lives and how the
"component under test" is executed.

A knowledge skill is special: `engineering-standards` and the `*-patterns` packs are off-listing
(`disable-model-invocation: true`) and carry no behaviour of their own — their quality only
manifests when a role **applies** them. So testing a pack means running the role that loads it.

## Decision

- **`lib/agentic_forge/skill_eval.py`** runs Tier-2 for every skill that declares
  `tier2_quality`, reusing the agent runner's policy layer. The careful per-run loop (grading,
  the pass-rate cap, write-role isolation, aggregate-over-expected-counts) is **extracted from
  `agent_eval.run_role` into a shared `run_eval_cases`** so there is one eval core, not two.
- **Execution context per skill:**
  - **Off-listing knowledge skill** (`engineering-standards`, `*-patterns`): execute *as the
    `software-engineer`* with the knowledge loaded — system prompt = the `software-engineer`
    body + `engineering-standards` body (+ the pack body for a `*-patterns` skill), the
    `software-engineer`'s tools, **isolated** (it writes code), graded against the **skill's
    own** assertions (typed / tested / stack-idiomatic output). This makes the long-claimed
    "exercised through the software-engineer's Tier-2" actually true.
  - **On-listing skill** (`deep-review`, `skill-factory`): execute the skill directly — system
    prompt = the skill body, the skill's own `allowed-tools`, isolated iff it writes
    (Write/Edit), graded against its assertions.
- **Grade with the `grader` role** (read-only, level-2, verifies on-disk artifacts), aggregate
  with `benchmark.summarize`, gate with `gate.tier2_quality` — the same policy layer as agent
  Tier-2 and Tier-1.
- **CLI `dev/run_skill_evals.py`** mirrors `run_agent_evals` / `run_tier1_evals`
  (`--runner dry|claude|api`, `--skill`, `--model`, `--runs`); `dry` checks wiring with no model
  calls. CI's `eval.yml` runs a dry + cost-gated subscription pass, replacing the "manual" note.

## Alternatives considered

- **With/without-skill delta (skill-creator style):** rejected for now — our `gate.tier2_quality`
  uses an absolute pass-rate lower bound, not a delta; measuring the delta doubles cost and isn't
  needed to answer "does the skill yield quality output." (Can be added later if marginal-lift is
  wanted.)
- **Duplicate the eval loop in `skill_eval`:** rejected — copying the pass-rate cap / isolation /
  aggregation logic invites drift in gate-critical code; extract one shared `run_eval_cases`.
- **Test the packs in isolation (no role):** rejected — a knowledge pack has no behaviour on its
  own; `software-engineer` + pack is the faithful execution, and it's exactly what the
  completeness review recommended.

## Consequences

- **All four tiers now have automated runners** (Tier-0 `validate.py`, Tier-1
  `run_tier1_evals.py`, Tier-2 roles `run_agent_evals.py` + skills `run_skill_evals.py`, Tier-3
  `run_spine_e2e.py`); skill Tier-2 is no longer a manual step.
- The earlier honest gap ("the packs' `tier2_quality` has no execution path") is **closed** — the
  eval-runbook scope note is updated accordingly.
- Pack runs are the **most expensive** eval (a full `software-engineer` coding session per case ×
  N runs); cost-gated in CI, `--runs` configurable for local use.
- `agent_eval` gains `run_eval_cases` (shared core); `run_role`'s external behaviour and
  `RoleReport` are unchanged. Builds on ADR 0011; does not supersede it.

## Note (count grew with later stages)

The "twelve skills" above is the set that declared `tier2_quality` at the time of this decision. The
machinery is unchanged, but later stages added own-behaviour skills that also declare it — Stage-4
ops/release (`deploy-watch`, `incident-response`, `release`; ADR 0021), Stage-5 `marketing` (ADR
0022), and Stage-6 `repo-onboarding` / `ux-design` (ADR 0023). The runner (`skill_eval.py`) runs
Tier-2 for **every** skill that declares the threshold, so the live count is higher than twelve;
the decision and its execution model are as written.
