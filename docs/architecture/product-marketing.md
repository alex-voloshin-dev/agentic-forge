# Stage 5 — Product & marketing domains (design)

Stage 5 adds the **marketing** domain. The "product" half of the roadmap stage is already shipped,
so the net-new work is one router skill for marketing, evidence-first to avoid low-signal output.
Built contract-first → evals-first → gate, with inspection-gradeable Tier-2 (ADR 0020). Roadmap:
Stage 5.

## Product — already shipped (reconciliation)

The roadmap's Stage-5 "product (research synthesis, metrics)" is already covered by the existing
`product` spine skill (Stage 2): it processes the research brief, assesses the current product,
writes user stories, and produces `prd.md` with goals / non-goals / **success metrics** /
acceptance criteria. **No new product skill is needed.** If deeper product analytics tooling is
wanted later, it extends `product`; it is not a new component. This stage is therefore *marketing*.

## Marketing — one router skill, depth in references (router discipline)

CLAUDE.md router discipline keeps the always-on set small and pushes depth into `references/`;
marketing is rarely used relative to the SDLC core, so it is **one on-listing `marketing` router
skill** that dispatches to sub-procedures in `references/`, forking the research / `Explore` roles
to gather evidence. It covers the roadmap's six areas:

| Sub-area (reference) | Does | Output |
| --- | --- | --- |
| market-research | market sizing, segments, and the competitor landscape — every claim cited | `market-brief` |
| strategy | positioning / GTM / channels / messaging from the market-brief + the PRD | `marketing-strategy` |
| content | copy / social / blog / paid to the strategy — on-brand, no unsupported claims | content files |

## Evidence-first — the key quality lever

The roadmap's stated risk is **low-signal generated content**. The mitigation is **claims
verification as gradeable assertions** (ADR 0020): every market-size / competitor / performance
claim must cite a source or be explicitly marked an assumption; no fabricated statistics; content
makes no unsupported superlatives. The read-only grader verifies these by reading (are claims
cited? are specific competitors named? does content trace to the strategy?) — deterministic, not
vibes. This is what makes a subjective domain gateable.

## New handoff types (`handoff.py`, contract-first)

- `market-brief` — feature schema + `segments`, `competitors` (named, non-empty), `sources`
  (cited), `sizing`.
- `marketing-strategy` — feature schema + `positioning`, `segments`, `channels`, `messaging`,
  `metrics`.
- Content is delivered as files, not a typed artifact.

## Eval approach (ADR 0020)

- **Tier-1**: `marketing` triggers (market/competitor research, GTM/positioning strategy,
  marketing content / social / paid copy) vs negatives — a product PRD → `product`, the technical
  design → `architecture`, feature research before speccing → `research`.
- **Tier-2** (fixture-backed, inspection-gradeable): a fixture product + market context →
  assert the `market-brief` names specific competitors with **cited** claims and no fabricated
  stats; the strategy ties to the brief + PRD; content matches the strategy's positioning with no
  unsupported superlatives.

## Alternatives considered

- **Three separate on-listing marketing skills** (market-research / strategy / content) —
  rejected for router discipline: marketing is rarely used, so one router + `references/` keeps the
  listing lean. Revisit if a sub-area grows enough to warrant its own entry.
- **Reuse the old repo's marketing/PM skills** — not applicable here (nothing to reuse in this
  repo); designed fresh to the current gate. If specific old-repo skills should be mirrored, they
  need to be provided.
- **A new `product` skill** — rejected; the existing `product` already does research-synthesis →
  PRD with metrics (see reconciliation above).

## Exit criteria

- `marketing` skill: Tier-0 green; Tier-1 recall/specificity ≥ 0.9; Tier-2 lower bound ≥ 0.8
  (n ≥ 5) with claims-verification assertions.
- New `market-brief` / `marketing-strategy` handoff schemas + tests; Tier-0.
- Docs: this design, an ADR, roadmap / overview, CHANGELOG per step.
