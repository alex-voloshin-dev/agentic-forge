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
| 5 | `develop` | pick plan step → git infra (worktree) → **implement the step's components (sequential, one worktree in v1)** → **multi-aspect review fan-out** (code / security / integration+API / lint) → loop-back on failure → **QA** (existing + new unit + e2e) | review aspects (impl parallelism deferred) | `plan.md` (+`tech-design`) → code in worktree | `develop`, `feature-dev`, `qa`, `worktree-isolation` |
| 6 | `code-review` | scope the diff → fan-out reviewers by code aspect → verify → synthesize verdict → `review.md` | code review aspects | diff (+`plan.md`) → `review.md` | `code-review`, `security-audit` |

Artifact shapes are the canonical contract in
[patterns/handoff.md](../../plugin/patterns/handoff.md); not restated here.

## Specialist agent roster (expanded)

Stage 2 expands the role set beyond the Stage-1 four (this supersedes ADR 0009's "no new
roles", which was Stage-1-scoped — see ADR 0013). Per
[ADR 0014](decisions/0014-software-engineer-base-role.md): `implementer` is renamed to
**`software-engineer`** (the base engineering role), and **stack specialization lives in
skills, not per-stack agents** — `software-engineer` loads the lean `engineering-standards`
skill plus the relevant stack skill (the by-stack step) by context. New **quality
specialists** are real agents, added only as a shipping phase needs them and gated
(`component.type: agent`, Tier-2): `security-engineer` and `qa-engineer` now; others (e.g.
`sre-`/`devops-engineer`) later. Current roster: base `software-engineer`; design `architect`;
quality `reviewer`, `grader`, `security-engineer`, `qa-engineer`.

## How a phase-workflow is implemented

A shippable plugin can't depend on the harness Workflow tool, so a phase-workflow is a
**skill whose `SKILL.md` encodes the multi-stage fan-out procedure**, executed with the native
subagent mechanism (`context: fork` + `agent`, the `Task` tool) — model-driven orchestration,
the pattern agentic-forge already uses. **Deterministic glue** (stack detection, plan parsing,
artifact-header validation, synthesis scaffolding) lives in `plugin/lib/agentic_forge/` and is
unit-tested. New pattern references: **fan-out/fan-in** and **multi-aspect review**; reused:
worktree, review-loop, handoff, adversarial-review.

## Multi-language (by-stack)

The thin slice proved the workflow model on **Python**; by-stack makes the spine
stack-parametric. Mechanism (see [ADR 0015](decisions/0015-by-stack-detection-and-packs.md)):

- **Deterministic detection** — `lib/agentic_forge/stacks.py` `detect(repo)` returns ranked
  `StackProfile`s from an explicit `stack:` hint (CLAUDE.md / AGENTS.md) or manifest signatures
  (`pyproject.toml` → python, `tsconfig.json` → typescript (suppressing a co-present bare
  `package.json`), bare `package.json` → javascript,
  `go.mod` → go, `Cargo.toml` → rust, …). Detection is a tested fact, not an LLM guess.
- **Stack profile input** — each profile carries `stack_id`, `display`, the `pack`
  (`*-patterns` skill name or `None`), and a `toolchain` (`test`/`lint`/`typecheck`/`format`
  commands). Profile commands are **conventional fallbacks**; the repo's declared commands
  (CLAUDE.md / Makefile / scripts) win.
- **Stack reference packs** — off-listing (`disable-model-invocation: true`) `*-patterns`
  knowledge skills (toolchain, idioms, testing, layout, pitfalls), modelled on
  `engineering-standards`, loaded on demand by `develop` / `code-review` and the
  `software-engineer` / `qa-engineer` roles for the detected stack.

**Status:** detection ships for the common stacks; **`python-patterns`, `typescript-patterns`,
`go-patterns`, and `rust-patterns` ship**. A detected stack with no pack falls back to
`engineering-standards` + the profile's toolchain defaults (logged, not silent). Further packs
(jvm, dotnet, …) ship one at a time.

## Trigger taxonomy

Six always-on skills must route sharply. Each owns one phase by the **artifact it produces**
(what-exists / what-&-why / how / order / make / correct). Each skill's `should_not_trigger`
set is seeded from its **neighbours'** `should_trigger` prompts, so Tier-1 **specificity**
directly measures non-overlap. The `code-review` phase routes only on SDLC-flow phrasing
("review the change from develop / record review.md for this feature"); standalone audits and
non-code review stay with `deep-review`.

## Eval model

- **Each workflow skill:** Tier-1 (trigger recall/specificity ≥ 0.9, via majority-of-N router
  sampling). A skill that delegates to gated roles inherits its **quality** from those roles'
  Tier-2 (≥ 0.8) rather than re-running a separate Tier-2; the end-to-end quality is the Tier-3
  scenario. A skill with substantial own logic still ships a `tier2_quality` gate.
- **Each new specialist role:** Tier-2 via the agent eval runner.
- **The spine:** Tier-3 E2E on a **fixture target-repo** (Python), one feature through the
  phases in an isolated copy/worktree, with per-phase checkpoints (artifact exists + validates;
  PRD goals trace to design; plan covers design; develop's code passes the repo's tests;
  code-review returns a verdict).

## Thin slice first

Build order (your choice): **`architecture → develop → code-review`** as workflows, on the
Python fixture repo. `develop` is the flagship (git infra → implement the step in a single
worktree → multi-aspect review fan-out → QA) and exercises the riskiest machinery. Minimum new
roles for the slice: `security-engineer` and `qa-engineer` (review + QA); implementation uses
the renamed `software-engineer` (was `implementer`). Stack engineers stay deferred to the
by-stack step. Prove the slice end to end, record Tier-1/2/3, then add
`research`, `product`, `plan`, and the by-stack mechanism.

## Exit criteria

- Six workflow skills: Tier-1 ≥ 0.9 recall/specificity; quality via the delegated roles'
  Tier-2 (≥ 0.8) and the Tier-3 scenario.
- New specialist roles each pass Tier-2.
- Fan-out/fan-in + multi-aspect-review patterns documented and used.
- Tier-3 E2E green on the fixture repo with all phase checkpoints.
- Tier-0 green throughout; docs + CHANGELOG updated per change.

## Implementation tasks

1. ~~Patterns: `fan-out-fan-in.md`, `multi-aspect-review.md`. Fixture Python target-repo.~~ Done.
2. ~~Thin-slice roles (evals-first): `software-engineer`, `security-engineer`, `qa-engineer`.~~
   Done (stack engineers deferred to by-stack — ADR 0014).
3. ~~Thin-slice workflows (evals-first): `architecture`, `develop`, `code-review`.~~ Done.
4. ~~Tier-3 scenario runner for the slice; prove end to end.~~ Done (Tier-3 PASS).
5. ~~Complete spine: `research`, `product`, `plan`.~~ Done — all six phase skills built + gated.
6. ~~Extend the Tier-3 scenario to all six phases.~~ Done — full six-phase E2E proven.
7. **Next:** the by-stack mechanism + non-Python stacks; a real Tier-1 runner on live
   skill descriptions (current Tier-1 is a majority-of-N router sim).

## Defaults to confirm or override

- Names: `research, product, architecture, plan, develop, code-review` (the last kept as a
  compound, code-specific, to avoid the `review`/`deep-review` collision).
- Phase-workflows are model-driven fan-out (SKILL.md procedure + `lib/` glue), not the harness
  Workflow tool.
- Thin slice `architecture → develop → code-review` on a Python fixture repo; by-stack later.
