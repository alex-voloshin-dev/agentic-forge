# 0070 — Delivery parity for the document phases: one feature worktree, one PR

Status: Accepted — **implemented**. Extends the worktree discipline of
[0034](0034-develop-parallelism.md) / `worktree.md` to the six document phases, and reuses the PR
machinery of [0063](0063-autonomous-pr-watch.md) / [0067](0067-deep-review-remediation.md) /
[0068](0068-pr-watch-autostart.md).

## Context

Code changes get isolation, review, a PR, monitoring and a gated merge. Document changes — the PRD,
the tech design and its ADRs, the work plan, the research brief, the ux-spec, marketing
deliverables — are written **straight into the user's checkout**. Verified across all six phase
bodies: zero occurrences of worktree, branch, commit or `gh pr create`.

The *review* contract is already identical (ADR 0060–0062: bounded loop, external lens, exit through
`review_loop_decision`). The gap is **isolation and delivery**, and it has a concrete consequence:
when a phase `escalate`s, the rejected artifact is already sitting in the working tree, marked only
by `status: in-review` (ADR 0067).

## The problem literal parity creates

`develop` can own a worktree per task because it is the **last producing phase** — nothing
downstream reads its output from the main checkout. The document phases are a **chain**:

```
research → product → architecture → plan → develop
   each reads its predecessor via handoff.load_artifact from docs/sdlc/<slug>/
```

Give each phase its own worktree and its own PR, and `architecture` — running next, often in the same
session — **cannot find the PRD**: it lives on an unmerged branch. Literal parity therefore forces
one of two bad outcomes:

- **serialize the spine on merge latency** — every handoff waits for CI and a human, so a spine run
  becomes days instead of a session; or
- **have phases read each other's branches** — which couples phases to git state and contradicts
  ADR 0013's rule that phases are joined *only* by committed handoff artifacts.

**A second interaction, easy to miss:** the merge gate blocks on `checks: NONE` (ADR 0063 — "no
builds is not green builds"). A docs-only PR in a downstream repo often has **no CI at all**, so
auto-merge would never fire for it. Parity in delivery does not imply parity in mergeability.

## Decision

**One feature worktree and one PR per feature — not per phase.**

### 1. A feature branch, shared by every document phase

The first document phase to run for `<feature-slug>` creates `../wt-docs-<slug>` on a branch
`docs/<slug>`, and records it in `docs/sdlc/<slug>/.worktree` (or the existing scheduling state).
Every later phase for the same feature **reuses it**.

This is what keeps the chain intact: all phases share one tree, so `handoff.load_artifact` finds the
predecessor's artifact exactly as it does today. The phases stay joined by artifacts, not by git
refs — ADR 0013 is preserved.

### 2. Each phase commits its own artifact on `proceed`

On the loop's `proceed` exit the phase commits **only its own** artifact(s) with a conventional
message (`docs(product): PRD for <slug>`). On `escalate` it commits nothing and leaves the worktree
in place — the work is preserved and inspectable, but nothing is delivered.

### 3. The PR is opened once and grows

The first `proceed` pushes the branch and opens the PR. Every later phase pushes to the **same** PR,
so a reviewer sees the feature's whole paper trail — brief, PRD, design, ADRs, plan — as one change
set, which is how a human actually wants to review a feature's documentation.

### 4. `escalate` opens the PR as a **draft**

If a phase escalates after the PR exists, it marks the PR a draft. This needs no new machinery: the
merge gate already blocks on `draft PR` (ADR 0063). An unresolved review therefore stops the merge
through the *existing* rail rather than a new one.

### 5. Monitoring and merge are entirely reused

The PR-created hook enqueues it (ADR 0068/0069), the scheduled drain watches it, and the ADR 0067
gate decides the merge. **No new merge path, no new watcher, no new settings.**

### 6. Worktree lifecycle has a named owner

`develop` owns its worktrees; nobody would own this one. The rule: the **feature worktree is removed
when its PR is merged or closed** — detected by the same drain that already reads `state` and drops
the queue entry. **Deferred, not built:** an orphan sweep (branch gone, worktree left) — until it exists,
a worktree whose PR was closed outside the drain must be removed by hand
(`git worktree remove ../wt-docs-<slug>`).

## What this deliberately does NOT do

- **No per-phase PR.** Literal parity, rejected above: it serializes the spine or breaks the artifact
  contract. Six PRs per feature is also ceremony for a solo maintainer and noise for a reviewer.
- **No auto-merge promise for docs-only PRs.** Where the repo has no docs CI, `checks: NONE` blocks
  by design. Enabling this and expecting merges without a docs check would look broken — a repo that
  wants auto-merged doc PRs needs at least one check (a link/schema/lint job).
- **No change to the conversational phases' elicitation.** `product`, `ux-design` and `marketing`
  question the user *before* writing. The draft then lands in `../wt-docs-<slug>/…`, which is **not**
  where the user's editor is pointed — a real ergonomic cost, and the strongest argument against this
  whole ADR. Mitigation: the phase reports the absolute path on every write.

## Alternatives considered

- **Literal per-phase parity with `develop`.** Rejected — §"The problem".
- **Branch + commit + PR without a worktree** (work in the main checkout). Simpler and keeps files
  where the user expects them, but leaves the user's checkout on a feature branch with staged doc
  changes — the state `develop` exists to avoid. Worth reconsidering if the ergonomic cost of §"What
  this does NOT do" proves dominant in practice.
- **Status quo (write straight to the checkout).** Rejected for feature work, but note it remains
  right for a *one-off* document written outside a feature flow; the design applies only when a
  `<feature-slug>` is in play.
- **Commit to the current branch without a PR.** Rejected — it delivers unreviewed documents, which
  is the gap this closes.

## Consequences

- A feature's documentation becomes reviewable as one PR, by the same machinery that reviews code,
  and `escalate` stops leaving rejected artifacts in the user's checkout.
- The spine keeps running in one session: phases share a tree, so no handoff waits on a merge.
- Six phase bodies gain worktree + git steps, and each gains the ability to push to a remote — an
  authority no document phase has today. That is the largest single expansion of blast radius in
  this design; it ships on the maintainer's explicit call after that cost was stated.
- **Unvalidated dependency:** this rests entirely on the PR watcher, which still has **no real-PR
  run** (a debt since ADR 0045). Building doc delivery on it before that validation would put the
  project's own documents through an unproven path.
