# 0061 — The bounded skeptic loop + external reviewer reach `research` and `ux-design`

Status: Accepted — **implemented**. Completes [0060](0060-skeptic-loop-architecture-plan.md) (which
deferred these two) and [0037](0037-review-passes-for-artifact-writers.md); extends
[0042](0042-external-reviewer.md)'s `KINDS` and [0057](0057-external-reviewer-on-by-default.md)'s
on-by-default wiring. The `KINDS` invariant below ("one kind per handoff artifact") is **refined by
[0062](0062-skeptic-loop-marketing.md)** to *one kind per review-criteria set*, for a router phase
whose several deliverables share one failure mode.

## Context

ADR 0060 brought `architecture` and `plan` up to the `product` / `develop` reference shape and
deferred the last two artifact-writing phases. Closing that deferral surfaced a sharper version of
the original finding:

- **ADR 0037's audit missed *two* writers, not one.** It bucketed the 14 workflows into
  artifact-writers (`product`, `marketing`, `ux-design` — given a skeptic pass), reviewer-side phases
  (`code-review`, `security-review`), and ops/deterministic phases (`release`, `deploy-watch`,
  `incident-response`), and concluded the loop "now reaches every workflow that writes a reviewable
  artifact". `plan` (ADR 0060) and **`research`** both write reviewable artifacts and appear in none
  of those buckets. `research` is the *first* phase of the spine, so an unsupported claim in
  `research-brief.md` propagates through the PRD, the design, the plan, and the code.
- **`research` had no independent review at all.** Its step 4 ("Synthesize & verify") is the
  author's *own* verification — exactly the blind spot `adversarial-review.md` exists to cover.
- **`ux-design` had the pass but not the contract.** ADR 0037 gave it a real two-lens adversarial
  review, but with no exit criterion (no `review_loop_decision`), no external lens, and no mention in
  its Output — so, as with `architecture` before 0060, "done" did not depend on the review's outcome.
- **Neither could run its own library calls.** Like `product` (ADR 0060 §4), both skills' bodies call
  `handoff.validate_header(...)` while their `allowed-tools` had no `Bash`.

One thing did *not* carry over from 0060: `external_review.KINDS` had a ready criteria entry for a
plan and a technical design, but **none for a research brief or a UX spec** — and an unknown kind
falls back to the **code** criteria ("correctness, bugs, security, integration/API breaks"), which is
actively wrong for both. Wiring the lens with an existing kind would have shipped a reviewer
critiquing a UX spec as if it were a diff.

## Decision

1. **Two new `KINDS` entries** in the ADR 0042 seam, so each phase's external lens is criticised on
   its own failure modes:
   - `research` — every load-bearing claim cited, no unsourced assertion, source disagreements
     reconciled rather than averaged, and a recommendation that follows from the findings.
   - `ux` — every screen covering empty / loading / error / success, no dead-end flow, and concrete
     accessibility requirements (keyboard and focus order, contrast, ARIA/semantics, labels).

   `dev/external_review.py`'s `--kind` choices derive from `sorted(KINDS)`, so both are available
   from the CLI with no change there. The invariant is now **one kind per handoff artifact**, tested:
   the kind set is asserted exactly, and every kind's criteria must be **distinct** (a copy-pasted
   duplicate would review two artifacts on one artifact's failure modes, the same class of defect as
   the code-criteria fallback).

2. **`research` gains a mandatory bounded skeptic pass** (new step 7), modelled on `product`'s: a
   fresh `reviewer` forked via `Task` attacks the brief on citation support, invented figures,
   reconciled disagreements, and whether the recommendation follows from the findings — explicitly
   *independent of* step 4's self-verification.

3. **`ux-design`'s existing pass gains the contract:** the two lenses (plus the external one)
   aggregate to a single verdict, and the loop exits on
   `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<the ux-spec validates>)`,
   with `escalate` surfacing the gaps instead of handing off. The lenses themselves are unchanged —
   ADR 0037 chose them correctly.

