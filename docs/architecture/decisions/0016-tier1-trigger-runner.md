# 0016 — Tier-1 trigger runner on live skill descriptions

Status: Accepted

## Context

The eval pyramid (ADR 0003) makes Tier-1 — should-trigger **recall** ≥ 0.9 and
should-not-trigger **specificity** ≥ 0.9 — a gate for every router skill, and each on-listing
skill already declares `thresholds.tier1_trigger` plus `triggers.should_trigger` /
`should_not_trigger` prompts in its `evals.json`. But there was no runner: the pure functions
`gate.trigger_metrics` / `gate.tier1_trigger` had **no production caller** (only unit tests),
the spine's Tier-1 numbers came from an ad-hoc "majority-of-N router sim," and CI's skill
Tier-1/2 step was a literal `echo "TODO"`. So the gate did not actually measure triggering
against the **live** skill listing (the real `name: description` set the router sees).

We need a runner that measures recall/specificity by asking the router to choose among the
**actual on-listing descriptions**, so the gate reflects real routing rather than a hand-coded
simulation.

## Decision

- **A `lib/agentic_forge/tier1_runner.py`** that (a) builds the live always-on listing — every
  **model-invocable** skill's `name` + `description`, excluding `disable-model-invocation`
  skills (the stack packs / `engineering-standards` are off-listing and not router-triggered) —
  and (b) for each skill that declares `tier1_trigger`, classifies each of its trigger prompts
  against that listing.
- **The router is a single classification call; reuse the agent runner's transports.** The
  `agent_eval.Runner` seam (`claude_cli_runner` / `api_runner`) is reused with tools disabled
  and one turn: system = a router instruction + the rendered live listing, user = the trigger
  prompt, output = the chosen skill name (or `none`). No new transport.
- **Grading is deterministic** (no LLM judge, unlike Tier-2): a `should_trigger` prompt must
  select the skill (counts toward recall); a `should_not_trigger` prompt must **not** select it
  (counts toward specificity).
- **Majority-of-N sampling** (default N = 5) absorbs router stochasticity — the selection for a
  prompt is the modal choice across N calls.
- **Gate through the existing pure functions** `gate.trigger_metrics` + `gate.tier1_trigger`
  (recall/specificity ≥ 0.9 from the contract), so Tier-1 shares the same policy layer as the
  rest of the pyramid and those functions gain a real production caller.
- **CLI `dev/run_tier1_evals.py`** mirrors `run_agent_evals.py` (`--runner dry|claude|api`,
  `--skill`, `--model`, `--runs`); `dry` checks wiring with no model calls. CI's `eval.yml`
  TODO step is replaced by a real, cost-gated invocation.

## Alternatives considered

- **Keep the hand-coded router sim:** rejected — it does not exercise the live descriptions, so
  it drifts from real routing and can't catch a description that reads well in isolation but
  collides with a neighbour in the actual listing.
- **A bespoke router transport:** rejected — the router is one classification call; reuse
  `agent_eval`'s proven subscription/API plumbing instead of duplicating it.
- **LLM-judge grading (like Tier-2):** rejected — Tier-1 grading is a deterministic
  set-membership check ("did the router pick skill S?"), so a judge would only add cost and noise.
- **Eval every skill, including the off-listing packs:** rejected — packs are
  `disable-model-invocation` and never router-triggered; Tier-1 applies to the on-listing router
  skills only (the packs' readiness is a Tier-2 concern — see ADR 0015 and the eval-runbook).

## Consequences

- The eight on-listing skills (`research`, `product`, `architecture`, `plan`, `develop`,
  `code-review`, `deep-review`, `skill-factory`) get a real, repeatable Tier-1 gate measured on
  live descriptions; the "router sim" wording in `spine.md` is replaced by this runner.
- `gate.trigger_metrics` / `gate.tier1_trigger` go from test-only to production callers.
- CI can enforce skill Tier-1 (cost-gated on the subscription token), replacing the TODO no-op.
- Off-listing packs remain Tier-1-exempt **by design**, documented here and in the eval-runbook.
- Builds on ADR 0011 (the agent Tier-2 runner, whose transport seam this reuses); does not
  supersede it.
