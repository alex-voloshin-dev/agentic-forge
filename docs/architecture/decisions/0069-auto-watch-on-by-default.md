# 0069 — `auto_watch` on by default, bounded by `enabled`

Status: Accepted — **implemented**. Amends [0068](0068-pr-watch-autostart.md) §4.

## Context

ADR 0068 shipped `auto_watch` off by default, alongside `auto_merge`, as "two independent switches,
both off". In use that is one opt-in too many: a maintainer who has already turned the watcher **on**
(`pr_watcher.enabled`) and set up the 10-minute clock has plainly asked for their pull requests to be
watched — yet still had to discover and flip a second flag before anything happened.

Flipping the default as it stood would have been wrong, though, and the gap is worth recording: the
hook's enqueue was gated on `auto_watch` **alone**. Defaulting it on would therefore have made the
plugin write `.agentic-forge/pr-watch-queue.json` into *every* installing repo on *every*
`gh pr create` — including repos whose owner never enabled the watcher and would never drain the
queue, where the file would simply accumulate stale entries to its 50-entry cap.

## Decision

1. **The enqueue requires `enabled` AND `auto_watch`.** `enabled` is the master switch; with the
   watcher off, the queue file is never created and the plugin writes nothing into the repo.
2. **`auto_watch` defaults to `true`** — read as *"within an enabled watcher, watch the PRs you
   create"* rather than as a second opt-in. It changes **which** PRs get watched, not **whether** the
   watcher runs.
3. **`auto_merge` is unchanged and stays `false`.** The distinction the two switches encode is
   preserved exactly: watching is reversible and merging is not.

## Alternatives considered

- **Leave both off (0068 as shipped):** rejected per the maintainer's ask — an opted-in watcher that
  ignores the PRs you create is a surprising default.
- **Default `auto_watch` on without the `enabled` bound:** rejected — that is the version that writes
  a file into every installing repo unprompted. The bound is what makes the default defensible.
- **Fold `auto_watch` into `enabled`:** rejected — a user may legitimately want the scheduled
  `pr_watcher.repos` sweep without auto-queueing the PRs they personally open.

## Consequences

- For a repo with the watcher off (the default), behaviour is **unchanged**: no queue file, no writes.
- For a repo with the watcher on, PRs created in a session are now watched without a second flag.
- 0068 §4's "both off by default" is annotated in place rather than left untrue.