4. **The external lens in both, on by default** (`external_reviewer.enabled`), folding into the same
   worst-first revision. The ADR 0042/0057 posture carries over verbatim: strict
   `{verdict, findings[]}` prompt, `exec --sandbox read-only`, graceful skip when `codex` is absent,
   findings advisory and verified before acting.

5. **`Bash` added to both skills' `allowed-tools`**, which is what makes their `handoff` /
   `external_review` calls executable at all (ADR 0060 §4's finding, applied to the last two phases).

6. **`ux-design` step 6 now names the artifact's location** (`ux-spec.md` under
   `docs/sdlc/<feature-slug>/`) — it was the only phase skill that specified the frontmatter but not
   the path, while `patterns/handoff.md` and the Tier-3 checkpoints already assume it.

7. **No eval-contract changes**, per ADR 0037 §5 / [ADR 0020](0020-tier2-inspection-gradeable-assertions.md):
   both skills' existing assertions already gate the outcomes the pass improves (cited sources, a
   recommendation, per-screen states, concrete a11y requirements). Only `component.purpose` is
   updated. **No `description` changes** — Tier-1 routing and the listing budget are untouched.

## Alternatives considered

- **Reuse an existing kind (`product` for the ux-spec, `technical` for the brief):** rejected — the
  `product` criteria ask for testable acceptance criteria and measurable metrics, which a UX spec does
  not have; the point of per-kind criteria is that the lens hunts *that artifact's* failure modes.
- **Let both fall through to the default kind:** rejected outright — the fallback is the **code**
  criteria, so the lens would look for bugs and API breaks in a research brief. (The fallback stays
  as-is for genuinely unknown kinds: it is a fail-safe for a caller typo, not a wiring strategy.)
- **Leave `ux-design` alone since it already has a pass (ADR 0037's position):** rejected — a review
  whose outcome doesn't gate the handoff is advice, not a gate; that is the same gap ADR 0060 closed
  in `architecture`.
- **Give `research` only the external lens (its step 4 already verifies):** rejected — self-verification
  is what the adversarial pattern exists to correct, and on a machine without `codex` the phase would
  again have no independent review.
- **Fold this into ADR 0060 rather than a new ADR:** rejected — 0060's context was the `architecture` /
  `plan` review; the `research` gap and the missing `KINDS` are new findings that deserve their own
  record. 0060's deferred-alternative bullet now points here.

## Consequences

- **All six artifact-writing phases** — `research`, `product`, `architecture`, `plan`, `ux-design`,
  `develop` — now share one shape: draft → bounded skeptic / multi-aspect review (internal roster +
  the external lens when enabled) → `review_loop_decision` → `proceed` hands off, `escalate` stops.
  The workflows still without a loop are the reviewer-side phases (`code-review`, `security-review` —
  by design), `marketing` (an adversarial claims pass without the shared exit criterion — the
  remaining asymmetry, **since closed by [0062](0062-skeptic-loop-marketing.md)**), and the
  ops/deterministic phases.
- `KINDS` now covers every handoff artifact a phase can hand to the external lens; adding a phase
  means adding its kind, and the test enforces that the set is exact and the criteria distinct.
- Each of the two phases costs one extra reviewer fork (plus one `codex` call where installed) in the
  converging case; where `codex` is installed and `enabled` is left true, brief / spec text is now
  also sent to a third party — the ADR 0057 trust boundary and its opt-out
  (`external_reviewer.enabled: false` on secret-bearing repos) apply unchanged.
- Tier-0 green; Tier-1 unaffected (no description changes). The Tier-3 spine and domain scenarios
  assert the artifacts, which the loop can only improve.
- **Measured (2026-07-25):** `ux-design` Tier-2 PASS (mean 1.000, σ 0.000, lower bound 1.000, n = 5);
  `research` and the other spine phases Tier-1 1.000 / 1.000. The consolidated table for the whole
  sweep lives in [ADR 0062](0062-skeptic-loop-marketing.md#measured-outcome--the-sweeps-live-gate-2026-07-25).
