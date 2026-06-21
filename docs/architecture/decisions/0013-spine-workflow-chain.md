# 0013 — Stage 2 SDLC spine as a chain of phase-workflows

Status: Accepted (design). Supersedes [ADR 0012](0012-sdlc-spine.md).

## Context

ADR 0012 framed Stage 2 as six *thin router skills* that each delegate to a single Stage-1
role. On review, that under-models the work: each SDLC phase is really a **workflow** — gather
inputs, plan, fan out subagents across directions/components, synthesize, analyse — e.g.
`research` parallelises tracks (market/product/eng) then synthesises; `develop` builds a
worktree, fans out implementation by component, fans out review by aspect (code / security /
integration+API / lint), loops back on failure, then runs QA. The ancestor `ai-skills` repo
(26 agents, 77 skills, `team-*` fan-out, by-stack packs) demonstrates this shape. This ADR
revises the Stage-2 architecture accordingly. See [spine.md](../spine.md).

## Decision

- **Spine = a chain of phase-workflows** joined only by handoff artifacts — not one
  mega-workflow, not thin single-role routers. **Fan-out/fan-in becomes a core, built pattern**
  in Stage 2 (it was deferred in Stage 1).
- **Six workflow skills:** `research`, `product`, `architecture`, `plan`, `develop`,
  `code-review` (one-word names; `code-review` kept as a code-specific compound to avoid the
  `review`/`deep-review` collision — `deep-review` handles non-code and standalone audits).
- **Build fresh, `ai-skills` as reference.** Conform every component to the agentic-forge gate;
  use the ancestor for structure/content, not as a drop-in port.
- **Expanded specialist agent roster.** Fan-out by component/aspect needs specialist executors
  (stack engineers, architects, security/qa/sre/devops). Added only as a shipping phase needs
  them, each gated (`component.type: agent`, Tier-2). **This supersedes ADR 0009's "no new
  roles," which was Stage-1-scoped.**
- **Phase-workflows are model-driven fan-out:** the `SKILL.md` encodes the multi-stage
  procedure executed via `context: fork`/`Task`; deterministic glue lives in `lib/`. The
  plugin does not depend on the harness Workflow tool.
- **Multi-language (by-stack) after the thin slice.** Prove the model on Python first; then add
  stack-detection + stack reference packs adapted from `ai-skills`.
- **Thin slice first:** `architecture → develop → code-review` as workflows on a Python fixture
  repo; Tier-3 E2E with per-phase checkpoints.

## Alternatives considered

- **Thin router skills (ADR 0012):** superseded — too shallow for phases that genuinely
  fan out and synthesize.
- **Port `ai-skills` as-is / adapt-and-re-gate:** rejected in favour of building fresh — the
  ancestor is vendor-agnostic and ungated; fresh build guarantees gate-conformance from day one
  while still mining the ancestor for content.
- **Keep the four generic roles only, parametrise by stack:** rejected — weakens discipline-
  and aspect-specific fan-out; the specialist roster matches the workflow vision.
- **One mega-workflow for the whole spine:** rejected — phases must checkpoint to durable
  artifacts and be independently runnable/resumable.
- **Harness Workflow tool to orchestrate phases:** rejected for the shipped plugin (not a
  plugin primitive); it remains available for *our* dev-time orchestration.

## Consequences

- New core patterns to document: fan-out/fan-in and multi-aspect review.
- The agent roster grows (each addition gated); ADR 0009's role cap no longer applies to
  Stage 2+.
- `develop` is the only code-writing skill; it isolates via worktree and runs internal review
  + QA before phase 6.
- New test assets: a Python fixture target-repo and a Tier-3 spine scenario runner.
- Multi-language is explicitly staged after the thin slice; workflows take a "stack profile"
  input so the later by-stack work is additive.
