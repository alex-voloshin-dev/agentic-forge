# 0060 — The bounded skeptic loop + external reviewer reach `architecture` and `plan`

Status: Accepted — **implemented**; completed by [0061](0061-skeptic-loop-research-ux.md), which
brings the last two writer phases (`research`, `ux-design`) to the same shape. Extends
[0057](0057-external-reviewer-on-by-default.md) (external
reviewer on by default, wired into `develop` + `product`) and closes a gap left by
[0037](0037-review-passes-for-artifact-writers.md) (review passes for artifact-writer workflows).
Uses the existing seam from [0042](0042-external-reviewer.md) and the settings from
[0041](0041-plugin-settings.md) / [0049](0049-user-level-config.md).

## Context

A review of the spine's four artifact-writing phases against the `product` / `develop` reference
implementation found the middle two out of line:

- **`develop`** (ADR 0057) — multi-aspect review + the external lens (`--kind code`), inside the
  bounded N = 3 loop with `review_loop_decision` as the exit criterion.
- **`product`** (ADR 0037 + 0057) — a mandatory bounded skeptic pass + the external lens
  (`--kind product`), same exit criterion.
- **`architecture`** — a review pass existed but was **"(Optional) … for a non-trivial design"**: no
  exit criterion, no external lens, and nothing in Output / Definition of done, so a run that skipped
  it was still "done".
- **`plan`** — **no review step at all.** ADR 0037's audit classified the 14 workflows into
  artifact-writers (given a skeptic pass), reviewer-side phases, and ops/deterministic phases, and
  concluded the loop "now reaches every workflow that writes a reviewable artifact" — but `plan`
  writes `plan.md`, a reviewable artifact, and appears in none of those buckets. It was simply
  missed.

The gap matters most exactly there: a defect in the design or the build order is the cheapest to fix
at that phase and the most expensive downstream — `develop` materialises it as code across every
dependency level before any reviewer sees it. ADR 0057 deferred "wire it into every review surface",
but the surfaces it named were the *reviewer-side* skills (`code-review`, `deep-review`,
`security-review`), not these two writers.

Two supporting facts made this cheap: `external_review.KINDS` has shipped `plan` and `technical`
criteria since ADR 0042 (unused until now), and `planning.plan_batches` already raises on a duplicate
id / unknown dependency / cycle — a deterministic gate `plan` was not using.

## Decision

1. **A mandatory bounded skeptic pass in both phases**, modelled exactly on `product`'s: fork a fresh
   `reviewer` via `Task`, attack the draft against that artifact's own failure modes, revise
   worst-first. Per phase:
   - `architecture` — each ADR alternative **genuinely weighed** (not a strawman), every PRD goal
     **traced** to a component or decision, every risk carrying a **mitigation**, component
     boundaries / failure modes sound. `deep-review` remains the fan-out option for a large design.
   - `plan` — every design component **covered** by a task, the dependency graph **complete** (no
     missing edge) as well as acyclic, each task **independently shippable** with a **verifiable**
     checkpoint, the deferred list **explicit**.

   "Mandatory" means the pass always runs, not that it always costs N = 3: the loop early-exits on
   `approve`, so a clean design or plan converges in one round (ADR 0037's proportionality argument,
   unchanged).

2. **The external reviewer as an extra lens in both**, on by default via `external_reviewer.enabled`:
   `--kind technical` over `tech-design.md`, `--kind plan` over `plan.md`. Findings fold into the
   same worst-first revision at their own severity. No new machinery — the ADR 0042 seam, the strict
   `{verdict, findings[]}` prompt contract, the read-only sandbox, graceful skip when `codex` is
   absent, and the advisory/prompt-injectable caveat all carry over verbatim from ADR 0057.

