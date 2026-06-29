# Stage 1 — Engine foundations

Status: Implemented. This document is the worked-through design for Stage 1; the engine
roles, the handoff helper, and the pattern references described below are now built and
Tier-0 green. Implementation choices made on top of this design are recorded in
[ADR 0010](decisions/0010-handoff-schemas-and-pattern-references.md).

## Decisions

- **Dedicated roles:** `reviewer`, `grader`, `software-engineer`, `architect`. Research uses the
  built-in `Explore` agent; planning uses the built-in `Plan` agent; generic delegation
  uses `general-purpose`. Stage 2 (the SDLC spine) extends this roster with two specialists —
  `security-engineer` and `qa-engineer` — that the phase-workflows fan out to; see
  [spine.md](spine.md).
- **Handoff format:** Markdown + YAML frontmatter, committed to the target repo so it is
  human-readable, Obsidian-linkable, and machine-parseable on the key fields.
- **Review loop:** bounded — at most `N` iterations (default `N = 3`), stop early when the
  reviewer returns `approve`.
- **Agent eval:** a dedicated runner (`agent_eval.py`) over our gate (`component.type:
  agent`) — skill-creator is skill-shaped, so it is not reused for agents. See
  [ADR 0011](decisions/0011-agent-eval-runner.md).

These are recorded in [ADR 0009](decisions/0009-engine-roles-and-handoff.md).

## Subagent roles

Each role is a single Markdown file under `plugin/agents/<name>.md`. Skills delegate to
them via the `Task` tool (named in `allowed-tools`); users never call them.

| Role | Purpose | Tools (narrowed) | Returns |
| --- | --- | --- | --- |
| `reviewer` | Critique a diff or a design artifact in isolation | `Read, Grep, Glob, Bash(git diff:*)` | Verdict `approve`/`changes` + findings (severity, location, suggested fix) |
| `grader` | Grade eval assertions impartially against outputs | `Read, Grep, Glob` | `grading.json` (`text`/`passed`/`evidence` + summary); never edits the work |
| `software-engineer` | Write code in an isolated worktree | `Read, Write, Edit, Bash, Grep, Glob` | Summary of changes, files touched, tests added |
| `architect` | Produce technical design from requirements | `Read, Grep, Glob, Write` (docs only) | ADR(s) + component design artifact |

Why these and not more: `reviewer` and `grader` are needed almost everywhere (review loop,
self-review, Tier-2 grading) and benefit from a clean context. `software-engineer` needs a full
write toolset and worktree isolation. `architect` benefits from a design-focused prompt.
Researcher/planner are well covered by `Explore`/`Plan`, so we do not duplicate them.
`grader` is the one role no workflow skill delegates to — it is invoked only by the eval harness
(`run_agent_evals` / `run_skill_evals`) for Tier-2 grading. Stage 2 adds two more specialists the
phase-workflows fan out to — `security-engineer` (security lens; `Read, Grep, Glob, Bash(git
diff:*)`) and `qa-engineer` (tests; `Read, Write, Edit, Bash, Grep, Glob`); see [spine.md](spine.md)
— for a six-role roster.

## Handoff artifact model

Phases communicate by writing artifacts the next phase reads — auditable and decoupled.

- **Location:** `docs/sdlc/<feature-slug>/` in the target repo (committed; links into the
  knowledge base in Stage 3). Default; overridable per project.
- **Shape:** Markdown body (for humans and Claude) with a YAML frontmatter header carrying
  the fields the next phase parses.

The artifact types, their producers, and key header fields are specified canonically in
[patterns/handoff.md](../../plugin/patterns/handoff.md) (and enforced by the per-type schemas
in `handoff.py`). This document does not restate that table, to avoid drift.

The shared helper `plugin/lib/agentic_forge/handoff.py` loads and validates these headers
against small per-type JSON Schemas, reusing `frontmatter.py`. It exposes `load_artifact` /
`parse_artifact` (raise `HandoffError`), `validate_header` (returns a list of problems), and
`schema_for`, plus the `status`, `verdict`, and `severity` vocabularies. See
[ADR 0010](decisions/0010-handoff-schemas-and-pattern-references.md) for the schema rules.

## Patterns delivered

