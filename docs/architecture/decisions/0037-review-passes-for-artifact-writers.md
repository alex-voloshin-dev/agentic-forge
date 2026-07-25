# 0037 — Review/skeptic passes for artifact-writer workflows; loop-reference symmetry; deploy-watch scope honesty

Status: Accepted — **implemented** (see the [Unreleased] CHANGELOG entry). §5's deferred
verification — "the way to confirm the lift is a live Tier-2 re-run" — was **carried out on
2026-07-25** for the skills whose loops were later contracted by [0061](0061-skeptic-loop-research-ux.md)
/ [0062](0062-skeptic-loop-marketing.md): both PASS, table in
[0062](0062-skeptic-loop-marketing.md#measured-outcome--the-sweeps-live-gate-2026-07-25).

## Context

A loop-integration audit (bounded review loop + Ralph loop) across the 14 SDLC workflow skills,
each finding verified against source, concluded:

- The **bounded review loop** is correctly integrated where it is load-bearing: `develop` (full —
  the [multi-aspect-review](../../../plugin/patterns/multi-aspect-review.md) gate + `N = 3`
  [review-loop](../../../plugin/patterns/review-loop.md) + QA re-entry under the same budget),
  `architecture` (an optional bounded loop for a non-trivial design), and the **reviewer-side**
  phases `code-review` / `security-review`, which are review *producers* (they emit a `review`
  artifact for a consuming loop), not writers.
- Three **artifact-writer** workflows produce a reviewable deliverable but had **no review/skeptic
  step**: `product` (a PRD), `marketing` (claims + content), `ux-design` (a ux-spec).
- **Ralph loops** are correctly absent everywhere — deferred engine-wide ("would run natively, not
  reimplemented"; roadmap out-of-scope). No skill mentions or implements one.
- Two doc-honesty gaps: `security-review` produces the artifact a bounded loop consumes but did not
  link the pattern; `deploy-watch` is named "watch" but is a single-pass snapshot, not a
  continuous poll.

## Decision

1. **Add a bounded adversarial skeptic pass to the three artifact-writer workflows.** Each forks a
   fresh `reviewer` (via `Task`) to attack its own draft against that artifact's specific failure
   modes, then revises. The loop is **bounded and exits on approve** (per
   [review-loop.md](../../../plugin/patterns/review-loop.md)); because a spec/doc artifact converges
   fast, the early-exit keeps it cheap (typically one pass) — no separate, smaller `N` is
   introduced. The method linked is
   [adversarial-review.md](../../../plugin/patterns/adversarial-review.md) (correct for *non-code*
   artifacts), bounded by review-loop. Per skill:
   - `product` — every acceptance criterion **testable**, every metric **measurable**, **non-goals
     complete**, requirements **traceable to the brief**.
   - `marketing` — every claim **cited or marked an assumption**, **no invented figures**,
     competitors named specifically, **no unsupported superlatives**. This upgrades its prior
     self-check ("Verify claims") into a forked adversarial pass — its self-declared "fluff"
     failure mode is exactly what an independent skeptic catches.
   - `ux-design` — two lenses: **accessibility** (keyboard/focus, contrast, ARIA) and **flow/state
     completeness** (every screen has empty/loading/error/success; no dead-end).

2. **`product` and `ux-design` gain `Task` in `allowed-tools`** — they lacked it, so could not fork
   a reviewer. `marketing` already had it. **Descriptions are unchanged**, so Tier-1 routing is
   unaffected (and need not be re-verified by a cost-gated run).

3. **`security-review` links `review-loop.md`** in its Output, for symmetry with `code-review`:
   both emit a `review` artifact (`verdict` / `iteration`) that the consuming `develop` workflow
   drives through its bounded loop. No workflow change — it stays the critique side.

4. **`deploy-watch` states its scope honestly** in the body: a **point-in-time snapshot** (one
   assessment pass), not a continuous watch — re-run to re-check; continuous
   poll-until-terminal-state is out of scope for now. That continuous-watch shape is the natural
   future home of a bounded **Ralph** poll-loop once Ralph is un-deferred — recorded here, not in
   the user-facing body (which avoids internal-pattern jargon). The description ("watch a rollout")
   is left unchanged (Tier-1-routing-sensitive).

5. **No eval-contract changes.** The three writers' existing Tier-2 assertions (and `product`'s
   Tier-3 spine checkpoint) already gate the *outcomes* the skeptic pass improves — cited claims,
   complete per-screen states, testable acceptance. Asserting "a review pass ran" would be
   process-grading that the read-only grader cannot verify from the artifact (ADR 0020). The
   skeptic pass is an implementation improvement under the existing contract; the way to confirm the
   lift is a live Tier-2 re-run, ideally the new `--baseline` A/B from
   [ADR 0036](0036-tier2-ab-overhead-wiring.md).

## Alternatives considered

- **Make the passes mandatory at `N = 3` like `develop`:** rejected — over-burdens a simple PRD or
  spec. The early-exit-on-approve bound is proportional; a doc converges in ~1 pass.
- **Use `multi-aspect-review.md` for `ux-design`:** rejected — that pattern is code-specific ("for
  non-code targets use adversarial-review.md"); a ux-spec is non-code, so the adversarial lens
  fan-out is the right pattern.
- **Add process assertions ("a review pass ran") to the evals:** rejected — ungradeable from the
  artifact by the read-only grader; the outcome assertions already gate the quality (ADR 0020).
- **Rename `deploy-watch` / change its description to "snapshot":** rejected — the description is
  Tier-1-routing-sensitive and "watch a rollout" is a real trigger phrase; clarify the body only.
- **Implement a Ralph loop for `deploy-watch` now:** rejected — Ralph stays deferred engine-wide;
  `deploy-watch` is only recorded as its future home.

## Consequences

- The bounded review loop now reaches every workflow that **writes a reviewable artifact**. The
  only workflows still without it are the reviewer-side phases (`code-review`, `security-review` —
  by design) and the deterministic/ops phases (`release`, `deploy-watch`, `incident-response`)
  where a human gate or determinism substitutes.
- `product` and `ux-design` can now fork subagents (`Task`); their Tier-2 / Tier-3 numbers should
  be re-recorded on the next live run (the additive skeptic pass must not lower pass-rate and aims
  to raise it — measurable with the `--baseline` A/B).
- Tier-0 stays green; Tier-1 is untouched (no description changes). The audit's verdict is captured
  in this ADR + the CHANGELOG.
