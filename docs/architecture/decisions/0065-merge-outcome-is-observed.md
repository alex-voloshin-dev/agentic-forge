# 0065 — The merge outcome is observed, not inferred from the command

Status: Accepted — **implemented**. Hardens [0063](0063-autonomous-pr-watch.md) (autonomous PR
watch), which introduced the merge step.

## Context

ADR 0063 gave the watcher a merge seam and took its success from the fact that the call returned.
Cutting a PR in this repository on 2026-07-25 showed why that is wrong:

```
$ gh pr merge 13 --rebase --delete-branch
failed to run git: fatal: 'master' is already used by worktree at '/private/tmp/afmaster'
$ gh pr view 13 --json state,mergedAt
state=MERGED mergedAt=2026-07-25T17:12:24Z
```

**`gh pr merge` is not atomic.** It merges on GitHub and *then* does local work — switching
branches, deleting the merged branch — and that local half can fail on its own, after the remote
merge has already landed. Here a leftover git worktree holding `master` made the local step fail;
the PR was merged regardless.

For an autonomous watcher this is worse than a cosmetic mis-report. Reading the non-zero exit as
"not merged" means the next poll finds an already-merged PR, tries to merge it again, fails again,
and reports failure forever — a loop that never converges, on a PR that was fine from the first
attempt.

## Decision

1. **`merged_argv(repo, number)` + `parse_merged(payload)`** — read the PR's own
   `state` / `mergedAt` and decide from that. `parse_merged` is tolerant of shape and of junk (a
   `gh` error object, a bare string, `None` all read as *not merged*), so a failed status read can
   never fabricate a merge.

2. **`run_watch(..., confirm_merged=…)`: the seam decides the outcome, in both directions.**
   - The merge command raising is caught and recorded as `merge_command_failed`, **not** as
     "unmerged"; `merged` comes from `confirm_merged()`.
   - A command that *succeeded* while the PR is not actually merged is likewise reported as
     unmerged. The observation wins either way — an exit status is evidence about a process, not
     about the pull request.
   - When the command failed **and** the PR is genuinely unmerged, the failure text becomes the
     `merge_blocked_by` reason, so the watch report says what went wrong.

3. **Without the seam, a failure still propagates.** A caller that wires no confirmation has no way
   to observe the truth, and guessing in either direction would be worse than raising: silently
   swallowing would claim a merge that may not exist; silently reporting "not merged" is the bug
   this ADR fixes. The pre-0065 contract is preserved exactly for those callers.

4. **The report distinguishes the two.** A merge whose command errored logs
   `merged (merge command errored; PR state confirms it landed)` rather than a bare `merged`, so the
   audit trail keeps the anomaly instead of hiding a successful-looking outcome.

## Alternatives considered

- **Parse the CLI's stderr for "already merged" / known-benign failures:** rejected — a deny-list of
  error strings is exactly the brittle pattern ADR 0059 had to unwind for the commit gate, where
  over-broad substrings matched genuine failures. Reading the resource's state is unambiguous.
- **Retry the merge on failure:** rejected as the primary fix — retrying an operation whose outcome
  is unknown is how a merged PR gets merged twice (or how a real failure loops). Confirm first; a
  retry can sit on top of a *known* "not merged".
- **Make the merge seam return `bool` instead of adding a confirmation seam:** rejected — it puts
  the same inference back in the caller and gives the tested core nothing to enforce. The point is
  that the outcome is a *read of the PR*, which is a different call from the merge.
- **Always require `confirm_merged`:** rejected — it would break existing callers (including the
  dry/plan paths) for no gain; the seam is optional and the no-seam behaviour is unchanged.

## Consequences

- The autonomous watcher can no longer be wedged by a merge that succeeded remotely and failed
  locally — the case that motivated this.
- `WatchResult` gains `merge_command_failed`, so "the merge landed but the command errored" is
  visible in the report and the audit trail rather than smoothed over.
- The same reasoning applies to any other non-atomic outward action the watcher might grow (a
  push that lands before a follow-up step fails, say): the outcome should be read, not inferred.
  Only the merge is wired this way today.
