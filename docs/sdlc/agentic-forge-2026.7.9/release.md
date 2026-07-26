---
type: release
feature: agentic-forge-2026.7.9
status: final
version: 2026.7.9
date: 2026-07-26
changelog:
  - "Added: delivery parity for the six document phases (ADR 0070) — research, product, architecture, plan, ux-design and marketing now write into an isolated feature worktree, commit on `proceed`, and deliver as a pull request carried by the existing gate. One worktree and one PR per FEATURE, never per phase: per-phase would leave `architecture` unable to read the PRD `product` just wrote"
  - "Added: `escalate` commits nothing and marks the feature PR a draft — no new machinery, because the merge gate already refuses a draft PR (ADR 0063)"
  - "Added: `doc_delivery.py` (naming + argv only; slug validated rather than sanitised; never `--force`) and `patterns/doc-delivery.md`, so the procedure lives in one place rather than six skill bodies and the router budget is untouched"
  - "Added: the delivery contract is a GATE — `test_review_loop_shape.py` pins that each of the six links the pattern and states both exit branches, the contract class that shipped broken twice before (ADR 0060 §4, 0061)"
  - "Changed: `pr_watcher.auto_watch` defaults to ON, bounded by `enabled` — the enqueue now requires BOTH, which is what stops the plugin writing a queue file into every installing repo (ADR 0069). `auto_merge` unchanged and still off"
breaking: []
---

# Release 2026.7.9

Documents now ship the way code does.

## What changed

**Delivery parity for the document phases (ADR 0070).** The PRD, tech design and its ADRs, work
plan, research brief, ux-spec and marketing deliverables were written **straight into the user's
checkout** — verified across all six phase bodies before starting: zero occurrences of worktree,
branch, commit or `gh pr create`. Their *review* contract was already identical to code's
(ADR 0060–0062); the gap was isolation and delivery, and it had a concrete cost — an `escalate`d
phase left its rejected artifact sitting in the working tree.

Now each phase works in `../wt-docs-<slug>` on `docs/<slug>`, commits its own artifact on `proceed`,
and the feature's documentation arrives as a pull request that the existing watcher carries through
the existing gate.

**The load-bearing choice — and a deliberate departure from the request.** The ask was "full parity
with `develop`". Literal parity — a worktree and a PR per *phase* — was rejected, because the
document phases are a chain: `architecture` reads the PRD `product` just wrote. Per-phase branches
would leave that input unmerged and invisible, forcing either a spine serialised on merge latency or
phases reading each other's git refs, which contradicts ADR 0013's rule that phases are joined only
by committed artifacts. So: **one worktree and one PR per feature**, shared by every phase. The
departure is recorded in the ADR rather than quietly implemented.

**`escalate` uses a rail that already exists**: it commits nothing and marks the PR a draft, which
the merge gate already refuses (ADR 0063). No new blocking mechanism was introduced.

**`auto_watch` on by default, bounded by `enabled` (ADR 0069).** Flipping the default alone would
have been wrong: the enqueue was gated on `auto_watch` *alone*, so it would have made the plugin
write a queue file into **every** installing repo on **every** `gh pr create`, including repos whose
owner never enabled the watcher and would never drain the queue. Requiring both switches is what
makes the default safe, and it reframes the setting as *"within an enabled watcher, watch the PRs
you create"* — **which** PRs, not **whether** the watcher runs.

## The review of this work found three defects in it

All of the doc-truth class the 2026.7.7 deep review was written about, all fixed before merge:

1. ADR 0070 still marked **Proposed** after being implemented.
2. A consequence line still reading *"the reason it is proposed rather than shipped"*.
3. §6 promising a `--prune-doc-worktrees` sweep that **was never built** — now marked deferred, with
   the manual command given.

It also asked the question that cost two blockers this week — *who actually calls this?* Unlike the
merge-rails blocker, `doc_delivery` makes **no enforcement claim** (verified: no "enforced" /
"tested core" / "guarantee" anywhere in it); it is naming and argv, and the pattern says plainly
that the skill executes. To keep that link from rotting silently, the delivery contract became a
gate.

## Verification

- **Tier-0**: `validate.py`, `pytest` (coverage 95.31%), `ruff`, `mypy` — clean.
- **Tier-3 dry-run**: clean on all five scenarios.
- **Live Tier-1 / Tier-3 not re-run**, deliberately: no skill `description` changed (what Tier-1
  measures), and the E2E checkpoints are untouched. The six bodies gained a delivery note and two
  exit-branch clauses; the new gate test pins those directly.

## Not validated

- The document phases' git and `gh` steps are **model-followed instructions**, exercised by no live
  run — the same shape as every other phase procedure, but new here.
- The PR watcher this delivery rests on **still has no real-PR run** (a debt since ADR 0045). It
  now carries the project's own documents. Shipped on the maintainer's explicit call after that was
  stated.
- **A docs-only PR may never auto-merge**: the gate blocks on `checks: NONE`, and many repos have no
  documentation CI. That is the gate working as designed; such a repo needs a check on doc PRs.
- An orphan-worktree sweep is **deferred, not built** — a worktree whose PR was closed outside the
  drain must be removed by hand.

## Tag

`v2026.7.9` (annotated) on the merged master commit, created after the PR's rebase merge.
