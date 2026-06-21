---
name: research
description: Investigate a feature or idea before it is specified or designed — gather inputs, fan out parallel research tracks (e.g. prior art / product / engineering), synthesize, and produce a research-brief.md with cited sources and a recommendation. Use when asked to research, investigate, explore or compare options/approaches, survey prior art, or recommend a direction BEFORE speccing or designing. This is the SDLC research phase (feeds product); for a standalone deep report not tied to the feature flow use deep-research. Not for defining requirements (product), the technical design itself (architecture), or implementing (develop).
allowed-tools: Read, Grep, Glob, Task, Write
---

# Research (phase workflow)

The first phase of the SDLC spine: turn an open question into a grounded research brief the
`product` phase consumes. It is a [fan-out/fan-in](../../patterns/fan-out-fan-in.md) workflow —
plan tracks, research each independently, synthesize — delegating the actual digging to
existing capabilities rather than doing it inline.

## When to use

Before a feature is specified, when the question is *what exists / what are the options*: prior
art, market/competitors, user needs, technical feasibility. Not for deciding requirements
(`product`), designing (`architecture`), or building (`develop`).

## Process

1. **Scope & gather.** State the question; collect what's already on hand (the request, repo,
   any existing docs). Pick a `<feature-slug>`.
2. **Plan tracks.** Choose the research directions that apply — e.g. prior art / market,
   product / users, engineering / feasibility. Only the ones that matter.
3. **Fan out** one researcher per track (see fan-out/fan-in), delegating:
   - **codebase / internal** → the built-in `Explore` agent;
   - **external / web** → the `deep-research` skill (multi-source, verified, cited).
   Each returns structured findings with sources.
4. **Synthesize & verify.** Merge the tracks into one picture; reconcile disagreements; verify
   the load-bearing claims against their sources (drop unsupported ones).
5. **Analyse → recommend.** Draw conclusions and a recommendation for the `product` phase.
6. **Write the brief.** Emit `research-brief.md` (frontmatter `type, feature, status, date,
   sources[]`; body = findings, conclusions, recommendations) under `docs/sdlc/<feature-slug>/`;
   validate it (`handoff.validate_header(..., expected_type="research-brief")`).

## Output

A `research-brief.md` handoff (see [patterns/handoff.md](../../patterns/handoff.md)): synthesized
findings, cited sources, and recommendations — the input to `product`.

## Definition of done

- `research-brief.md` validates against the research-brief handoff schema (sources listed).
- Findings are synthesized across the tracks (not concatenated) and load-bearing claims are
  cited.
- The brief ends with clear conclusions + a recommendation for the next phase.
