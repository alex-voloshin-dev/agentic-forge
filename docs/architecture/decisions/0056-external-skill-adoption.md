# 0056 — Adopt external skill-library content as references (marketing execution depth)

Status: Accepted — implemented (see the [Unreleased] CHANGELOG entry).

## Context

The maintainer's personal skill library (22 skills, exported from claude.ai) was reviewed for
adoption. It splits into: (a) the maintainer's own field-tested marketing/growth skills
(`geo-audit`, `social-media-manager`, `seo-review`, `faq-schema-builder`, `grand-slam-offer`) —
deep execution knowledge our thin `marketing` references (22–25 lines each) lack; (b) a previous
generation of workflow skills (`marketing`, `qa`, `product-manager`, `ui-ux-design`) superseded by
this plugin's architecture but holding useful checklists/templates; (c) Anthropic document skills
(`docx`/`pdf`/`pptx`/`xlsx` — **proprietary, "All rights reserved"**) and Apache-2.0 design skills
(`theme-factory`, `canvas-design`, `brand-guidelines`); (d) personal/niche skills
(`linkedin-profile`, `ai-expert`, `session-start-hook`).

Constraints: the router listing is at its ~1% budget ceiling (CLAUDE.md), so new on-listing skills
need a budget review; the plugin is MIT-licensed, so proprietary content cannot be vendored; the
eval pyramid (ADR 0017) assigns Tier-2 to self-contained skills (`marketing`, `ux-design`,
`deep-review`) while spine/fork-orchestrator skills (`product`, `qa-test-strategy`) carry Tier-1
only.

## Decision

1. **References-first, no new on-listing skills.** All adopted content lands in `references/`
   under existing skills (loaded on demand — zero listing cost). Two listing descriptions change,
   both Tier-1-gated live: `marketing` gains the offer/pricing + content-audit keywords, and
   `product` gains the matching boundary clause ("not market/competitor analysis and offer/pricing
   design — marketing") — extending one description diluted its neighbour's routing until the
   boundary was stated on both sides (lesson recorded in the eval runbook).
2. **What is adopted, where:**
   - `marketing/references/geo-content.md` ← `geo-audit` + `seo-review` + `faq-schema-builder`:
     the 0–100 GEO rubric, the 10-point pre-publish checklist, anti-patterns, FAQPage JSON-LD
     essentials, and the technical-SEO audit pass — **generalized** (brand-specific canonical
     terms become "the product's canonical terms"; old `Agent(seo-engineer)`/`/feature-dev`
     wiring becomes this plugin's roles).
   - `marketing/references/offer-design.md` ← `grand-slam-offer`: the offer/pricing/packaging
     procedure (value equation, trim & stack, risk reversal, authenticity guardrail), with the
     method attributed to its source (Hormozi's *$100M Offers*).
   - `marketing/references/content.md` **extended** ← `social-media-manager`: zero-click strategy,
     personal-over-company, per-platform limits, and the anti-AI-writing patterns as a quality
     gate; plus the durable-artifact convention (`marketing/MARKETING.md`, `content-calendar.md`)
     from the predecessor marketing workflow, so strategy/publication state persists between
     sessions.
   - `product/references/prioritization.md` ← `product-manager`: framework selection table
     (RICE / ICE / MoSCoW / JTBD / Kano), metric frameworks (North Star, AARRR, AI-product
     metrics), Now/Next/Later roadmap shape.
   - `ux-design/references/design-handoff.md` ← `ui-ux-design`: the design-to-code handoff
     template (tokens / variants / states / ARIA), token-naming table, 5-minute accessibility
     quick-audit.
   - `qa-test-strategy/references/bug-reports.md` ← `qa`: structured bug-report format and the
     exploratory-testing pass — two genres the strategy skill did not cover.
   - `deep-review/references/lenses.md` gains a **reader-testing** lens (from Anthropic's
     `doc-coauthoring` Stage 3 — the technique, not the text): simulate the target reader and
     verify the doc answers their actual questions.
3. **Not adopted:** the proprietary document skills (license + scope), the Apache design skills
   (scope: artifact styling, not SDLC), `linkedin-profile`/`ai-expert`/`session-start-hook`
   (personal/niche; `ai-expert` duplicates host surfaces), Anthropic's `skill-creator`
   (`skill-factory` is stricter — evals-first with hard gates).
4. **Eval plan (contract-first):** `marketing` gains should-trigger phrases (offer/pricing,
   content audit) and three Tier-2 cases with fixtures (a GEO audit over a defective HTML fixture,
   an offer-design brief, a social post gated by the anti-AI patterns); `ux-design` gains a
   handoff-spec Tier-2 case. `product`'s changed description re-ran Tier-1 live;
   `qa-test-strategy`'s description is untouched → its Tier-1 contract is unchanged (ADR 0017
   keeps both skills' quality with the delegated roles). Changed contracts run live before
   shipping.

## Alternatives considered

- **New skills per capability (`geo-audit`, `offer`, …):** rejected — the listing is at its
  budget ceiling, the capabilities are sub-procedures of one marketing domain, and off-listing
  manual skills would hide them from natural routing ("audit this page for AI search").
- **Vendor the document/design skills for completeness:** rejected — proprietary license (docx et
  al.) and out-of-scope surface (styling); users already get them from Anthropic directly.
- **Adopt the old workflow skills wholesale:** rejected — they encode a superseded architecture
  (`Agent(...)` roles, `/feature-dev` chains, `context: fork`); only their checklists carry over.

## Consequences

- `marketing` becomes execution-capable (audit, offer, social) rather than research/strategy-only,
  at the cost of a few listing tokens — Tier-1 re-run guards the routing.
- Adopted content is the maintainer's own or attributed method summaries; no licensing exposure.
- The source library stays where it is; this ADR records provenance so future bundles/audits can
  trace where the rubrics came from.
