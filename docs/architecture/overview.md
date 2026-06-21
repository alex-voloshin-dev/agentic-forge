# Architecture overview

agentic-forge is a non-application asset repository: it produces a Claude Code plugin, not
a deployable service. Its architecture is organized as five concentric layers, built from
the inside out. The inner layers are machinery; the outer layers are the workflows users
actually experience.

## The five layers

```
┌──────────────────────────────────────────────────────────────┐
│ L4  Guardrails & observability  (hooks: security, gate, logs)  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ L3  Knowledge base  (Obsidian vault, recall, injection)    │ │
│  │  ┌──────────────────────────────────────────────────────┐ │ │
│  │  │ L2  Workflow skills  (one router per domain + depth)   │ │ │
│  │  │  ┌──────────────────────────────────────────────────┐ │ │ │
│  │  │  │ L1  Engine  (subagent roles + native patterns)     │ │ │ │
│  │  │  │  ┌──────────────────────────────────────────────┐ │ │ │ │
│  │  │  │  │ L0  Meta-core  (skill-factory, eval-harness,  │ │ │ │ │
│  │  │  │  │     lib, Tier-0 validator) — builds the rest   │ │ │ │ │
│  │  │  │  └──────────────────────────────────────────────┘ │ │ │ │
│  │  │  └──────────────────────────────────────────────────┘ │ │ │
│  │  └──────────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

| Layer | Responsibility | Status |
| --- | --- | --- |
| L0 Meta-core | `skill-factory`, eval-harness, `lib/`, Tier-0 validator. Builds everything else. | **Built** |
| L1 Engine | Subagent roles + native patterns (router, fan-out/fan-in, review loop, Ralph, worktree, file handoff). | **Built (minimal)** — roles + handoff + review-loop/worktree/handoff patterns; fan-out & Ralph deferred. |
| L2 Workflow skills | One router skill per domain; depth via references and sub-skills. | Planned |
| L3 Knowledge base | Obsidian-format vault the plugin deploys, maintains, and reads for context. | Planned |
| L4 Guardrails | Hooks for security, the test/eval gate, logging, subagent budgets. | Planned |

## Component taxonomy

Claude Code merged custom commands into skills, so the unit set is deliberately small:

- **Skill** — the primary unit; expresses a workflow or reusable knowledge. Auto-loads by
  description. Lives in `plugin/skills/<name>/`.
- **Subagent** — an isolated execution role (own tools/model). Skills delegate to it; users
  don't call it. Lives in `plugin/agents/<name>.md`.
- **Hook** — deterministic event enforcement (Python). Guardrails, not logic.
- **Script** — deterministic, unit-tested Python. Shared code in `plugin/lib/`,
  skill-specific in `skills/<name>/scripts/`.
- **Pattern reference** — an on-demand Markdown guide to an engine pattern (review loop,
  worktree, handoff) that workflow skills link to. Lives in `plugin/patterns/`.
- **Knowledge note** — Obsidian markdown in the target repo's vault.
- **Eval contract** — `evals/evals.json` per component; the readiness source of truth.

Skill-centric means skills are the spine; everything else is something a skill uses.

## Native patterns we rely on

These are Claude Code capabilities we use directly rather than reimplement. Ones not yet
built are marked **(deferred)** — designed-for but not part of the current engine:

- **Progressive disclosure** — name+description in the listing; body on activation;
  references on demand. The basis of router discipline.
- **Router** — a small set of always-on entry skills with sharp descriptions; depth pushed
  into `references/` (loaded on demand, so it never sits in the listing). Required because the
  skill listing has a context budget (~1% of the model window) and overflow drops
  descriptions. (`user-invocable: false` only hides a skill from the user's `/` menu — its
  description still counts against the budget; `disable-model-invocation: true` removes a
  skill from the listing.)
- **Forked skills / subagents** — `context: fork` + `agent` runs a skill in isolation; the
  `Task` tool spawns subagents for fan-out/fan-in.
- **Fan-out / fan-in** — partition work into independent units, run one subagent each in
  parallel, then synthesize one result (the backbone of Stage 2 phase-workflows;
  `patterns/fan-out-fan-in.md`, specialised by `patterns/multi-aspect-review.md`).
- **Review loop** — writer → reviewer → revise, always with an iteration budget and a
  "converged-enough" criterion.
- **Adversarial fan-out review** — decompose a review into lenses, fan out independent
  reviewers, verify each finding against the source, then synthesize one report (the
  `deep-review` skill / `patterns/adversarial-review.md`).
- **Ralph loop (deferred)** — a bounded, self-restarting agent loop for long autonomous
  tasks (the agent re-runs itself until a stop condition is met).
- **Git worktree isolation** — parallel work on isolated checkouts.
- **File-based handoff** — phase A writes a contract artifact (PRD, ADR, plan) that phase B
  reads. Auditable and decoupled; the backbone of the SDLC spine.
- **Scheduling** — not native to Claude Code; delegated to CI / headless `claude -p` runs.

## The eval pyramid (cross-cutting)

Quality is enforced the same way at every layer:

- **Tier 0 — static** (always blocks, no LLM): standard validation, frontmatter lint, body
  length, reference resolution, `pytest`, `ruff`, `mypy`, script coverage ≥ 80%.
- **Tier 1 — trigger**: should-trigger recall ≥ 0.9, should-not-trigger specificity ≥ 0.9.
- **Tier 2 — quality** (LLM judge, N ≥ 5): pass-rate lower bound (mean − σ) ≥ 0.8, within
  token/time overhead budgets, not worse than the previous version. For subagent **roles**,
  only the lower-bound pass-rate applies — there is no with/without baseline, trigger surface,
  or overhead delta to compare (see [ADR 0011](decisions/0011-agent-eval-runner.md)).
- **Tier 3 — E2E**: workflow scenarios with checkpoints (added with L2).

See [meta-core.md](meta-core.md) for how the harness implements this, and
[../../plugin/eval/README.md](../../plugin/eval/README.md) for the engine split.

## Key constraints

- Claude Code only; no application code; no deployable artifact.
- All persisted content in English; `SKILL.md` bodies ≤ 500 lines.
- Relative runtime paths and `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}` only.
- One source of truth per component: behavior in `SKILL.md`, readiness in `evals/evals.json`.
