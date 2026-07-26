# Pattern: document delivery (isolation → PR → gated merge)

The document phases produce reviewable artifacts, so they deliver them the way code is delivered:
in an isolated worktree, as a pull request, merged through the same gate. Shared here rather than
repeated in six skill bodies. Deterministic naming and argv live in `agentic_forge.doc_delivery`
(ADR 0070).

## The one rule that shapes everything

**One worktree and one PR per FEATURE — never per phase.**

The document phases are a chain: `architecture` reads the PRD `product` just wrote. Give each phase
its own branch and the next phase cannot find its input — it would sit unmerged — which either
serialises the spine on merge latency or forces phases to read each other's git refs, contradicting
the rule that phases are joined only by committed artifacts ([handoff.md](handoff.md)).

So every document phase working on `<feature-slug>` shares `../wt-docs-<slug>` on `docs/<slug>`.

## Procedure

**Before writing the artifact:**

1. Skip all of this when there is no `<feature-slug>` — a one-off document written outside a feature
   flow belongs in the checkout, as before.
2. Reuse or create the feature worktree: if `doc_delivery.worktree_dir(slug)` exists, work there;
   otherwise `doc_delivery.add_worktree_argv(repo, slug, base)`. **Report the absolute path** — the
   user's editor is not pointed at it, and a conversational phase must not leave them hunting for
   the draft.
3. Write the artifact under `<worktree>/docs/sdlc/<slug>/`, and read upstream artifacts from the
   same worktree, so the chain resolves.

**After the review loop exits:**

4. **`proceed`** — commit this phase's artifact only (`commit_argv`, message
   `docs(<phase>): <slug>`), push (`push_argv` — plain, **never** `--force`), then:
   - no open PR for `docs/<slug>` (`pr_view_argv` returns nothing) → open one (`pr_create_argv`),
     titled for the feature, body listing the artifacts delivered so far;
   - a PR already exists → the push updated it. Say so; do not open a second.
5. **`escalate`** — commit **nothing**. If the PR exists, mark it a draft (`pr_draft_argv`). This
   needs no new mechanism: the merge gate already refuses a `draft PR`, so an unresolved review
   stops the merge through the rail that is already tested.
6. Report the PR URL. Monitoring and merge are **not** this phase's job — the PR-created hook
   enqueues it and the scheduled drain carries it through the gate (pr-watch, ADR 0068).

**Lifecycle:** the worktree is removed when its PR merges or closes. Until then it is the feature's
shared workspace, which is why no single phase removes it (unlike `develop`, which owns and removes
its own).

## What this does not promise

**A docs-only PR may never auto-merge.** The gate blocks on `checks: NONE` — "no builds" is not
"green builds" — so in a repo with no documentation CI the PR waits for a human. That is the gate
working as designed; a repo that wants doc PRs merged automatically needs at least one check on
them.

See also: [worktree.md](worktree.md) (the isolation discipline this follows),
[review-loop.md](review-loop.md) (the loop whose exit decides commit vs draft).
