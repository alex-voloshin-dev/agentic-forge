# 0012 — Stage 2 SDLC spine: six thin router skills

Status: Superseded by [ADR 0013](0013-spine-workflow-chain.md) (the spine is a chain of
phase-**workflows**, not thin single-role routers; fan-out/fan-in becomes core, the agent
roster expands, and we build fresh using `ai-skills` as reference). Retained for history;
the phase set, handoff-only communication, trigger taxonomy, fork/inline split, and
thin-slice-first decisions carry forward into 0013.

## Context

Stage 2 builds the vertical slice from idea to reviewed code on top of the Stage 1 engine. The
roadmap left five questions open: phase boundaries/artifacts, router-vs-sub-skill split,
fork-vs-inline, the trigger taxonomy, and the E2E scenario. The handoff contract (ADR 0010)
and roles (ADR 0009) already fix the artifacts and delegation targets; this ADR fixes the
skill set, routing, and build approach. See [spine.md](../spine.md).

## Decision

- **Six thin router skills**, one per phase: `research-brief`, `product-spec`, `tech-design`,
  `work-plan`, `develop`, `code-review`. Each delegates to a Stage 1 target and communicates
  only via committed handoff artifacts in `docs/sdlc/<feature-slug>/`. No new roles; no
  `user-invocable:false` sub-skills (they don't save listing budget — ADR 0004). Depth lives
  in each skill's `references/`.
- **Trigger taxonomy by owned artifact:** each skill owns one phase/question (what-exists /
  what-&-why / how / order / make / correct). Each skill's `should_not_trigger` set is seeded
  from its neighbours' `should_trigger` prompts, so Tier-1 specificity directly measures
  non-overlap.
- **Fork vs inline:** fork `research-brief`, `tech-design`, `work-plan`, `code-review`; keep
  `product-spec` inline (requirements elicitation is a conversation); `develop` runs in a
  worktree and owns the bounded review loop internally.
- **Phase-6 review delegates.** Because a `code-review` skill already ships in the environment
  and `deep-review` owns thorough audits, the spine's review phase is thin: it routes on
  SDLC-flow phrasing only, runs the review loop, calls `deep-review`/`reviewer` to critique,
  and writes `review.md`.
- **E2E (Tier 3) on a fixture target-repo** in an isolated copy/worktree, carrying one feature
  through all phases with per-phase checkpoints.
- **Thin slice first:** build `tech-design → develop → code-review`, prove it end to end, then
  add the other three.

## Alternatives considered

- **Fewer/merged skills** (e.g. one "design" skill for product+technical): rejected — blurs
  the what/how boundary that the trigger taxonomy depends on.
- **A standalone phase-6 review engine:** rejected — would collide on Tier-1 with the existing
  `code-review` and `deep-review`; delegating reuses a gated skill. *Fallback:* if Tier-1
  specificity still can't separate them, drop the phase-6 skill and let `deep-review` serve
  the phase directly.
- **Build all six at once:** rejected for first delivery — the thin slice de-risks the
  riskiest machinery (worktree + review loop + roles) before breadth.
- **E2E by dogfooding a real agentic-forge feature:** deferred — a fixture target-repo is
  isolated and repeatable, and better matches the plugin's real use (operating on *other*
  repos).

## Consequences

- Six descriptions are the entire Tier-1 surface; they must stay sharp — non-overlap is an
  explicit eval target.
- The spine reuses `deep-review` (Stage-2 addition) for heavy review and the `reviewer` role
  for light review, so phase 6 is orchestration, not a new engine.
- A fixture target-repo and a Tier-3 scenario runner (extending the agent-eval harness) are
  new test assets.
- `develop` is the only skill that writes code; it isolates via worktree and gates internally
  before phase 6.
