---
name: pr-watch
description: Babysit a GitHub pull request or CI run — poll checks, review threads, and mergeable state via `gh` at a cadence matched to the pending work, report each transition, and (only on explicit request) drive the bounded review-thread fix loop from agentic_forge.pr_watch. Manual utility — run /pr-watch to watch a PR until green/merged, babysit CI, or work through review comments. It never merges and never force-pushes.
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

## Safety invariants

- **Never merge; never force-push** — the lib deliberately has no builder for either.
- No outward write (reply / resolve / push) without the user's explicit request in this session.
- Bounded: at most `pr_watcher.max_threads` threads per pass; idempotent re-polls (resolved /
  bot-authored threads and an already-posted conflict notice are skipped).

## Output

A baseline report, transition-only updates, and a final summary (checks, threads, mergeable,
recommended next action); in fix mode additionally the fixed/rejected breakdown. Nothing is
fabricated: every state comes from a `gh` read in this session.
