# 0063 — Autonomous PR watch: merge gate, comment triage, conflict resolve

Status: Accepted — **implemented**. Extends [0044](0044-pr-watcher.md) / [0045](0045-pr-watcher-1b.md)
(PR watcher core) and **reverses one of their invariants** (see below). Uses the settings layer
([0041](0041-plugin-settings.md) / [0049](0049-user-level-config.md)), the guardrail hooks
([0019](0019-l4-guardrails.md)), and the bounded review loop
([review-loop.md](../../../plugin/patterns/review-loop.md)).

## Context

The PR watcher (0044/0045) parses a PR's review state and drives a bounded fix loop over review
threads. It stops there **by design**: it never merges, and the maintainer drove every PR to
completion by hand. The ask now is a watcher that carries a PR to *done* on its own:

1. monitoring starts **when the PR is created**, because an external GitHub reviewer (e.g. a codex
   app) posts its review shortly after open;
2. it re-checks every ~10 minutes and **merges** once the PR is green, comment-free, and conflict-free;
3. it **resolves conflicts** and updates the PR;
4. it **triages each comment** — a valid one becomes a fix (through the internal develop review
   loop), an invalid one is refuted — and then resolves the thread, updating docs / the PR
   description when the fix warrants it.

This is plugin capability, not automation of this repository: every identity and threshold below is
a **setting** a downstream repo fills in.

## Decision

### 1. The never-merge invariant is reversed — behind an opt-in gate

ADR 0044 §"Safety" and 0045 recorded: *"it never merges and never force-pushes … there is no
merge/force command builder here, by design."* Half of that is now intentionally undone:

- **`merge_argv(repo, number, method)` exists** and `run_watch` can merge.
- **`pr_watcher.auto_merge` defaults to `false`.** A published plugin must not start merging pull
  requests in every repo that installs it; the capability ships off and is enabled per repo.
- **`never force-push` remains absolute** — there is still no force builder, and none is planned.
  Conflict resolution merges the base *into* the branch and pushes fast-forward.
- `merge_method` is clamped to `{rebase, squash, merge}` **in the library**, not only in the schema:
  the method reaches argv as `--<method>`, so an unvalidated string would be flag injection.

### 2. The merge gate is a pure, tested function — not prose in a skill

`merge_readiness(state, *, bot)` returns a `MergeDecision(ready, reasons)`. It blocks unless **all**
hold:

| Condition | Blocking reason when unmet |
| --- | --- |
| not a draft | `draft PR` |
| check rollup is `SUCCESS` | `checks: PENDING` / `FAILURE` / `NONE` |
| no unresolved actionable threads | `N unresolved review thread(s)` |
| `mergeable == MERGEABLE` | `mergeable: CONFLICTING` / `UNKNOWN` |

Two deliberate readings of the ask:

- **"No comments" means no *unresolved actionable* threads**, reusing `actionable_threads`. A PR
  whose comments were all triaged and resolved is mergeable; the literal reading ("zero comments
  ever") would make any reviewed PR permanently unmergeable.
- **"Green builds" requires checks to exist.** A rollup of `NONE` (no CI at all) **blocks**, with
  that as the stated reason. No builds is not the same as green builds, and auto-merging into a
  repo with no CI is exactly where an irreversible action should refuse.

### 3. The external-review window is the poll interval — no separate wait

"Merge when there are no comments" plus "the reviewer comments *after* open" looks like it merges
before the review lands. The first design answered that with an explicit `await_reviewers` list plus
a timeout. **That machinery was dropped** in favour of the structure already present:

- **The first pass cannot merge.** Right after `gh pr create` the checks are `PENDING`, so the gate
  is shut. The earliest a merge can happen is the *next* poll — one full `poll_seconds` (default
  600) later. That interval is the reviewer's window.
- **A `NONE` rollup blocks**, so a repo with no CI never falls through this reasoning.

The tempting wrong version of this is "the build duration is the wait". It is not: this repository's
own static gate finishes in ~27 seconds, so a watcher pacing on build time would open the gate before
any reviewer looked. The guarantee comes from the *poll cadence*, which makes `poll_seconds`
load-bearing for review latency and not merely a cadence knob — **shortening it shortens the window**,
and that trade-off is documented where the setting is.

Dropping the wait also removes the failure mode it introduced: a named reviewer that stops posting
(app uninstalled, integration broken) would otherwise block every merge until its timeout, on every
PR. No configured identity means nothing to go stale.

### 4. Never merge in the pass that pushed

`run_watch` merges only when the pass fixed nothing and pushed nothing. A fix push invalidates the
green checks it was gated on — the new commit has not been tested yet. So the merge waits for the
next poll, by which time CI has re-run. This is enforced in the tested core, not left to the caller.

### 5. Comment triage routes through the existing engine

A valid comment is a code change, so it goes where code changes go: the `software-engineer` role
under the bounded review loop (`develop`'s machinery), not an ad-hoc patch. An invalid one gets a
reasoned refutation and the thread is left **open** — the watcher never resolves a dispute in its own
favour. After a fix, the skill updates the docs and the PR description when behaviour changed, per
the repository's documentation discipline; a stale PR body after an accepted review comment is a
documented failure of this workflow, not an afterthought.

### 6. Watching starts at PR creation via a hook

A `PostToolUse` hook on `Bash` detects a `gh pr create` call and injects a reminder to start the
watch. A hook is the only mechanism that fires *automatically* on an action; the skill cannot
observe a command it did not run. It is **observability-only — it never blocks** (always exits 0,
like `audit_log.py`) and it only *suggests*: it does not spawn a watcher behind the user's back,
because auto-merge is downstream of it.

## Alternatives considered

- **Keep the never-merge invariant (0044/0045 status quo):** rejected — the maintainer asked for the
  watcher to carry a PR to done. The invariant was a Stage-1 conservatism, not a permanent law; the
  replacement rails (opt-in, pure gate, no-merge-after-push, timeout-bounded review wait) are what
  make the reversal safe to record rather than silently drop.
- **Auto-merge on by default:** rejected — an irreversible outward action in every repo that installs
  the plugin. Off by default, one setting to enable.
- **Trust `mergeStateStatus == CLEAN` alone:** rejected — it folds several conditions into one opaque
  value, so the watch report could not say *why* a PR is not mergeable, which is most of its value.
- **An `await_reviewers` list + `review_timeout_seconds` (the first cut of §3):** rejected as
  unnecessary machinery — the poll interval already provides the window, while the setting pair added
  a per-repo identity to keep current and a new way to wedge (a stale login blocking every merge
  until its timeout). Two settings and a code path removed.
- **Poll on the checks' expected duration (the existing pr-watch pacing):** kept for interactive
  babysitting; the autonomous mode uses the requested fixed `poll_seconds` (default 600) because it
  runs unattended and a predictable cadence is easier to reason about in an audit trail.
- **Have the hook start the watcher itself:** rejected — a hook that silently launches an agent which
  can merge is exactly the kind of invisible authority a guardrail layer must not take.

## Consequences

- The watcher can now complete a PR unattended where `auto_merge` is on: triage → fix → push → wait
  for CI → merge. Where it is off (the default), behaviour is unchanged from 0044/0045.
- ADR 0044/0045's "never merges" line is **no longer true** and is annotated there; "never
  force-pushes" still is, and is now the only absolute.
- A repo with no CI does not merge silently — the gate blocks with `checks: NONE` as the reason.
- `poll_seconds` now carries two meanings: the re-check cadence **and** the window an external
  reviewer gets before the gate can open. Documented at the setting, because the second is not
  obvious from the name.
- New settings: `auto_merge`, `merge_method`, `poll_seconds`. All optional with defaults; existing
  configs stay valid.
