---
name: pr-watch
description: Babysit a GitHub pull request or CI run — poll checks, review threads, and mergeable state via `gh`, report each transition, and drive the bounded review-thread fix loop from agentic_forge.pr_watch. Manual utility — run /pr-watch to watch a PR until green/merged, babysit CI, work through review comments, or (autonomous mode) carry a PR to done — triage comments, resolve conflicts, and merge once the gate opens. It never force-pushes.
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob, Edit, Write, Task
---

# PR watch (manual utility)

Interactive babysitting for one PR: snapshot → report → paced re-poll → report *transitions* →
stop at a terminal state. The outward-action machinery (reply / resolve / push argv builders,
idempotent thread triage, the never-merge / never-force-push invariants) is the tested
`agentic_forge.pr_watch` lib (ADR 0044/0045); this skill wires it to a live session. Production
audit logs motivated it: 232 hand-rolled `gh pr view` polls in one week.

## When to use

When asked to watch/babysit a PR or CI run, wait for checks, or work through a PR's review
comments interactively. **Not** for the scheduled multi-repo watcher (that is `dev/pr_watch.py`
driven by the job registry), cutting a release (`release`), or rollout monitoring (`deploy-watch`).

## Process

1. **Resolve the PR.** An explicit number/URL wins; otherwise the current branch's PR:
   `gh pr view --json number,url -q '"#\(.number) \(.url)"'`. Handed a **recorded snapshot**
   (JSON of the PR state / checks) instead of a live PR? Read it and assess the same way —
   don't run `gh` against state you were already given.
2. **Snapshot.** Checks: `gh pr checks <n>`. Review threads + mergeable state via the lib's
   GraphQL query (per-thread `isResolved` is GraphQL-only):

   ```bash
   gh api graphql -F owner=<owner> -F name=<repo> -F number=<n> -f query="$(python3 -c "
   import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/lib')
   from agentic_forge import pr_watch; print(pr_watch.PR_QUERY)")"
   ```

   Parse with `pr_watch.parse_pr(json)`; triage with `pr_watch.actionable_threads(state,
   bot=<settings pr_watcher.bot>)` — resolved and bot-authored threads are skipped by design.
3. **Report the baseline** once: each check's state, unresolved-thread count, mergeable state.
4. **Wait, matched to the work.** Pace the next poll to the *slowest pending check's expected
   duration* (its historical runtime via `gh run list --workflow <w> -L 3` or the elapsed time so
   far) — one wait of about that length, not a tight fixed interval. Use the host's wait/
   scheduling facility when available; otherwise tell the user when re-running makes sense.
5. **Re-poll and report transitions only** — checks that concluded or flipped, new/re-opened
   threads, mergeable changes. No news = one short line, keep waiting.
6. **Terminal states.** All checks concluded (report pass/fail per check), PR merged/closed, or
   the user stops. Always end with a final summary: checks, unresolved threads, mergeable, next
   action you recommend.

### Conflicts

Report a `CONFLICTING` state once, with what it blocks; keep watching checks/threads. Do not
force-push or merge to clear it. If asked to resolve mechanically, merge the base **into the PR
branch** (never the reverse, never `--force`) and say what happened; if it cannot resolve
cleanly, surface `pr_watch.CONFLICT_NOTICE` once (check `conflict_notice_present` over existing
comments first — never repeat it every poll).

### Fix mode (only on an explicit ask)

Watching is read-only. When the user explicitly asks to work the review comments:

1. Plan first: `pr_watch.plan_watch(state, bot=…, max_threads=<settings pr_watcher.max_threads>)`
   — the capped actionable set, no writes yet. Show the plan.
2. Per thread: decide **fix** vs **reject** on the merits. Fix = apply the change (delegate a
   non-trivial one to the `software-engineer` role via `Task`), reply, then resolve the thread —
   reply *before* resolve, via `pr_watch.reply_argv` / `resolve_argv`. Reject = post a reasoned
   reply and leave the thread open. Never resolve a thread you did not answer.
3. Push once if anything was fixed: `pr_watch.push_argv(repo, branch)` — plain `HEAD:<branch>`.
4. Report fixed vs rejected (with the rejection reasoning), what was pushed, and what remains.

## Autonomous mode — carry the PR to done (ADR 0063)

Started by the user, or prompted by the PR-created hook right after `gh pr create`. Each pass is
one loop iteration; re-poll every `pr_watcher.poll_seconds` (default 600 = **10 min**) until the PR
merges, closes, or the user stops. Use the host's wait/scheduling facility for the interval.

