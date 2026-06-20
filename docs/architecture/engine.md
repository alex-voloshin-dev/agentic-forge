# Stage 1 — Engine foundations (design)

Status: Designed (pre-implementation). This document is the worked-through design for
Stage 1; implementation follows only after review.

## Decisions

- **Dedicated roles:** `reviewer`, `grader`, `implementer`, `architect`. Research uses the
  built-in `Explore` agent; planning uses the built-in `Plan` agent; generic delegation
  uses `general-purpose`.
- **Handoff format:** Markdown + YAML frontmatter, committed to the target repo so it is
  human-readable, Obsidian-linkable, and machine-parseable on the key fields.
- **Review loop:** bounded — at most `N` iterations (default `N = 3`), stop early when the
  reviewer returns `approve`.
- **Agent eval:** the skill-creator subagent-run loop plus our gate (`component.type:
  agent`).

These are recorded in [ADR 0009](decisions/0009-engine-roles-and-handoff.md).

## Subagent roles

Each role is a single Markdown file under `plugin/agents/<name>.md`. Skills delegate to
them via `context: fork` + `agent: <name>` or the `Task` tool; users never call them.

| Role | Purpose | Tools (narrowed) | Returns |
| --- | --- | --- | --- |
| `reviewer` | Critique a diff or a design artifact in isolation | `Read, Grep, Glob, Bash(git diff:*)` | Verdict `approve`/`changes` + findings (severity, location, suggested fix) |
| `grader` | Grade eval assertions impartially against outputs | `Read, Grep, Glob` | `grading.json` (`text`/`passed`/`evidence` + summary); never edits the work |
| `implementer` | Write code in an isolated worktree | `Read, Write, Edit, Bash, Grep, Glob` | Summary of changes, files touched, tests added |
| `architect` | Produce technical design from requirements | `Read, Grep, Glob, Write` (docs only) | ADR(s) + component design artifact |

Why these and not more: `reviewer` and `grader` are needed almost everywhere (review loop,
self-review, Tier-2 grading) and benefit from a clean context. `implementer` needs a full
write toolset and worktree isolation. `architect` benefits from a design-focused prompt.
Researcher/planner are well covered by `Explore`/`Plan`, so we do not duplicate them.

## Handoff artifact model

Phases communicate by writing artifacts the next phase reads — auditable and decoupled.

- **Location:** `docs/sdlc/<feature-slug>/` in the target repo (committed; links into the
  knowledge base in Stage 3). Default; overridable per project.
- **Shape:** Markdown body (for humans and Claude) with a YAML frontmatter header carrying
  the fields the next phase parses.

| Artifact | Produced by | Frontmatter (key fields) |
| --- | --- | --- |
| `research-brief.md` | `research-brief` (Explore) | `type, feature, date, status, sources[]` |
| `prd.md` | `product-spec` | `type, feature, status, goals[], non_goals[], metrics[], acceptance[]` |
| `tech-design.md` + `adr-*.md` | `tech-design` (architect) | `type, feature, status, decisions[], components[], risks[]` |
| `plan.md` | `work-plan` (Plan) | `type, feature, status, tasks[] (id, deps), checkpoints[], deferred[]` |
| `review.md` | `code-review` (reviewer) | `type, target, iteration, verdict, findings[]` |

A shared helper (`plugin/lib/agentic_forge/handoff.py`, added at implementation) will load
and validate these headers against small per-type schemas, reusing `frontmatter.py`.

## Patterns delivered

- **File-based handoff** — the artifacts above; each phase reads predecessor frontmatter
  for structured fields and the body for detail.
- **Bounded review loop** — writer (skill or role) → `reviewer` → revise, capped at `N = 3`,
  exiting on `approve`. The orchestrating workflow skill owns the loop and the budget.
- **Worktree isolation** — `implementer` runs against a git worktree created by the
  `develop` workflow, so parallel/iterative work does not touch the main checkout.

Deferred to later stages: fan-out/fan-in research at scale, Ralph loops.

## Agent evaluation

Each role ships an eval contract at `plugin/agents/evals/<name>.evals.json` (the superset
schema with `component.type: agent`). Fixtures define representative tasks and assertions;
runs use the skill-creator subagent loop; `benchmark.summarize` aggregates and
`gate.tier2_quality` decides. Thresholds start at `min_pass_rate 0.8`, `runs 5`.

The Tier-0 validator **already** requires an eval contract for every agent at
`plugin/agents/evals/<name>.evals.json` with `component.type: agent` (implemented during the
documentation review), so agents are gated like skills from the start.

## Exit criteria

- All four roles defined with narrowed tools and explicit return contracts.
- Each role meets Tier-2 (lower bound ≥ 0.8 over ≥ 5 runs) on its fixture set.
- `handoff.py` + per-type header schemas implemented and unit-tested.
- Validator requires agent eval contracts (done during review); Tier-0 green.
- Patterns documented as references usable by Stage 2 skills.

## Implementation tasks (next, after review)

1. Author the four role files + agent eval contracts (via `skill-factory`).
2. Add `lib/agentic_forge/handoff.py` + artifact header schemas + pytest.
3. ~~Extend the validator to require agent eval contracts.~~ Done during the review.
4. Write pattern references (review loop, worktree, handoff) for Stage 2 to consume.

## Defaults to confirm or override

- Artifact directory: `docs/sdlc/<feature-slug>/`.
- Review-loop cap: `N = 3`.
- Agent eval location: `plugin/agents/evals/`.
