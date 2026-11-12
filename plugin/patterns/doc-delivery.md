# Pattern: document delivery (isolation → PR → gated merge)

The document phases produce reviewable artifacts, so they deliver them the way code is delivered:
in an isolated worktree, as a pull request, merged through the same gate. Shared here rather than
repeated in six skill bodies. Deterministic naming and argv live in `agentic_forge.doc_delivery`
(ADR 0070), reached through `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py"` (ADR 0104). Its `doc-*` commands print
commands as `{"argv", "shell"}` and run none: decode `shell` from JSON first (`\"` is `"`), then run
it yourself, so that the guardrail hooks see it. Do not copy the JSON text onto a command line.

`${CLAUDE_PLUGIN_ROOT}` below is the plugin's directory, the one holding `skills/` and `patterns/`, and is not normally set in a shell: if this file reached you unexpanded, use the path your skill's own commands show.


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
2. Reuse or create the feature worktree: `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" doc-worktree --repo . --slug <slug> --base <base>`
   gives its `worktree` path; if `exists`, work there; otherwise run its `add`. **Report the absolute path** — the
   user's editor is not pointed at it, and a conversational phase must not leave them hunting for
   the draft.
3. Write the artifact under `<worktree>/<feature-dir>/`, the feature folder `artifact-home` finds
   (`docs/sdlc/<slug>/` when the repository keeps none; [handoff.md](handoff.md#where-a-features-documents-go)),
   and read upstream artifacts from the same worktree, so the chain resolves. With no
   `<feature-slug>`, `<worktree>` is the checkout.

**After the review loop exits:**

4. **`proceed`** — first set the artifact's `review_decision` to `proceed` (leave its `status`, which is
   the repository's) and run `handoff-load` on it again ([review-loop.md](review-loop.md)), or the next
   phase refuses it. Then
   `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" doc-proceed --worktree <worktree> --phase <phase> --slug <slug> --artifact <path>`
   (each `<path>` is the document's quoted `arg` from `artifact-home`, never a path typed by hand)
   gives the `steps` for this repo: stage and commit this phase's artifact only (message
   `docs(<phase>): <slug>`; `--artifact` repeats for more than one), push (plain, **never** `--force`).
   When its `open_pr` is true, with the body written to a file outside the worktree,
   `python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" doc-pr-argv --repo-slug <owner/repo> --slug <slug> --title <title> --body-file <file>`
   gives `view` and `create` (a title takes letters, digits and `._:/()#+-` only), then:
   - no open PR for `docs/<slug>` (`view` returns nothing) → open one (`create`),
     titled for the feature, body listing the artifacts delivered so far;
   - a PR already exists → the push updated it. Say so; do not open a second.

   **A repo with no remote or no `gh` is not a failed phase.** With nowhere to push, the
   `steps` only commit and the `note` says `no remote: committed on docs/<slug>, not
   pushed`; with a remote but no `gh` on PATH they push and the `note` gives the branch for a
   hand-opened PR. The `note` is the sentence to report.
5. **`escalate`** — set the artifact's `review_decision` to `escalate` and commit **nothing**. If the PR exists, mark it a draft (`gh pr ready <n> -R <owner/repo> --undo`). This
   needs no new mechanism: the merge gate already refuses a `draft PR`, so an unresolved review
   stops the merge through the rail that is already tested.
6. Report the PR URL. Monitoring and merge are **not** this phase's job — the PR-created hook
   enqueues it and the scheduled drain carries it through the gate (pr-watch, ADR 0068).

**Lifecycle:** the worktree is removed when its PR merges or closes. Until then it is the feature's
shared workspace, which is why no single phase removes it (unlike `develop`, which owns and removes
its own).

## Language

The delivered documents, the commit messages and the PR body follow the **project's** language
convention (usually English). The summary reported back in the conversation follows the **user's**
language — see [handoff.md](handoff.md#language-artifact-vs-summary).

## What this does not promise

**A docs-only PR may never auto-merge.** The gate blocks on `checks: NONE` — "no builds" is not
"green builds" — so in a repo with no documentation CI the PR waits for a human. That is the gate
working as designed; a repo that wants doc PRs merged automatically needs at least one check on
them.

See also: [worktree.md](worktree.md) (the isolation discipline this follows),
[review-loop.md](review-loop.md) (the loop whose exit decides commit vs draft).