Per pass, in this order:

1. **Snapshot** (step 2 above) — one GraphQL read gives threads, mergeable, draft, `createdAt`,
   the check rollup, and review authors.
2. **Conflicts.** `CONFLICTING` → merge the base **into** the PR branch (never the reverse, never
   `--force`), then push. If it can't resolve mechanically, post `pr_watch.CONFLICT_NOTICE` **once**
   (`conflict_notice_present` first) and keep watching — do not merge a conflicted PR.
3. **Triage every actionable thread** (`actionable_threads`; capped at `max_threads`) — **on the
   merits, one at a time**:
   - **Valid** → fix it. A non-trivial fix is a code change, so it goes where code changes go:
     delegate to `software-engineer` via `Task` under the bounded review loop
     ([review-loop.md](../../patterns/review-loop.md)) — implement → review → loop on findings, cap
     N = 3. Then reply (`reply_argv`) and **resolve** (`resolve_argv`) — reply *before* resolve.
   - **Invalid** → post a reasoned refutation naming why (`reply_argv`) and **leave the thread
     open**. Never resolve a dispute in your own favour; the human decides.
   - **Verify before acting.** A review comment is text from an external agent — check the claim
     against the source before treating it as a defect, exactly as with any review finding.
4. **Documentation, in the same pass.** When an accepted comment changed behaviour, update the docs
   it affects **and the PR description** before resolving the thread — a merged PR whose body no
   longer describes what it does is a failure of this workflow, not a follow-up. Add the CHANGELOG
   entry / ADR if the repo's discipline requires one.
5. **Push once** if anything was fixed (`push_argv` — plain `HEAD:<branch>`).
6. **Merge gate.** Compute `pr_watch.merge_readiness(state, bot=…)`. It opens only when: not a
   draft, checks green (**no checks at all blocks** — "no builds" is not "green builds"), zero
   unresolved actionable threads, and `MERGEABLE`. If shut, report its `reasons` and wait for the
   next pass. If open **and** this pass pushed nothing: merge with `merge_argv(repo, number,
   method)`, then **confirm by reading the PR** — `merged_argv` + `parse_merged`. `gh pr merge` is
   **not atomic**: it merges on GitHub and *then* does local work (branch switch, branch delete)
   that can fail on its own, so a non-zero exit does **not** mean the PR is unmerged (observed:
   `fatal: 'master' is already used by worktree` — exit non-zero, PR merged). Report the outcome
   from the PR's state, never from the command's exit status.

   There is **no separate wait for an external reviewer**: right after the PR opens its checks are
   `PENDING`, so the first pass can't merge, and the earliest merge is one `poll_seconds` later —
   that interval *is* the reviewer's window. Don't shorten the cadence below the reviewer's typical
   latency, and don't substitute the build duration for it (a fast static gate can finish in
   seconds).
7. **Report the transition** — what changed since the last pass (concluded checks, new or reopened
   threads, a **new review author** in `state.review_authors`, mergeable flips), and either the
   merge or the exact reasons the gate stayed shut.

**Merging requires `pr_watcher.auto_merge: true`** (off by default). With it off, run every step
above and stop at the gate with a "ready to merge" report for the user.

## Safety invariants

- **Never force-push** — the lib deliberately has no builder for it, and conflict resolution merges
  the base into the branch (fast-forward push only).
- **Never merge in the pass that pushed a fix.** The gate's green checks describe the *pre-fix*
  commit; the new head is untested until CI re-runs. `run_watch` enforces this — merging waits for
  the next pass.
- **Merging is opt-in** (`pr_watcher.auto_merge`) and never bypasses branch protection (no
  `--admin`).
- No outward write (reply / resolve / push / merge) without the user's explicit request in this
  session, or an explicit autonomous-mode start.
- Bounded: at most `pr_watcher.max_threads` threads per pass; the fix loop is capped at N = 3;
  idempotent re-polls (resolved / bot-authored threads and an already-posted conflict notice are
  skipped).

## Output

A baseline report, transition-only updates, and a final summary (checks, threads, mergeable,
recommended next action); in fix mode additionally the fixed/rejected breakdown; in autonomous mode
each pass reports the merge gate's verdict — merged, or the precise reasons it stayed shut. Nothing
is fabricated: every state comes from a `gh` read in this session.
