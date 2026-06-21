# Stage 2 — SDLC spine (design)

Status: Designed (pre-implementation), workflow model. Decisions in
[ADR 0013](decisions/0013-spine-workflow-chain.md) (which supersedes the earlier "thin router"
ADR 0012). Builds on the Stage 1 engine ([engine.md](engine.md)), the handoff contract
([patterns/handoff.md](../../plugin/patterns/handoff.md)), and reuses ideas from the ancestor
`ai-skills` repo as **reference** (we build fresh to our gate, not port).

## Core idea: a chain of workflows

Each SDLC phase is **itself a workflow** — a multi-stage procedure that gathers inputs, plans,
**fans out subagents** across directions/components, synthesizes their results, and analyses
to a conclusion. The spine is a **chain of these workflows** joined only by committed handoff
artifacts in `docs/sdlc/<feature-slug>/`; it is deliberately **not** one mega-workflow (each
phase runs, lands an artifact, and the next phase consumes it). Consequence vs Stage 1:
**fan-out/fan-in is now a core, built pattern** (no longer deferred).

## Strategy: build fresh, `ai-skills` as reference

The ancestor `ai-skills` (26 agents, 77 skills, by-stack packs) already proves this shape
across runtimes. We **build fresh** to the agentic-forge gate (agentskills.io, evals.json
superset, ≤500-line bodies, Tier-0/1/2/3, Claude-only) and consult the ancestor for structure
and content. Reference map per phase below.

## The phases

| # | Skill | Workflow does (stages) | Fans out over | Reads → Writes | ai-skills ref |
| --- | --- | --- | --- | --- | --- |
| 1 | `research` | gather inputs → plan parallel tracks → fan-out → synthesize → analyse/recommend | research directions (market, product, eng, …) | request → `research-brief.md` | `analyze`, `spike` |
| 2 | `product` | digest research → assess current product → plan → user stories → define changes → PRD by template | product areas / user-story sets | `research-brief.md` → `prd.md` | `feature-design`, `product-manager` |
| 3 | `architecture` | digest PRD → study system → weigh options → component design → ADRs → risks | design decisions / subsystems | `prd.md` → `tech-design.md` + `adr-*.md` | `architecture*`, `system/solution-architect` |
| 4 | `plan` | digest design → decompose tasks → dependency order → checkpoints → deferred | work streams | `tech-design.md` → `plan.md` | `plan` |
| 5 | `develop` | pick plan step → git infra (worktree) → **fan-out impl by component** → **multi-aspect review fan-out** (code / security / integration+API / lint) → loop-back on failure → **QA** (existing + new unit + e2e) | components/services, then review aspects | `plan.md` (+`tech-design`) → code in worktree | `develop`, `feature-dev`, `team-*`, `qa`, `worktree-isolation` |
| 6 | `code-review` | scope the diff → fan-out reviewers by code aspect → verify → synthesize verdict → `review.md` | code review aspects | diff (+`plan.md`) → `review.md` | `code-review`, `security-audit` |

Artifact shapes are the canonical contract in
[patterns/handoff.md](../../plugin/patterns/handoff.md); not restated here.

## Specialist agent roster (expanded)

The fan-out by component and by review-aspect needs **specialist executors**, so Stage 2
expands the role set beyond the Stage-1 four (this supersedes ADR 0009's "no new roles", which
was Stage-1-scoped — see ADR 0013). Roles are added **only as a phase that ships needs them**,
each gated like any agent (`component.type: agent`, Tier-2). Planned roster (adapted from
`ai-skills`, re-gated): stack engineers (`software-engineer` + `python-engineer`, later
`frontend-/db-/data-/ml-/mobile-/java-engineer`), architects (`system-/solution-/cloud-architect`),
and quality roles (`security-engineer`, `qa-engineer`, `sre-engineer`, `devops-engineer`). The
existing `architect`/`implementer`/`reviewer`/`grader` stay as the generic base; specialists
are the fan-out targets.

## How a phase-workflow is implemented

