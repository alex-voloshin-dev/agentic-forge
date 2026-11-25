---
type: release
feature: agentic-forge-2026.11.17
status: final
version: 2026.11.17
date: 2026-11-25
changelog:
  - "On one's own PR a changes review posted as COMMENT also posts each body-only finding as an inline thread anchored in the diff, so merge_preflight and branch protection hold the merge until it is resolved (field item 11, ADR 0110 amendment)."
  - "af.py pr-review places a finding that cites a renamed file's old path on the new file's lines."
breaking: []
---
# Release 2026.11.17

Field item 11 (thread 58b37c1c), recorded as an amendment to ADR 0110.

## What changed

- **A `changes` review on one's own PR now holds the merge.** GitHub refuses REQUEST_CHANGES on one's own pull request
  (422), so `af.py pr-review` posts a `changes` verdict there as COMMENT, and a finding outside the diff went to the
  review body only. The merge gates (merge_preflight and branch protection's conversation resolution) read unresolved
  threads, not a body, so such a review held nothing. Now, when the verdict is `changes`, the PR is one's own and the
  requested event was request-changes, every body-only finding is also posted as an inline comment:
  - anchored on the nearest added or context line of its own file, else the diff's first added line, else its first
    context line, else (a diff that only deletes) its first removed line on the left side;
  - opening with "Finding at `loc`. This thread sits here only to hold the merge; the line it is attached to is not
    the finding's.", then the finding as the body shows it, through the same mention-safe, capped path;
  - the body still lists every finding and names the line each thread sits on.
  - A diff with nothing to anchor on (a rename without hunks, a binary change, an empty diff) keeps the findings in
    the body and warns, in the body and on stderr, that the review will not hold a merge.
  - `--event comment` and another person's PR are unchanged. A verdict marker read by merge_preflight was declined: a
    review body is editable text.
- **A finding citing a renamed file's old path** is placed on the new file's lines, on every review; an exact path wins
  over a suffix match.

## How it was checked

- Review: reviewer, security-engineer and the external lens (codex) approve; the reviewer's and security lens's minors
  (an explicit prefix for the PR watcher's fixer, left-side anchors for deletion-only diffs, rename resolution, the
  100-thread note) and codex's follow-up minor (exact rename source before a suffix match) were applied after.
  Details in `review-code-1.md`.
- Tier-0: `dev/validate.py`, `ruff`, `mypy`, the full pytest suite, `dev/hook_smoke.py` under Python 3.9.

## Not validated

- Tier-1/1b/2/3: not run. The code-review skill body gained two sentences about the hold threads and the
  `af.py: pr-review: warning:` line; its description did not change.
- Not checked against the live GitHub API: that a thread from a COMMENT review on one's own PR counts toward
  "Require conversation resolution" (the design relies on GitHub counting every unresolved thread).

## Known limits

- Both gates read `reviewThreads(first:100)`, which counts resolved threads too: more than 100 threads over a PR's
  life keeps them shut as "truncated". Follow-up: paginate, or count only unresolved threads.
- The gates skip threads by the configured `pr_watcher.bot` login; if that is the fleet's own review login, these
  threads hold nothing. The author's login can resolve the threads.
