---
name: marketing
description: Market and competitor research and analysis, go-to-market strategy and positioning, and marketing content (landing copy, social, ad/paid) — the outward-facing marketing domain, all with cited evidence. Use for market research or a competitor analysis, go-to-market / positioning / channel strategy, or writing landing-page copy, social posts, or ad / paid copy. Not for product requirements or a PRD (product), researching the product feature or technical options (research), or the technical design (architecture).
allowed-tools: Read, Grep, Glob, Bash, Task, Write, Edit, WebSearch, WebFetch
---

# Marketing (domain router)

The marketing domain: turn a product into market understanding, a go-to-market strategy, and
on-brand content. This is one router skill — it dispatches to the sub-procedure in `references/`
for the task at hand, and forks the research / `Explore` roles to gather evidence. The product
requirements themselves are the `product` skill's job; this is everything outward-facing.
(Design: [ADR 0022](../../../docs/architecture/decisions/0022-stage5-marketing-domain.md),
[product-marketing.md](../../../docs/architecture/product-marketing.md).)

## When to use

Market or competitor research, go-to-market / positioning / channel strategy, or marketing content
(landing copy, social, ad/paid). **Not** for the product spec / PRD (`product`), researching the
feature or technical options (`research`), or the technical design (`architecture`).

## Evidence discipline (non-negotiable)

The failure mode of generated marketing is confident, low-signal fluff. So every output obeys:

- **Cite or mark.** Every market-size, competitor, or performance claim cites a source, or is
  explicitly labelled an assumption. Never state a bare figure as fact.
- **No fabrication.** If the evidence has no number (e.g. no reliable TAM), say so — do not invent
  one. Name *specific* competitors, never "various players".
- **No unsupported superlatives** in content — claims trace to real proof points.

## Pick the sub-area

| Task | Reference | Output |
| --- | --- | --- |
| Market sizing, segments, competitor landscape | [references/market-research.md](references/market-research.md) | `market-brief` |
| Positioning, GTM, channels, messaging | [references/strategy.md](references/strategy.md) | `marketing-strategy` |
| Landing copy, social, ad / paid content | [references/content.md](references/content.md) | content files |

## Process

1. **Identify the sub-area** from the request and read its reference for the procedure + rubric.
2. **Gather evidence.** Use provided research/notes if present; otherwise gather it **live with
   `WebSearch` / `WebFetch`** (analyst reports, competitor sites, pricing pages) — or fork the
   `research` / `Explore` roles via `Task` for deeper tracks — **keeping every source URL**. Then
   apply the evidence discipline above (cite or mark every claim; no fabrication).
3. **Synthesize** the handoff artifact — `market-brief` (frontmatter `type`, `feature`, `status`, `competitors`, `segments`, `sources`) or `marketing-strategy` (`type`, `feature`, `status`, `positioning`, `channels`) — or
   the content files, grounded in the evidence and the upstream `prd.md` where relevant. Validate the
   chosen header (`handoff.validate_header(header, expected_type="market-brief")` or
   `"marketing-strategy"`; see [handoff.md](../../patterns/handoff.md)).
4. **Adversarial claims pass (bounded).** Fork a fresh `reviewer`/skeptic (via `Task`) to attack
   the draft against the evidence discipline above — every claim **cited or marked an assumption**,
   **no invented figures**, competitors named specifically, **no unsupported superlatives** — then
   fix what it flags. Bounded, exits on approve (see
   [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)). This is the guard against the fluff failure
   mode above.

## Definition of done

- The right sub-area procedure was followed; the output is the expected handoff/content.
- Every market/competitor claim is cited or labelled an assumption; nothing is fabricated;
  competitors are named specifically.
- Strategy ties to the market brief and the PRD; content traces to real proof points and the brand tone.
