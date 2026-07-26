---
type: release
feature: agentic-forge-2026.7.7
status: final
version: 2026.7.7
date: 2026-07-26
changelog:
  - "Fixed: the merge rails had NO production caller (ADR 0067) — merge_readiness, the no-merge-after-push rail and confirm_merged were never invoked, and pr_watcher_auto_merge was read by nothing, so the only merging path was model-followed prose. run_watch now recomputes the gate itself (the merge_decision parameter is gone) and requires an explicit auto_merge; dev/pr_watch.py wires the seams"
  - "Fixed: `escalate` did not stop the handoff — artifacts are written before the loop and `status` was inert, so a rejected artifact flowed downstream and Tier-3 scored the run green. handoff.is_handoff_ready is the shared rule; writers mark in-review, consumers refuse an unready artifact, the E2E checkpoint asserts readiness"
  - "Fixed: the watcher read its kill switch from inside its blast radius — <repo>/.agentic-forge/config.json is committed and was resolved AFTER `gh pr checkout`, so a PR could rewrite pr_watcher.bot or set auto_merge. Settings are now resolved before checkout and passed down as argv; auto_merge demands a real boolean"
  - "Fixed: the merge gate was blind to a CHANGES_REQUESTED review (which often carries no inline thread), a truncated >100 thread list, and a closed PR"
  - "Fixed: the Tier-1 parser missed its own founding case — ADR 0064 was written for a RUSSIAN prose reply, and its token cap counts ASCII runs. Added a non-Latin guard, rejection of negated mentions and of the model performing the request, an explicit decline vocabulary, rejection of ambiguity, and a minimum-valid-samples floor"
  - "Fixed: the PR-created hook missed its flagship shape — newlines were not separators, so `git push …\\ngh pr create …` never fired; and a FAILED create announced success because the URL was read from stderr"
  - "Fixed: none of the seven review loops persisted a review artifact, so ADR 0040's non-convergence scan could not fire for any of them"
  - "Added: tests/test_review_loop_shape.py pins the shared review-loop contract (Bash+Task, review_loop_decision, each skill's own KINDS key) — that contract had shipped broken twice, both times caught by a human sweep rather than a gate"
  - "Fixed: docs that were untrue — a fifth merge-gate condition in the changelog, the pr-watch skill still advertising the reversed never-merge invariant, leaked tool-call XML in extensions.md, the hook count, and review.passes documented as a loop budget no loop reads"
breaking: []
---

# Release 2026.7.7

A remediation release, and an argument for the method that produced it.

## What happened

Releases 2026.7.5 and 7.6 passed **the entire eval pyramid** — Tier-0, live Tier-1 (6/6 at
1.000/1.000), live Tier-2 (2/2), live Tier-3 (three scenarios). A six-lens adversarial deep review
of those releases then found **two blockers and a dozen majors**, each verified against source.

The gates were not broken. They check *behaviour*; these were defects of **wiring, contract and
truthfulness** — the classes a passing test suite is structurally unable to see.

**Three independent lenses converged on the headline finding:** the machinery for safely merging a
pull request — the gate, the never-merge-after-push rail, the merge confirmation — had **no
production caller at all**. `pr_watcher_auto_merge` was resolved into settings and read by nothing.
The only path that could merge a PR was a skill instructing a model to run `gh pr merge` over Bash,
where every rail was prose. The library was written, tested, documented as "enforced in the tested
core" — and connected to nothing.

The second blocker had the same shape: `escalate` was specified to stop a handoff, but each phase
writes its artifact *before* the loop and `status` was inert, so a rejected artifact flowed to the
next phase — and Tier-3 **scored such a run green**, because its checkpoints assert "exists and
validates", which is exactly the gate the loop had already failed.

## What changed

See `CHANGELOG.md` under `[2026.7.7]` and [ADR 0067](../../architecture/decisions/0067-deep-review-remediation.md)
for the full account. In brief: the library now recomputes the merge gate itself rather than
trusting a caller's assertion; the watcher resolves its own settings *before* checking out the branch
under review; `escalate` marks the artifact not-ready and consumers refuse it; the Tier-1 parser
gained the guards its founding case required; the hook matches the command shape it was built for;
the loops persist the review artifact the non-convergence scan needs; and a new test makes the shared
review-loop shape a gate instead of a convention.

## Verification

- **Tier-0**: `validate.py`, `pytest`, `ruff`, `mypy` — clean.
- **Tier-1 (live, runs = 5)**: all six touched skills **1.000 / 1.000**, with discarded calls down
  from **6.7% to 2.3%**. The improvement runs both ways: legitimate verbose answers that the previous
  parser threw away are counted again, while non-answers that it silently scored as votes are not.
  The same 1.000 now rests on cleaner data than before.
- **Tier-3 (live)**: `spine`, `product-inception` and `market-brief` all **PASS** under the stricter
  readiness checkpoint; the generated artifacts were inspected and do carry `status: approved`.

## Not verified

- The `escalate → in-review → checkpoint red` branch was **not** exercised live — no phase escalated
  during the run. It rests on unit tests (`is_handoff_ready` rejects `in-review`, unknown and missing
  statuses) and the checkpoint test.
- The autonomous PR watch still has **not** been driven against a real pull request end to end. That
  debt predates this release and survives it.

## Housekeeping

A stray `uv.lock` (224 KB) entered the tree during this work via a blanket `git add -A`. `uv` is only
an optional venv path in CONTRIBUTING — there is no `[tool.uv]`, no CI use, no lockfile discipline —
so it is removed and gitignored.

## Tag

`v2026.7.7` (annotated) on the merged master commit, created after the PR's rebase merge.
