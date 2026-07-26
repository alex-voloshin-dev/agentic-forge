---
type: release
feature: agentic-forge-2026.7.8
status: final
version: 2026.7.8
date: 2026-07-26
changelog:
  - "Added: auto-start the PR watch (ADR 0068) — with the new `pr_watcher.auto_watch` (off by default) the PR-created hook appends the PR to a gitignored `.agentic-forge/pr-watch-queue.json`, and a new `pr-watch-queue` scheduled job on a new `10min` cadence drains it through the EXISTING `dev/pr_watch.py --apply` path"
  - "Added: `pr_watcher.max_ticks` (default 144 = 24 h at the 10-minute cadence) — an entry leaves the queue when its PR is MERGED/CLOSED or its tick budget is spent, each drop audited, so a PR that never becomes mergeable cannot hold a poll slot forever"
  - "Changed: ADR 0063 §6 is narrowed, not deleted — the hook records intent but still never blocks, never spawns a process and never merges; no new merge path exists, so the ADR 0067 trust boundary, recomputed gate, auto_merge and confirm_merged all apply unchanged"
  - "Security: the queue is treated as untrusted input (it is written by a hook that runs in any session) — the drain validates slug pattern, positive int and `True`-is-not-a-number, caps the queue, and drops rather than executes anything malformed"
breaking: []
---

# Release 2026.7.8

One feature: a created pull request can now be carried to done unattended — without giving any hook
the authority to start an agent that merges.

## What was missing

Nothing connected a created PR to the watcher. `develop` never opens a PR (it ends at a merge-ready
branch), the `pr_created.py` hook only printed a reminder, and `pr-watch` is
`disable-model-invocation: true` — reachable only by a human `/pr-watch`, or by the hourly job over
`pr_watcher.repos`, which watches every open PR in a repo rather than the one you just made.

## The constraint that shaped it

**A plugin has no daemon** (ADR 0024, unchanged). A hook is a short-lived process with a ten-second
budget, and a session ends. So the obvious implementation — the hook spawns a loop — was rejected:
an invisible, session-independent process that can merge pull requests is precisely the hazard
ADR 0063 §6 named, made worse by being unattended and absent from the transcript.

What ships instead: **the hook records intent, the existing scheduler executes it.**

```
gh pr create
  → hook prints the reminder; with `auto_watch`, appends to .agentic-forge/pr-watch-queue.json
  → hook exits. Nothing started.
scheduler job `pr-watch-queue` (cadence 10min)
  → each entry through the EXISTING dev/pr_watch.py --apply
  → entry leaves on MERGED/CLOSED, or when max_ticks is spent
```

**No new merge path exists.** Everything hardened in ADR 0067 — the trust boundary, the recomputed
gate, `auto_merge`, `confirm_merged` — stays the single way a merge can happen. The drain only
decides *which* PRs get a pass. ADR 0063 §6 is therefore **narrowed**, not deleted: recording intent
is not starting an agent, and what the hook leaves behind is a file a human can read and delete.

## Rails

- **Two independent switches, both off by default.** `auto_watch` enqueues; `auto_merge` merges.
  Watching *without* merging is the safe middle setting and useful on its own — it triages review
  comments and resolves conflicts while the merge stays a human decision. A single switch would make
  "handle my review comments" imply "merge my pull request".
- **Bounded.** An entry leaves on `MERGED`/`CLOSED` or after `max_ticks`; every drop is audited.
- **The queue is untrusted input** — written by a hook that runs in any session. The drain validates
  on read (slug pattern, positive int, and `True`-is-not-a-number, since a bool *is* an `int` in
  Python), caps the queue length, and drops rather than executes anything malformed. `.gitignore`
  already excludes `.agentic-forge/*` except `config.json`, so a pull request cannot commit entries.

## Prerequisite the plugin cannot satisfy for you

The cadence gates how often the job *may* run; your clock decides how often the runner is invoked at
all. A ten-minute tick needs a ten-minute cron:

```cron
*/10 * * * *  cd /path/to/repo && python dev/run_scheduled.py
```

With an hourly cron the drain is hourly, whatever the setting says. This is documented at the
setting, because otherwise the feature looks broken to anyone who enables it without changing their
schedule.

## Verification

- **Tier-0**: `validate.py`, `pytest` (coverage 95.30%), `ruff`, `mypy` — clean.
- The hook was exercised live in both directions on a scratch repo: with `auto_watch: false` the
  queue file is never created; with `true` the entry appears.
- The new scheduled job was confirmed to be reachable (`run_scheduled.py --dry` lists it as due) —
  the "who actually calls this?" question that the 2026.7.7 deep review showed a green test suite
  cannot answer.

**Live Tier-1 / Tier-3 were not re-run**, deliberately: this release changes no skill `description`
(what Tier-1 measures), no spine phase body, and no E2E checkpoint. The changed surfaces are the
hook, the scheduler, a pure queue core and settings — all unit-tested.

## Not validated

The watcher has **still never been driven against a real pull request** (a debt since ADR 0045), and
that now extends to the drain: its live `gh` calls are seams marked `pragma: no cover`. Enabling
`auto_merge` on top of `auto_watch` automates a path nobody has watched work. The recommended order
is `auto_watch` first, on one real PR, and `auto_merge` only after that.

## Tag

`v2026.7.8` (annotated) on the merged master commit, created after the PR's rebase merge.
