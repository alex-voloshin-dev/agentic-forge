---
type: review
feature: agentic-forge-2026.11.12
target: master..fix/commit-gate-cwd
iteration: 5
verdict: approve
findings: []
---

# Review, final round: the commit gate follows the commit's directory (item 7, ADR 0111)

Diff: branch `fix/commit-gate-cwd` against master 7b014d6 (v2026.11.11).
Decision: proceed (verdict approve, gate green, QA green).

## History

- Round 1 (changes): a linked worktree of the same repository was trusted although its files may be
  a PR head; uncounted pushes in groups and subshells; a failing `cd` before `;`; `-C` resolved
  lexically. Rebuilt as an allowlist confined to the start directory's own work tree.
- Round 2 (changes): `CDPATH` exemption too wide; untracked and ignored content inside the work tree;
  the block hint for a moved commit.
- Round 3 (changes, budget N = 3 exhausted): the tracked check read the target as a glob. Escalated
  to the owner, who chose: fix, one more review round, then release.
- Round 4 (changes): the tracked check accepted a target that is itself an index entry (a tracked
  file replaced by a directory, an uninitialised submodule).
- Round 5: the tracked check requires a regular (non-gitlink) entry strictly beneath the target.

## Final verdicts

- reviewer: approve (round 4, all round-3 findings resolved; two doc nits fixed in round 5).
- security-engineer: approve (round 5 delta: both round-4 cases closed, `-z` parsing, prefix
  collisions, case and symlink handling, hardening of the split git read all checked).
- external lens (codex): approve, no findings (round 5, full diff).
- QA (qa-engineer): no defects; six end-to-end hook tests run the hook as Claude Code does, under
  the test interpreter and Python 3.9, and all six fail on master. `dev/hook_smoke.py` now runs a
  `cd .. && git commit` under 3.9 too.

## Accepted residuals (ADR 0111, Limits)

- A tracked directory passes whatever untracked files sit in it; the start directory has the same
  exposure. The gate is an accident guard, not a boundary against the model.
- A `cd` into a subdirectory with no gate, or with its own `test_gate.skip`, turns the gate off for a
  commit that records the whole index (reachable before in two calls).
- Shells set for physical `cd`, a `CDPATH` set only in the shell's rc files, and a stalled mount
  during `realpath` are outside what the hook can see or bound.
- Follow-ups, not fixed here: the merge gate's background-`cd` gap; `gate_scope._git` runs git by
  bare name.