A shippable plugin can't depend on the harness Workflow tool, so a phase-workflow is a
**skill whose `SKILL.md` encodes the multi-stage fan-out procedure**, executed with the native
subagent mechanism (`context: fork` + `agent`, the `Task` tool) — model-driven orchestration,
the pattern agentic-forge already uses. **Deterministic glue** (stack detection, plan parsing,
artifact-header validation, synthesis scaffolding) lives in `plugin/lib/agentic_forge/` and is
unit-tested. New pattern references: **fan-out/fan-in** and **multi-aspect review**; reused:
worktree, review-loop, handoff, adversarial-review.

## Multi-language (by-stack) — after the thin slice

The thin slice proves the workflow model on **Python**. Then we bring the ancestor's by-stack
mechanism: a **stack-detection** helper + **stack reference packs** (test runners, release
tools, lint/format, cloud/telemetry) that `develop`/`code-review`/(later) `release` load on
demand for the detected stack. Designed now (the workflows take a "stack profile" input);
implemented for non-Python stacks as a follow-on step.

## Trigger taxonomy

Six always-on skills must route sharply. Each owns one phase by the **artifact it produces**
(what-exists / what-&-why / how / order / make / correct). Each skill's `should_not_trigger`
set is seeded from its **neighbours'** `should_trigger` prompts, so Tier-1 **specificity**
directly measures non-overlap. The `code-review` phase routes only on SDLC-flow phrasing
("review the change from develop / record review.md for this feature"); standalone audits and
non-code review stay with `deep-review`.

## Eval model

- **Each workflow skill:** Tier-1 (trigger recall/specificity ≥ 0.9) + Tier-2 (output quality
  lower bound ≥ 0.8) on fixtures.
- **Each new specialist role:** Tier-2 via the agent eval runner.
- **The spine:** Tier-3 E2E on a **fixture target-repo** (Python), one feature through the
  phases in an isolated copy/worktree, with per-phase checkpoints (artifact exists + validates;
  PRD goals trace to design; plan covers design; develop's code passes the repo's tests;
  code-review returns a verdict).

## Thin slice first

Build order (your choice): **`architecture → develop → code-review`** as workflows, on the
Python fixture repo. `develop` is the flagship (git infra → impl fan-out → multi-aspect review
fan-out → QA) and exercises the riskiest machinery. Minimum new roles for the slice:
`software-engineer`/`python-engineer` (impl fan-out) and `security-engineer`/`qa-engineer`
(review + QA), atop the existing four. Prove the slice end to end, record Tier-1/2/3, then add
`research`, `product`, `plan`, and the by-stack mechanism.

## Exit criteria

- Six workflow skills: Tier-1 ≥ 0.9 recall/specificity, Tier-2 ≥ 0.8 lower bound.
- New specialist roles each pass Tier-2.
- Fan-out/fan-in + multi-aspect-review patterns documented and used.
- Tier-3 E2E green on the fixture repo with all phase checkpoints.
- Tier-0 green throughout; docs + CHANGELOG updated per change.

## Implementation tasks (after approval)

1. Patterns: `fan-out-fan-in.md`, `multi-aspect-review.md`. Fixture Python target-repo.
2. Thin-slice roles (evals-first): `software-engineer`/`python-engineer`, `security-engineer`,
   `qa-engineer`.
3. Thin-slice workflows (evals-first): `architecture`, `develop`, `code-review`.
4. Tier-3 scenario runner for the slice; prove end to end; record numbers.
5. Complete spine: `research`, `product`, `plan`; extend the scenario to all phases.
6. By-stack mechanism + non-Python stacks.

## Defaults to confirm or override

- Names: `research, product, architecture, plan, develop, code-review` (the last kept as a
  compound, code-specific, to avoid the `review`/`deep-review` collision).
- Phase-workflows are model-driven fan-out (SKILL.md procedure + `lib/` glue), not the harness
  Workflow tool.
- Thin slice `architecture → develop → code-review` on a Python fixture repo; by-stack later.
