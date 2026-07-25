# 0062 — The shared exit criterion + external reviewer reach `marketing`; the `KINDS` invariant refined

Status: Accepted — **implemented**. Completes the sweep started by
[0060](0060-skeptic-loop-architecture-plan.md) / [0061](0061-skeptic-loop-research-ux.md) over the
workflows that write a reviewable deliverable; refines 0061's `KINDS` invariant. Builds on
[0037](0037-review-passes-for-artifact-writers.md) (which gave `marketing` its claims pass),
[0042](0042-external-reviewer.md) (the seam) and [0057](0057-external-reviewer-on-by-default.md).

## Context

After 0060 and 0061, `marketing` was the last workflow writing a reviewable deliverable without the
shared shape. It was **not** an oversight of the ADR 0037 audit — that ADR deliberately gave it a
bounded adversarial claims pass, and the lens it chose (the evidence discipline: cite or mark, no
fabrication, specific competitors, no unsupported superlatives) is the right one. What it lacked was
the *contract* around that pass, exactly as `ux-design` did before 0061:

- **No exit criterion.** "Bounded, exits on approve" was prose; nothing computed
  `review_loop_decision`, so there was no `escalate` discipline — a deliverable whose claims still
  weren't sourced after N rounds had no defined stopping behaviour, and nothing said "don't ship".
- **No external lens**, and no `KINDS` entry to give it one — the same fallback-to-code hazard 0061
  found for a brief and a UX spec.
- **No `Output` section at all** (the only workflow skill without one), so what a full run produces
  — and what happens when it can't — was never stated.

`marketing` also raised the question 0061 didn't have to answer: it is a **router** over five
sub-areas with heterogeneous outputs — two typed handoffs (`market-brief`, `marketing-strategy`) and
three untyped deliverables (offer doc, content files, audit report). Both the `gate_green` and the
"one kind per handoff artifact" invariant needed a defensible answer for that shape.

## Decision

1. **One `marketing` kind, not five.** The five deliverables fail the *same* way — fluff: an
   uncited figure, a fabricated TAM, "various players", an unsupported superlative. So one criteria
   entry covers them.

   This **refines 0061's phrasing** of the invariant: it is **one kind per review-criteria set** —
   the failure modes of what a phase hands off — not one per schema type. A phase whose deliverables
   share a failure mode gets one entry; the test still asserts the kind set exactly and that every
   kind's criteria are **distinct** (a duplicate would review one artifact on another's failure
   modes). The code-criteria fallback for a genuinely unknown kind is unchanged.

2. **A conditional `gate_green`, stated honestly.** The loop uses
   `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=…)` like every other phase,
   where the gate depends on what the sub-area produced:
   - **typed handoff** (`market-brief` / `marketing-strategy`) → step 3's
     `handoff.validate_header` — a real, deterministic second condition, as in the other phases;
   - **untyped deliverable** (offer doc, content, audit report) → there is no schema, so the gate is
     the **evidence discipline** itself (every claim cited or labelled, no bare figure as fact).

   For the untyped half the gate largely collapses onto the reviewer's own verdict, so the loop
   reduces to "exit on `approve`, `escalate` at N = 3". That is weaker than `develop`'s QA gate or
   `plan`'s `plan_batches` — and it is still strictly stronger than the status quo, which had **no**
   escalate discipline and no stated non-ship. Inventing a schema for landing copy to manufacture a
   deterministic gate would be worse than naming the limit.

3. **The external lens, on by default** (`external_reviewer.enabled`), over the same evidence
   discipline, folding into the same worst-first revision. ADR 0042/0057 posture carries over
   verbatim: strict `{verdict, findings[]}` prompt, `exec --sandbox read-only`, graceful skip when
   `codex` is absent, findings advisory and verified before acting.

4. **An `Output` section** stating what a full run produces and that `escalate` (unsourced claims
   still standing at N = 3) surfaces them and **does not ship**.

5. **No eval-contract changes**, per ADR 0037 §5 / [ADR 0020](0020-tier2-inspection-gradeable-assertions.md):
   `marketing`'s Tier-2 already grades claims-verification, the outcome this pass improves. Only
   `component.purpose` is updated. **No `description` change** — Tier-1 routing and the listing
   budget are untouched. `Bash` was already in its `allowed-tools` (unlike the five skills 0060/0061
   had to fix), so nothing was unreachable here.

## Alternatives considered

- **Leave `marketing` as-is (ADR 0037's position):** rejected — a review whose outcome doesn't gate
  shipping is advice, not a gate. That is the same argument 0060 applied to `architecture` and 0061
  to `ux-design`; applying it to two of three and stopping would leave the inconsistency the sweep
  set out to remove.
- **Separate kinds per deliverable (`market-brief`, `strategy`, `content`, …):** rejected — they
  share one failure mode, so the criteria would be near-duplicates, which the distinctness test
  rightly forbids and which buys no review fidelity.
- **Reuse `--kind research` for the market brief:** rejected — the research criteria ask whether the
  recommendation follows from the findings, which is not a market brief's failure mode; and the same
  skill's content/offer outputs would still have no fitting kind.
- **Demand a deterministic `gate_green` for the untyped deliverables (e.g. invent a `content`
  schema):** rejected — a schema over landing copy would be ceremony, not a gate; better to state
  that the untyped half's gate is the discipline and the loop reduces to approve/escalate.
- **Fold this into 0061:** rejected — 0061 is about the two *spine* writer phases and its invariant
  wording predates the router case; the refinement deserves its own record.

## Consequences

- **Every workflow that writes a reviewable deliverable now shares one shape** — draft → bounded
  review (internal roster + the external lens when enabled) → `review_loop_decision` → `proceed`
  ships, `escalate` stops: the six artifact-writing phases from 0060/0061 plus `marketing`. The
  workflows still without a loop are the reviewer-side phases (`code-review`, `security-review` —
  review *producers* by design) and the ops/deterministic ones (`release`, `deploy-watch`,
  `incident-response`), where a human gate or determinism substitutes. ADR 0037's closing claim is
  now actually true.
- `gate_green` is no longer uniformly a schema check across the fleet: `marketing`'s untyped half
  rests on the evidence discipline. Documented here and in `review-loop.md` rather than papered over.
- `KINDS` covers every review-criteria set a phase can hand the external lens; adding a phase means
  adding its kind unless it shares an existing failure-mode set.
- Where `codex` is installed and `enabled` is left true, marketing deliverables are now also sent to
  a third party — the ADR 0057 trust boundary and its opt-out apply unchanged.
- Tier-0 green; Tier-1 unaffected (no description changes); the `market-brief` Tier-3 domain scenario
  asserts the artifact, which the loop can only improve.
