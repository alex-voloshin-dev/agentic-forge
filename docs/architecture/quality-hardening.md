# Quality-hardening increments (post-spine)

Status: **Built — all three shipped** (ADR 0032/0033/0034; live-clean guards, gate green; hardened by a deep multi-reviewer review). Three independent increments that strengthen what the live Tier-3
sweep and the constitution exposed as soft — **no new SDLC domains**. Each has its own ADR; this
doc is the plan (scope, contracts, deterministic checkpoints, exit criteria, sequencing).
Implement after this is agreed (contract → evals → implementation → gate), then a final deep review.

## Why these three

- The live Tier-3 sweep proved skills **under-specify the frontmatter their handoff schema
  requires** (`ux-design` omitted `feature`/`status` → systematic schema-validation failures, fixed
  only for that one). → **#1 handoff-contract guard.**
- `CLAUDE.md` states workflows **read the knowledge vault to enrich context**, but the spine phases
  don't recall prior notes today (only the session-start hook injects a summary). → **#2 knowledge
  recall in the spine.**
- `spine.md` explicitly defers develop's "implement the step's components (sequential, one worktree
  in v1) — impl parallelism deferred". → **#3 develop parallelism.**

## 1. Handoff-contract guard — [ADR 0032](decisions/0032-handoff-contract-guard.md)

**Goal:** skills reliably emit schema-valid handoff artifacts; catch skill-body ↔ schema drift
deterministically (so retry masks less).

**Contract:**
- A `SKILL_HANDOFF` mapping (skill name → handoff type) in `lib/` (research→research-brief,
  product→prd, architecture→tech-design, plan→plan, code-review→review, security-review→review,
  qa-test-strategy→test-strategy, release→release, deploy-watch→deploy-status,
  incident-response→incident, marketing→market-brief, ux-design→ux-spec, repo-onboarding→onboarding).
- `handoff_contract_problems(plugin_dir)` (pure-ish): for each mapped skill, its `SKILL.md` body
  must mention **every required field** of its handoff schema (from `handoff.SCHEMAS`) and cue valid
  frontmatter. Returns a list of problems (empty = clean).
- A **pytest guard** asserts it is clean; unit tests use a synthetic skill missing a field (flagged)
  and a complete one (clean).

**Checkpoints / exit:** guard green for all mapped skills; the gaps it surfaces are fixed in the
skill bodies; its own unit tests cover pass + fail; coverage ≥ 80%.

## 2. Knowledge recall in the spine — [ADR 0033](decisions/0033-knowledge-recall-in-spine.md)

**Goal:** realize the constitution's "workflows read the vault to enrich their context".

**Contract:**
- Each spine phase (`research`, `product`, `architecture`, `plan`, `develop`, `code-review`) gains a
  **"Recall prior context"** process step: recall relevant notes from the knowledge vault
  (`docs/knowledge/`, via the `knowledge` skill / `vault.recall`) and factor prior decisions in
  before producing its artifact.
- A shared reference `patterns/knowledge-recall.md` (the step, when to use it, how to cite recalled
  notes), referenced by the phases.
- A **guard test**: each spine skill body references the recall step / the pattern (presence check).

**Checkpoints / exit:** each spine body has the step and links the pattern; guard test green; Tier-0
green. (Quality of recall is exercised by the existing knowledge Tier-2 + the spine Tier-3.)

## 3. develop parallelism — [ADR 0034](decisions/0034-develop-parallelism.md)

**Goal:** implement **independent** plan tasks concurrently across git worktrees, respecting
dependency order (spine.md's deferred item).

**Contract:**
- `plan_batches(tasks)` in `lib/` (pure): topological **levels** of plan tasks by their `deps` —
  each level is a set of mutually-independent tasks that may run in parallel; raises on a dependency
  cycle or an unknown dep. Fully unit-tested.
- The `develop` skill body: for each dependency level, **fan out** one `software-engineer` per
  independent task in its **own worktree** (concurrent), then **integrate** (merge in order) and run
  the multi-aspect review; sequential only along a dependency chain. v1 keeps the existing
  single-task path when the plan has no parallelism.
- A pattern reference `patterns/worktree-parallel.md` (fan-out across worktrees + integration/merge
  order + conflict handling), built on `fan-out-fan-in` + `worktree`.

**Checkpoints / exit:** `plan_batches` unit-tested (levels, single chain, cycle, unknown dep);
`develop` body describes the parallel flow and references the pattern; Tier-0 green.

## Sequencing & parallelization

The three are **independent** by file surface — #1 is `lib/` + a test, #2 is skill bodies + a
pattern, #3 is `lib/` + the `develop` body + a pattern — so implementation can run in parallel
(isolated worktrees to avoid edit races). The only serialized touch points are the **CHANGELOG**
and the **ADR index**, merged once. Each increment lands behind the full Tier-0 gate; a **final deep
multi-reviewer review** checks all three together before close.

## Exit criteria (all three)

1. Tier-0 green at every commit: `validate` + `pytest` (coverage ≥ 80%) + `ruff` + `mypy`.
2. Each increment's guard/test is green and the gaps it surfaces are fixed.
3. Docs + CHANGELOG updated per the documentation discipline; the three ADRs accepted.
4. The final deep review's confirmed findings are addressed.