3. **One exit criterion, shared and tested.** Both phases compute
   `handoff.review_loop_decision(verdict, iteration, cap=3, gate_green=<the phase's validation step
   passes>)` → `proceed` | `revise` | `escalate`, and **`escalate` does not hand off** — the
   unresolved gaps are surfaced and the run stops. `gate_green` is:
   - `architecture` — `tech-design.md` validates, every PRD goal traces, each ADR records a genuinely
     rejected alternative (its existing step 5);
   - `plan` — `plan.md` validates **and** `planning.plan_batches(tasks)` resolves. This promotes the
     previously prose-only "dependencies form a cycle-free order" into a deterministic, already-tested
     check, run by the same helper `develop` batches with.

4. **`Bash` added to `allowed-tools`** for `architecture`, `plan`, and **`product`**. The skills call
   the shared library (`handoff` / `planning` / `external_review` under `${CLAUDE_PLUGIN_ROOT}/lib`)
   and the repo-side `dev/external_review.py`; `allowed-tools` is a real restriction (the same reason
   ADR 0037 had to add `Task` to `product` / `ux-design` before they could fork a reviewer), so
   without `Bash` the external-reviewer step ADR 0057 specified for `product` **could not run at
   all**. This makes 0057's `product` wiring executable rather than aspirational.

5. **No eval-contract changes.** Per ADR 0037 §5 and [ADR 0020](0020-tier2-inspection-gradeable-assertions.md),
   "a review pass ran" is process-grading a read-only grader cannot verify from the artifact; both
   skills' existing assertions already gate the *outcomes* the pass improves (goal traceability,
   non-strawman alternatives, component coverage, cycle-free order, explicit deferred list). Only the
   `component.purpose` contract line in each `evals.json` is updated to describe the loop. Tier-1 is
   untouched — **no `description` changes**, so routing and the listing budget are unaffected.

## Alternatives considered

- **Leave `architecture`'s pass optional and skip `plan` (status quo):** rejected — an optional gate
  with no exit criterion and no mention in the definition of done is not a gate, and `plan` had none
  at all. These are the two phases whose defects are cheapest to catch and costliest to carry.
- **External lens only, no internal `reviewer`:** rejected — the value of ADR 0042's seam is that it
  is an *additional, different-model* lens; on the common machine without `codex` it degrades to
  nothing, which would leave both phases with no review at all.
- **A smaller budget (N = 1 or 2) for doc phases:** rejected — the loop early-exits on `approve`, so
  the cap only binds when the artifact genuinely keeps failing; one shared `REVIEW_LOOP_BUDGET` keeps
  every orchestrator identical (review-loop.md).
- **Also wire `research` and `ux-design` (the remaining writer phases without the external lens):**
  deferred at the time — `ux-design` already has a bounded two-lens skeptic pass (ADR 0037) and
  `research` has its own synthesis/verification step; both still lacked `Bash` in `allowed-tools`,
  the prerequisite. **Since closed by [ADR 0061](0061-skeptic-loop-research-ux.md)**, which found the
  deferral understated the gap (`research` had *no* independent review, and neither artifact had a
  `KINDS` entry — so the external lens would have fallen back to the code criteria).
- **Wire it into `code-review` / `security-review` / `deep-review`:** still deferred (ADR 0057) —
  those are review *producers* with their own aspect fan-out; `deep-review` documents the lens via
  `adversarial-review.md`.

## Consequences

- All four artifact-writing spine phases (`product`, `architecture`, `plan`, `develop`) now run the
  same shape: draft → bounded skeptic/multi-aspect review (internal roster + the external lens when
  enabled) → `review_loop_decision` → `proceed` hands off, `escalate` stops.
- `plan` gains a real determinism win beyond the review: the DAG is now proved by `plan_batches`
  rather than asserted in prose, at the phase that writes it instead of the phase that consumes it.
- Each phase's run gets slower and more expensive by one reviewer fork (plus one `codex` call where
  installed) in the converging case; where `codex` is installed and `enabled` is left true, the
  design / plan text is now also sent to a third party — the ADR 0057 trust boundary and its
  opt-out (`external_reviewer.enabled: false` on secret-bearing repos) apply unchanged.
- Tier-0 stays green; Tier-1 is unaffected (descriptions unchanged). The Tier-3 spine checkpoints for
  both phases still pass — they assert the artifacts, which the loop can only improve.
