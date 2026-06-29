# 0040 — Capture review-loop non-convergence via an artifact scan

Status: Accepted — **implemented** (diagnostics increment 2; see the [Unreleased] CHANGELOG entry).

## Context

[ADR 0039](0039-diagnostics-channel.md) shipped the diagnostics channel (increment 1: guardrail +
pipeline emitters) and **deferred** capturing **review-loop non-convergence**. Unlike the
increment-1 emitters — which sit at deterministic code boundaries (hooks / CLIs that *know* in code
when a denial / crash / gate-FAIL happened) — the bounded review loop runs **inside the model's
flow** per skill-body instructions. No Python owns the iteration counter, so nothing deterministic
observes "hit N iterations without an `approve`".

The user chose **approach (a): a deterministic scan of the `review.md` handoff artifacts.** This
works because the loop already records its state: [`review-loop.md`](../../../plugin/patterns/review-loop.md)
specifies that a budget-exhausted loop **persists a final `review.md` with verdict `changes`**, and
the `review` handoff schema requires `iteration` + `verdict`. So the terminal state of a
non-converged loop is already on disk.

## Decision

1. **A deterministic scanner over `review.md` artifacts.** `diagnostics.scan_reviews(repo)` walks
   `docs/sdlc/**/review.md`, loads each via `handoff.load_artifact(expected_type="review")`
   (skipping malformed / non-review files — never raises), and produces a diagnostics **anomaly**
   for each loop that exhausted its budget without converging: `verdict == "changes"` at
   `iteration >= cap` (default `3`, the canonical review-loop bound). The pass/fail decision is the
   **pure** `review_anomaly(header, *, cap, ts)`; `scan_reviews` is the thin I/O walk. No model
   reliance — it reads the artifacts the loop already writes.

2. **Why `iteration >= cap`.** A `review.md` with verdict `changes` at `iteration < cap` is a loop
   still **in progress** (it will revise) — not an anomaly. Only at/over the cap is the budget
   exhausted with no `approve`: the "did not converge" signal (review-loop.md: *"Budget exhausted
   (still `changes` after N) → persist the final `review.md` (verdict `changes`) → surface + stop"*).

3. **Wired into the existing diagnostics channel as a scheduled job.** A `review-scan` job (daily)
   runs the scan and records its anomalies to `.agentic-forge/diagnostics.jsonl` — gated by
   `AGENTIC_FORGE_DIAGNOSTICS` like all of increment 1 — and the existing `diagnostics-digest` rolls
   them into "top problems". Recurring non-convergence on the same `target` groups by signature (the
   volatile iteration number is normalised out).

## Alternatives considered

- **Skill-body instruction to emit on exhaustion (approach b):** rejected — model-dependent (the
  model might skip the step) and it couples skill bodies to a diagnostics CLI; the artifact scan is
  deterministic and reads what already exists.
- **A `Stop` / `SubagentStop` hook:** rejected — those events don't carry "the review loop didn't
  converge" semantics; the `review.md` `verdict` / `iteration` do.
- **Fold the scan into `diagnostics-digest`:** rejected — the scan *produces* events and the digest
  *consumes* them; separate jobs preserve that split (and let the scan run without re-emitting the
  whole digest).

## Consequences

- Review-loop non-convergence (in `develop`, `architecture`'s optional review, and the
  `product` / `marketing` / `ux-design` skeptic passes of [ADR 0037](0037-review-passes-for-artifact-writers.md))
  is captured as a diagnostics anomaly when the daily `review-scan` runs with diagnostics enabled —
  closing the increment-2 item ADR 0039 deferred.
- Pure decision + thin I/O seam (the channel's pattern); off by default; never raises (malformed
  artifacts are skipped).
- `review.md` is overwritten per iteration, so the scan sees the **final** state only — sufficient
  for non-convergence, which is a terminal state. Still deferred: opt-in **outward routing** of the
  digest (ADR 0039).
