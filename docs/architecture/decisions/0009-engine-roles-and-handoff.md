# 0009 — Engine roles, markdown handoff, bounded review loop

Status: Accepted — the agent-eval decision below is narrowed by
[ADR 0011](0011-agent-eval-runner.md): agents use a dedicated runner, not skill-creator
(which also aligns this with ADR 0005's "small harnesses for agents/scripts").

## Context

Stage 1 needs the minimal execution machinery for the SDLC vertical slice: which subagent
roles to build, how phases hand work to each other, when the review loop stops, and how
agents are evaluated.

## Decision

- Build dedicated roles `reviewer`, `grader`, `implementer`, `architect`. Reuse built-in
  `Explore` (research) and `Plan` (planning); use `general-purpose` for generic delegation.
- Phase handoff uses Markdown + YAML frontmatter artifacts committed to the target repo at
  `docs/sdlc/<feature-slug>/`.
- The review loop is bounded at `N = 3` iterations, exiting early on a `reviewer` `approve`.
- Agents are evaluated with the skill-creator subagent-run loop plus our gate
  (`component.type: agent`), thresholds starting at `min_pass_rate 0.8`, `runs 5`.
  _(Narrowed by [ADR 0011](0011-agent-eval-runner.md): agents use a dedicated runner, not
  skill-creator.)_

## Alternatives considered

- **Full per-phase role set** (researcher/architect/planner/implementer/reviewer/grader):
  rejected — Explore/Plan already cover research/planning; fewer roles to build and gate.
- **JSON or pure-markdown handoff:** rejected — frontmatter+markdown gives both
  human/Obsidian readability and reliable structured fields (see ADR 0006 rationale style).
- **Quality-threshold review convergence:** viable but costlier (grade every iteration);
  deferred in favor of the simpler approve-signal loop.
- **Dedicated agent-eval harness:** rejected — reuse the skill-creator engine (ADR 0005).
  _(Reversed by [ADR 0011](0011-agent-eval-runner.md): skill-creator is skill-shaped, so
  agents got a thin dedicated runner — which is what ADR 0005 itself anticipated.)_

## Consequences

- Small, justified role set; researcher/planner stay as built-ins.
- Handoff artifacts double as project documentation and knowledge-base seeds (Stage 3).
- The Tier-0 validator must be extended to require agent eval contracts.
- A `handoff.py` helper and per-type header schemas are added at implementation time.
