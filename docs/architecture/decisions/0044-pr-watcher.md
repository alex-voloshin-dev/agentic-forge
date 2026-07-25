# 0044 — PR watcher: monitor a GitHub PR, bounded auto-fix loop

Status: Accepted — **implemented** (planned-increment 1; see the [Unreleased] CHANGELOG entry).
**The "never merges" invariant below was deliberately reversed by
[ADR 0063](0063-autonomous-pr-watch.md)** (opt-in `pr_watcher.auto_merge`, gated by a pure
`merge_readiness` check); "never force-pushes" stands and is now the only absolute.

## Context

Planned-increment 1 (the largest, last). Monitor a GitHub PR hourly; read its review comments and
merge-conflict state; run a **bounded fix loop** that addresses each actionable reviewer comment
(fix it, or reject it with a reasoned reply), resolves the thread, and resolves merge conflicts —
**never merging**. It is the **only increment with outward GitHub writes**, so it is opt-in,
bounded, recorded, and dry-run by default. The user chose the autonomy level: **auto-fix + push**
(fix and push to the PR branch + reply/resolve threads automatically, gated by a settings flag,
not auto-merge).

## Decision

1. **Autonomy = auto-fix + push, opt-in.** Off by default (`settings.pr_watcher.enabled` is false,
   and the CLI defaults to `--dry`). When enabled it pushes fixes to the PR branch and posts /
   resolves review threads automatically; it **never merges** and **never force-pushes**. Every
   outward action is recorded as a `diagnostics` event (ADR 0039).

2. **Deterministic core + model-orchestration split (the project's pattern).**
   `lib/agentic_forge/pr_watch.py` is **pure** parsing + planning + command-building over the `gh`
   CLI / GraphQL JSON; the live model fix and the `gh` / `git` writes are **thin seams** (injected;
   the real calls are excluded from coverage, like the transports / connectors):
   - `parse_pr(data)` → a `PrState` (mergeable state + review threads with `id`, `isResolved`,
     comments).
   - `actionable_threads(state, *, bot)` → unresolved threads not authored by the bot (idempotency:
     a resolved or bot-owned thread is skipped).
   - command builders (`reply_argv`, `resolve_argv`, `push_argv`) → argv lists (testable as data;
     execution is a separate seam).

3. **Bounded + idempotent.** At most `settings.review.passes` fix passes; a thread once handled
   (replied + resolved, or rejected) is not re-processed (tracked by thread id). The hourly poll
   re-checks the live state, so there is no thrash and no re-fixing a resolved comment.

4. **Conflicts: detect now, resolve later.** This increment **detects** a `CONFLICTING` mergeable
   state and surfaces it (in the plan + result); **mechanical resolution is deferred to 1b** (a
   rebase/merge attempt → route to `software-engineer` → surface-and-stop). It never merges/forces.

5. **Hourly cadence via the existing scheduler.** `hourly` is added to `schedule.CADENCES` (the
   cadence the watcher's job will use); the **`pr-watch` job registration is deferred to 1b** with
   the "which PRs to watch" design. The "no daemon" constraint (ADR 0024) holds — a cron-triggered
   headless run drives it. For now the entry point is `dev/pr_watch.py`.

6. **Fix-vs-reject is the fixer's judgment, and rejections are explained.** The shipped fixer runs
   the change, then reports `fixed` **only if a diff actually landed** (it commits it so the push
   delivers it, and replies `Addressed in <sha>` + resolves); if no change landed it reports
   `rejected` with the reasoning and **leaves the thread open** — never silently resolving a
   disputed / unaddressed comment.

7. **Safety invariants:** never merge (*superseded by ADR 0063 — merging is now possible behind the
   opt-in `auto_merge` + the merge gate*); never force-push; opt-in (`enabled` + non-dry); bounded;
   every outward write recorded in diagnostics **unconditionally** (`emit(force=True)` — auditing
   GitHub writes is not subject to the diagnostics toggle); dry-run plans without writing. The fixer
   runs **without the Bash tool** (Read/Write/Edit/Grep/Glob only) to bound prompt-injection from
   the attacker-controlled comment body. **Trust boundary:** enabling auto-fix runs a headless agent
   on attacker-influenceable PR content and then pushes — enable it only for PRs/repos you trust.
   Auth is the user's `gh`; a missing `gh` degrades to a no-op with a message.

## Alternatives considered

- **Propose-only / hybrid autonomy:** not chosen — the user selected auto-fix + push (the spec asks
  the watcher to *resolve* comments and conflicts, not just propose). The conservative modes remain
  reachable via `--dry` (plan only).
- **A model-invocable skill:** rejected — the watcher is **headless / scheduled**, not user-routed,
  so it needs no Tier-1 routing surface (and avoids the on-listing router-budget review). It is a
  lib + a scheduled job + a CLI.
- **Auto-merge once all threads resolve:** rejected — merging is a human decision; the watcher never
  merges.
- **Parse review state from `gh pr view --json`:** insufficient — per-thread `isResolved` needs the
  GraphQL API; the fetch seam uses `gh api graphql`, parsed by `parse_pr` (the exact query lives in
  one documented place, adjustable per `gh` version).

## Consequences

- A bounded, opt-in, hourly PR auto-fix loop with real GitHub writes (push / reply / resolve), which
  **never merges**. The deterministic core (parse / plan / build) is unit-tested; the live fix + the
  `gh`/`git` writes are seams **validated on a real PR** (they can't be exercised here, and the real
  calls are coverage-excluded like the other transports).
- Off by default; nothing happens without `pr_watcher.enabled` + a non-dry run; every write is
  recorded in diagnostics, so an over-eager loop is auditable.
- Hourly scheduling reuses the existing cron/registry; `hourly` is now a cadence other jobs can use.