Each pattern is documented as an on-demand reference under `plugin/patterns/`, so Stage 2
skills link to it rather than restating it:

- **File-based handoff** ([patterns/handoff.md](../../plugin/patterns/handoff.md)) — the
  artifacts above; each phase reads predecessor frontmatter for structured fields and the
  body for detail.
- **Bounded review loop** ([patterns/review-loop.md](../../plugin/patterns/review-loop.md)) —
  writer (skill or role) → `reviewer` → revise, capped at `N = 3`, exiting on `approve`. The
  orchestrating workflow skill owns the loop and the budget.
- **Worktree isolation** ([patterns/worktree.md](../../plugin/patterns/worktree.md)) —
  `software-engineer` runs against a git worktree created by the `develop` workflow, so
  parallel/iterative work does not touch the main checkout.
- **Ralph loop** ([patterns/ralph.md](../../plugin/patterns/ralph.md)) — bounded autonomous
  iteration (ADR 0048): re-run a fresh-context executor against a persistent task until done /
  stalled / the iteration budget. Deterministic core in `lib/ralph.py`; driver in `dev/ralph.py`
  (dry-by-default, never merges/pushes). Compose with worktree + review-loop.

Deferred to later stages: research fan-out at scale (the fan-out/fan-in *pattern* itself shipped in
Stage 2 — see [spine.md](spine.md) and
[patterns/fan-out-fan-in.md](../../plugin/patterns/fan-out-fan-in.md)).

## Agent evaluation

Each role ships an eval contract at `plugin/agents/evals/<name>.evals.json` (the superset
schema with `component.type: agent`). Fixtures live in `plugin/eval/fixtures/<role>/`
(referenced from each case's `files`); runs use the dedicated agent eval runner
(`agentic_forge.agent_eval`, CLI `dev/run_agent_evals.py`), then `benchmark.summarize`
aggregates and `gate.tier2_quality` decides. Thresholds start at `min_pass_rate 0.8`,
`runs 5`. See [ADR 0011](decisions/0011-agent-eval-runner.md) and the
[eval runbook](../eval-runbook.md) — skill-creator stays the engine for skills, while agents
use this runner over the same `benchmark` + `gate` policy layer.

The Tier-0 validator **already** requires an eval contract for every agent at
`plugin/agents/evals/<name>.evals.json` with `component.type: agent` (implemented during the
documentation review), so agents are gated like skills from the start.

## Exit criteria

- All four roles defined with narrowed tools and explicit return contracts.
- Each role meets Tier-2 (lower bound ≥ 0.8 over ≥ 5 runs) on its fixture set.
- `handoff.py` + per-type header schemas implemented and unit-tested.
- Validator requires agent eval contracts (done during review); Tier-0 green.
- Patterns documented as references usable by Stage 2 skills.

## Implementation tasks (done)

1. ~~Author the four role files + agent eval contracts (via `skill-factory`).~~ Done —
   `plugin/agents/{reviewer,grader,software-engineer,architect}.md` with narrowed tools and
   explicit return contracts, each gated by `plugin/agents/evals/<name>.evals.json`
   (`component.type: agent`).
2. ~~Add `lib/agentic_forge/handoff.py` + artifact header schemas + pytest.~~ Done —
   per-type JSON Schemas + helper, unit-tested at 100% (`tests/test_handoff.py`).
3. ~~Extend the validator to require agent eval contracts.~~ Done during the review.
4. ~~Write pattern references (review loop, worktree, handoff) for Stage 2 to consume.~~ Done
   — `plugin/patterns/{handoff,review-loop,worktree}.md`.

Tier-2 quality has been run for the four Stage-1 roles via the agent eval runner on a Claude
subscription (Opus 4.8) — all pass the `min_pass_rate 0.8` / `runs 5` gate (lower bound
≥ 0.885); numbers recorded in the CHANGELOG. The two Stage-2 specialists
(`security-engineer`, `qa-engineer`) are gated the same way — see [spine.md](spine.md).

## Defaults (confirmed)

- Artifact directory: `docs/sdlc/<feature-slug>/`.
- Review-loop cap: `N = 3`.
- Agent eval location: `plugin/agents/evals/`.
