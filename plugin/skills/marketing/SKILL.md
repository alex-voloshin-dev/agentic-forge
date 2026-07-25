---
name: marketing
description: Market and competitor research and analysis, go-to-market strategy and positioning, offer / pricing / packaging design, marketing content (landing copy, social, ad/paid), and GEO/SEO content audits — the outward-facing marketing domain, with cited evidence. Use for market research or a competitor analysis of the market landscape, GTM / positioning / channel strategy, designing or pricing an offer, writing landing / social / ad copy, or auditing a page for AI search readiness / citability / SEO. Not for product requirements or a PRD (product), researching the feature or technical options (research), or the technical design (architecture).
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

Market or competitor research, go-to-market / positioning / channel strategy, offer / pricing /
packaging design, marketing content (landing copy, social, ad/paid), or a GEO/SEO audit of a page
for AI search readiness. **Not** for the product spec / PRD (`product`), researching the
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
| Offer / pricing / packaging design | [references/offer-design.md](references/offer-design.md) | offer doc |
| Landing copy, social, ad / paid content | [references/content.md](references/content.md) | content files |
| GEO / SEO audit of a page or content | [references/geo-content.md](references/geo-content.md) | audit report |

## Process

1. **Identify the sub-area** from the request and read its reference for the procedure + rubric.
2. **Gather evidence.** Use provided research/notes if present; otherwise gather it **live with
   `WebSearch` / `WebFetch`** (analyst reports, competitor sites, pricing pages) — or fork the
   `research` / `Explore` roles via `Task` for deeper tracks — **keeping every source URL**. Then
   apply the evidence discipline above (cite or mark every claim; no fabrication).
3. **Synthesize** the sub-area's output: the handoff artifact — `market-brief` (frontmatter `type`, `feature`, `status`, `competitors`, `segments`, `sources`) or `marketing-strategy` (`type`, `feature`, `status`, `positioning`, `channels`) — validated via
   `handoff.validate_header(header, expected_type="market-brief")` or `"marketing-strategy"`
   (see [handoff.md](../../patterns/handoff.md)); or the untyped deliverables per the reference —
   content files, the offer doc, or the audit report — grounded in the evidence and the upstream
   `prd.md` where relevant.
4. **Adversarial claims pass (bounded).** Fork a fresh `reviewer`/skeptic (via `Task`) to attack
   the draft against the evidence discipline above — every claim **cited or marked an assumption**,
   **no invented figures**, competitors named specifically, **no unsupported superlatives** — then
   fix what it flags worst-first. This is the guard against the fluff failure mode above.
   **External reviewer lens (on by default, ADR 0057/0062):** when `external_reviewer.enabled`
   (settings), also run the external reviewer over the deliverable — call
   `external_review.review(deliverable_text, "marketing", command=<cfg>)` from
   `${CLAUDE_PLUGIN_ROOT}/lib` (repo-side equivalent: `dev/external_review.py --target <the
   deliverable> --kind marketing`); codex attacks the same evidence discipline as an
   independent-model lens and its `findings` fold into the same worst-first revision. It **degrades
   gracefully** (absent/disabled codex is skipped, not a failure) and its findings are **advisory**
   (prompt-injectable) — verify before acting. **Exit criterion (the shared, tested rule):** each
   round, compute `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<the gate
   below>)` (see [adversarial-review.md](../../patterns/adversarial-review.md), bounded by
   [review-loop.md](../../patterns/review-loop.md)) — `revise` (loop back and fix worst-first),
   `escalate` (still `changes` at N = 3 → surface the unresolved claims and stop; don't ship), or
   `proceed` (`approve` **and** the gate → the deliverable is done). **The gate depends on what this
   sub-area produced:** for a typed handoff (`market-brief` / `marketing-strategy`) it is step 3's
   `handoff.validate_header`; for the untyped deliverables (offer doc, content files, audit report)
   there is no schema, so it is the evidence discipline itself — every claim cited or labelled, no
   bare figure stated as fact. Don't ship a deliverable whose claims aren't sourced.

## Output

**A full marketing run produces the finished deliverable for the sub-area** — a validated
`market-brief` or `marketing-strategy` handoff (see [handoff.md](../../patterns/handoff.md)), or the
untyped offer doc / content files / audit report — with every claim cited or labelled, that survived
the bounded claims loop to `proceed`. A run whose loop `escalate`s (unsourced claims still standing
at N = 3) surfaces them and stops; it does **not** ship fluff.

## Definition of done

- The claims loop exited on `proceed` (`review_loop_decision`): `approve` **and** the sub-area's
  gate (schema validation, or the evidence discipline for an untyped deliverable) — not `escalate`.
- The right sub-area procedure was followed; the output is the expected handoff/content.
- Every market/competitor claim is cited or labelled an assumption; nothing is fabricated;
  competitors are named specifically.
- A bounded adversarial claims pass (plus the external-reviewer lens when enabled) checked the
  evidence discipline before shipping.
- Strategy ties to the market brief and the PRD; content traces to real proof points and the brand tone.
