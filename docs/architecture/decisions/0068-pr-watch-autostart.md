# 0068 — Auto-start the PR watch: intent queue + a 10-minute drain

Status: Accepted — **implemented**. Narrows
[0063](0063-autonomous-pr-watch.md) §6; builds on [0024](0024-stage7-scheduling-observability.md)
(no daemon), [0044](0044-pr-watcher.md) / [0045](0045-pr-watcher-1b.md) (the watcher) and
[0067](0067-deep-review-remediation.md) (the gate and the trust boundary).

## Context

Today nothing connects a created PR to the watcher. `develop` never opens a PR (it ends at a
merge-ready branch); the `pr_created.py` hook only *prints a reminder*; and `pr-watch` is
`disable-model-invocation: true`, so only a human `/pr-watch` — or the hourly scheduled job over
`pr_watcher.repos` — starts anything.

The ask: after a PR is created, monitoring starts **by itself**, ticks every **10 minutes**, and
merges once comments are resolved, builds are green and there are no conflicts.

## The constraint that shapes the whole design

**A Claude Code plugin has no daemon** (ADR 0024, unchanged). A hook is a short-lived process with a
10-second budget; it cannot loop for hours. A session ends. So "monitoring runs by itself" can only
mean one of:

| Mechanism | Verdict |
| --- | --- |
| Hook spawns a detached looping process | **Rejected.** An invisible, session-independent process that can merge PRs — the exact hazard 0063 §6 named, made worse by being unattended and unlogged in the transcript. |
| Hook writes intent; the existing scheduler drains it | **Chosen.** Keeps the no-daemon architecture, reuses the audited outward-write path, and leaves one visible file describing what is being watched. |
| Model-driven: the hook tells the session to watch | Kept as the *interactive* path (`/pr-watch`), but it dies with the session, so it cannot be the answer. |

## Decision

### 1. The hook records intent; it still starts nothing

`pr_created.py` gains one behaviour, gated by a **new** `pr_watcher.auto_watch` (default `false`):
on a real `gh pr create` that returned a PR URL, append `{owner, name, number, branch, enqueued_at}`
to `.agentic-forge/pr-watch-queue.json`.

This is the minimal, defensible reversal of 0063 §6: **recording intent is not starting an agent.**
The hook still never blocks, never spawns a process, and never merges. What it produces is a file a
human can read and delete.

### 2. The existing scheduler drains the queue on a 10-minute cadence

- `schedule.CADENCES` gains `"10min": 600`.
- A new job `pr-watch-queue` (cadence `10min`) reads the queue and, for each entry, runs the
  **existing** `dev/pr_watch.py --apply` path — which already carries the ADR 0067 trust boundary
  (settings resolved before `gh pr checkout`), the recomputed merge gate, `auto_merge`, and
  `confirm_merged`.

**No new merge path is created.** That is the point: everything hardened in 0067 stays the single
way a merge can happen.

### 3. The queue is bounded and self-clearing

An entry is dropped when:
- the PR reads `MERGED` or `CLOSED` (the gate already fetches `state` — ADR 0067), **or**
- `pr_watcher.max_ticks` (default 144 = 24 h at 10-minute cadence) is exhausted, **or**
- the entry fails validation.

Every drop is recorded via the same `diagnostics.emit(..., force=True)` the watcher already uses for
outward actions. **Nothing is watched forever**, which is what keeps a stuck PR from consuming a poll
slot indefinitely.

### 4. Two independent switches, both off by default

| Setting | Default | Meaning |
| --- | --- | --- |
| `pr_watcher.auto_watch` | `false` | The hook enqueues a created PR. |
| `pr_watcher.auto_merge` | `false` | The drain may merge when the gate opens. |

Watching **without** merging is the safe middle setting and is genuinely useful on its own: it
triages review comments and resolves conflicts while leaving the merge to a human. Collapsing the two
into one switch would make "I want it to handle comments" imply "I want it to merge".

### 5. The queue is treated as untrusted input

`.agentic-forge/*` is gitignored except `config.json`, so a pull request **cannot** commit queue
entries — but the file is written by a hook that runs in any session, so the drain validates on read:
`owner/name` against the schema's existing pattern, `number` a positive int, and a hard cap on queue
length. A malformed entry is dropped and recorded, never executed.

## What this does NOT give you

**"Every 10 minutes" is only as true as the external clock.** The plugin cannot make time pass: the
cadence gates how often the job *may* run, while the **user's cron / launchd / CI schedule** decides
how often `run_scheduled.py` is invoked at all. With an hourly cron, ticks are hourly no matter what
`poll_seconds` says. Enabling this therefore has a prerequisite the plugin cannot satisfy for you:

```cron
*/10 * * * *  cd /path/to/repo && python dev/run_scheduled.py
```

This must be stated at the setting, or the feature will appear broken to anyone who enables it
without changing their cron.

## Alternatives considered

- **Have `develop` open the PR and start the watch.** Rejected for this increment: it would give a
  code-writing phase outward GitHub write authority, which no phase has today, and it couples the
  spine to a hosting provider. Opening the PR stays a human act; the hook reacts to it.
- **A `--daemon` mode on `dev/pr_watch.py`.** Rejected — reverses ADR 0024 for one feature, and puts
  a long-lived merging process outside the audited scheduler path.
- **Reuse `pr_watcher.repos` (watch every open PR in a repo).** Rejected as the default: it watches
  PRs nobody asked to watch, including other people's. The queue is explicit consent, per PR.
- **One switch instead of two.** Rejected — see §4.

## Consequences

- With both switches on and a 10-minute cron, a created PR is carried to merge unattended. With
  `auto_watch` on and `auto_merge` off (the recommended first step), it is carried to *ready* and
  waits.
- ADR 0063 §6 is narrowed, not deleted: the hook still never starts an agent. The reversal is that it
  may now leave a record that causes one to run **later, in the scheduler, under the settings**.
- The blast radius of a bug in the hook grows: a bad enqueue means an unwanted watch. Bounded by
  validation, the tick cap, and `auto_merge` being separately off.
- **This design is unproven against a real PR.** The watcher has never been driven end to end on one
  (a debt outstanding since ADR 0045). Shipping auto-start *before* that validation would automate a
  path nobody has watched work — so the proposed order is: validate the watcher manually on one real
  PR first, then enable auto-start.
