# 0022 — Stage 5: marketing as one evidence-first router skill (product already covered)

Status: Accepted

## Context

Stage 5 is "product & marketing" (roadmap). The product half is already shipped — the `product`
spine skill (Stage 2) turns research into a PRD with success metrics — so the net-new work is the
**marketing** domain. Marketing is broad (market, competitors, strategy, content, social, paid),
subjective, and prone to confident low-signal output (the roadmap's stated risk). Design in
[product-marketing.md](../product-marketing.md); eval rule per [ADR 0020](0020-tier2-inspection-gradeable-assertions.md).

## Decision

- **No new product skill.** The existing `product` already does research-synthesis → PRD with
  metrics. Deeper product analytics, if ever wanted, extends `product`; it is not a new component.
- **Marketing is ONE on-listing `marketing` router skill** that dispatches to sub-procedures in
  `references/` (market-research / strategy / content) and forks the `research` / `Explore` roles
  for evidence. Rationale: CLAUDE.md router discipline — the always-on listing has a hard budget,
  and marketing is rarely used relative to the SDLC core, so one sharp entry + depth in references
  beats several rarely-used on-listing skills. (Revisit if a sub-area grows enough to merit its own
  entry — the same way the spine has per-phase skills.)
- **Evidence-first is the quality lever.** A subjective domain is only gateable if the assertions
  are objective. So the rubric is **claims verification**, expressed as inspection-gradeable
  assertions: every market-size / competitor / performance claim cites a source or is labelled an
  assumption; no fabricated figures; competitors are named specifically; content makes no
  unsupported superlatives. The read-only grader checks these by reading — deterministic, not
  taste. This both makes the gate real and directly mitigates the low-signal-content risk.
- **New handoff types** `market-brief` (segments, named competitors, sizing, cited sources) and
  `marketing-strategy` (positioning, channels, messaging, metrics). Content is files, not a type.
- **Eval tier: Tier-1 + Tier-2.** Marketing's value is its *synthesis + evidence discipline*
  (own behavior), not just the forked research role's output, so it earns skill Tier-2
  (fixture-backed, inspection-gradeable) on top of Tier-1 routing — unlike the pure
  fork-orchestrators of Stage 4 (qa-test-strategy / security-review), which are Tier-1-only.

## Alternatives considered

- **Three separate on-listing marketing skills** (market-research / strategy / content) — rejected
  for router discipline; one router + `references/` keeps the listing lean for a rarely-used domain.
- **A new `product` skill** — rejected; the existing `product` already covers research → PRD +
  metrics.
- **Reuse the old repo's marketing/PM skills** — not applicable in this repo (nothing to reuse
  here); designed fresh to the current gate. Specific old-repo skills can be mirrored later if
  provided.
- **No skill Tier-2 for marketing** (treat it like a fork-orchestrator) — rejected; the evidence
  discipline is marketing's own contribution and is exactly what must be gated.

## Consequences

- One `marketing` skill (+ three references) and two handoff schemas; the listing grows by one.
- A deterministic, claims-verification Tier-2 over a subjective domain; the same evidence rule is
  reusable for future content/marketing components.
- Real provider/search connectors for live market research are the `research` / `Explore` roles'
  job behind the existing seam; nothing live is required for the gate (fixtures provide evidence).

## Exit criteria

- `marketing`: Tier-0 green; Tier-1 recall/specificity ≥ 0.9; Tier-2 lower bound ≥ 0.8 (n ≥ 5)
  with claims-verification assertions.
- `market-brief` / `marketing-strategy` schemas + tests; Tier-0.
- Docs: this ADR, product-marketing.md, roadmap / overview, CHANGELOG.
