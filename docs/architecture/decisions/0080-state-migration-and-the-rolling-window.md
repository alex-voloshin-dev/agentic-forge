# 0080 — State migration is tooling, and the audit log is a bounded rolling window

**Status:** Accepted (implemented)
**Date:** 2026-07-26
**Completes:** 0072 (which moved the state but shipped no way to bring the history with it).

## Context

A field verification of 2026.7.10 confirmed ADR 0072 works — the in-repo directory is no longer
recreated, and the user-level log grew by exactly the expected records. It also found the thing
0072 left out.

### The migration fails silently in both directions at once

The reporter had migrated by hand before upgrading, into `~/.agentic-forge/state/f4ai/` — the
obvious guess. The real slug is `f4ai-7afa8034` (`repo_slug()` = name + digest of the absolute
path). What then happens:

1. `existing_state_file()` looks under `state/<slug>/` and finds nothing;
2. it falls back to the legacy in-repo path, finds the file, and keeps using it;
3. so the repo directory **stays alive** and the moved 16,676 records are **orphaned**.

Every component behaves exactly as designed, and the user concludes the cleanup worked. It did not.
Orphaned history *and* a resurrected directory — the worst pair for someone who migrated
specifically to be rid of that directory. Nothing surfaced the discrepancy. The reporter resolved
the slug by importing `state_root()` and printing it, and observed that this is "a fine diagnostic
and a poor user procedure."

A further detail that rules out the naive fix: **2026.7.9 kept appending to the legacy path while
they migrated**, so 102 records landed there *after* the copy. A move would have dropped them.

### Rotation and migration point in opposite directions

Ten days of daily use produced **8.1 MB / 16,780 records** for one repo. With `MAX_AUDIT_BYTES`
10 MB and `KEEP_AUDIT_BYTES` 5 MB, an active repo reaches rotation inside a fortnight — and the
first rotation discards the earliest ~3 MB of exactly the history a migrating user just took care
to preserve. Rotation is a **routine event** here, not an edge case, and it was silent.

## Decision

### 1. Surface a half-done migration (`session_start`)

`diagnostics.legacy_state_notice()` returns one line when a legacy in-repo directory still holds
state files while the resolved root is elsewhere; `session_start` prints it once per session. It
**names the resolved root**, which is the piece nobody can guess. Silent → obvious, for the price of
one line.

### 2. Ship the migration (`plugin/bin/state_migrate.py`)

Dry-run by default, `--apply` to act. It **concatenates** rather than moves — records that arrived
at the legacy path after a hand copy must survive, and so must records already at the destination —
**de-duplicates** identical lines so re-running is safe and a partial hand migration merges instead
of doubling, **validates** every line parses before removing anything, and leaves the committed
`config.json` alone. For the single-document files (`schedule-state.json`, `pr-watch-queue.json`)
concatenation is meaningless, so the newer copy wins.

It is in `plugin/bin/` because ADR 0072's rule says so: a shipped artifact tells users to run it, so
it ships.

### 3. Name what the audit log is

**A bounded rolling window, not durable history.** The alternative — archiving the trimmed head —
is unbounded growth wearing a different name, which is the defect rotation was introduced to fix.
So the contract stays, and two things change so it stops being a trap:

- **The bounds are configurable** (`logs.max_bytes`, `logs.keep_bytes`; defaults unchanged). A user
  who needs the history to last raises them, deliberately, having read what they cost.
- **A rotation announces itself** — a diagnostics event recording how many bytes of the oldest
  records were discarded, `force=True` so it is written even with diagnostics off. This repo's own
  doctrine (ADR 0058) says a silent event is indistinguishable from one that never happened; that
  applies to deliberate data loss more than to anything else.

Durable evidence remains the **diagnostics bundle** — a deliberate snapshot, which is what the
field reports this project runs on are actually built from.

## Consequences

- **The migration is a supported operation** instead of a guess, and the guess now announces itself
  when someone makes it anyway.
- **The rolling-window contract is stated rather than implied.** A user who wants durable history
  has two supported answers (raise the bound, or bundle) instead of discovering the loss later.
- **Rotation becomes visible in diagnostics**, so a bundle now shows what was dropped and when.
- **`state_migrate.py` is the fifth shipped CLI**, and the PreToolUse chain, the config surface and
  the CLI surface have all grown this week. Worth a consolidation pass before adding a sixth.
- **The migration is not automatic.** Running it is the user's decision — moving someone's data
  without being asked is precisely the class of behaviour ADR 0072 exists to stop.
