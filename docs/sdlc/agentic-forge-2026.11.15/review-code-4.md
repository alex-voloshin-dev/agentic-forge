---
type: review
feature: agentic-forge-2026.11.15
target: master..fix/gate-local-tools
iteration: 4
verdict: approve
findings: []
---

# Review, round 4: the commit gate trusts no tracked tool (ADR 0115)

Diff: branch `fix/gate-local-tools` against master 2042bb3 (v2026.11.14).
Decision: proceed (verdict approve, gate green). Round 4 exceeds the N = 3 budget: round 3 returned `escalate` on
Windows-only findings, and the owner chose one more round.

## Rounds

- Round 1: reviewer changes (docs overstated what changes; a dropped variable can turn a gate into a block, not a
  fail-open; per-run recomputation; notice repetition; 3.9 coverage; a mirror test). security-engineer approve with
  minors (name rule gaps, on-disk credentials, case-insensitive filesystems, run by absolute path). codex changes
  (npm rebuilds `PATH` from `node_modules/.bin`). All applied.
- Round 2: reviewer and security changes, codex changes: `shutil.which` searches the current directory on Windows,
  and an unresolved bare name or an empty `PATH` could run a program from the repository. Fixed with an own lookup
  over absolute entries, fail open when nothing resolves, and a safe default `PATH`.
- Round 3: all three changes, Windows-only: git's forward-slash toplevel compared as a string, and `.bat`/`.cmd`
  resolution letting `cmd.exe` interpret repository file names; plus an auth-pattern false positive and the python3
  fallback using the original `PATH`. Escalated to the owner, who approved round 4.
- Round 4: reviewer approve (one nit applied after: the HTTP status pattern needs whitespace), security-engineer
  approve (one pre-existing minor recorded as a limit: `gate_scope` runs git by bare name), codex approve.

## Verdicts

- reviewer: approve. security-engineer: approve. external lens (codex): approve, no findings.
- QA: 175 cases in `tests/test_gate_tool_trust.py`, the hook end to end on 3.9, `dev/hook_smoke.py` untrusted-tool
  commit; full suite 6,139 passed, 96 % coverage.
