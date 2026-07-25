# 0059 — Commit-gate unrunnable-detection precision + bundle robustness (0058 hotfix)

Status: Accepted — **implemented** (hotfix `2026.7.4`). Corrects a defect introduced in
[0058](0058-field-diagnostics-fidelity.md); surfaced by the pre-publication deep review.

## Context

ADR 0058 made the commit-gate **fail open** when the gate "can't run" (a missing lint script /
uninstalled linter) via `guardrails.gate_unrunnable(output)`, a case-insensitive substring match on
the gate's combined output. The signature list included a **bare `"not found"`** (and `"no such
file"`). The pre-publication deep review found these are far too broad: `"not found"` appears in
*genuine* gate failures, so a real failing gate was silently downgraded to fail-open and the commit
allowed — defeating the gate. Confirmed false-positives (all made `gate_unrunnable` return `True`):

- **This repo's own gate.** `dev/validate.py` → `skill_contract.py` emits `SKILL.md not found` on a
  real structural failure, so a genuine Tier-0 failure would fail open.
- `pytest` `fixture 'x' not found`; `eslint` `'y' not found in './m'`; an HTTP test asserting
  `404 Not Found`; `gcc` `foo.h: No such file or directory` — all genuine failures.

The same review found two smaller defects in the 0058 diagnostics code:

- `commit_gate` concatenated `stdout + stderr` with **no separator**, so a signature could be
  spuriously formed or destroyed across the join boundary.
- `diag_bundle._read_transcript_sessions` guarded only `OSError`, but `open(encoding="utf-8")`
  raises `UnicodeDecodeError` (a `ValueError`) on a bad byte — escaping the best-effort contract and
  crashing the whole bundle build.

## Decision

1. **Tighten the unrunnable signatures.** Drop the bare `"not found"` and `"no such file"` from
   `_GATE_UNRUNNABLE`; keep only specific environment signatures: `missing script`,
   `command not found`, `can't open file`, `modulenotfounderror`, `is not recognized`,
   `executable not found`. These match "the gate couldn't start", not "the code failed the gate".

2. **Catch the shell's own not-found by exit code, not substring.** A shell that can't find/execute
   the command exits **127 / 126**. `commit_gate` now fails open when `returncode in
   guardrails.GATE_UNRUNNABLE_EXIT_CODES` (`{126, 127}`) **or** the tightened signature matches — so
   `bash: X: No such file or directory` (a real "couldn't run") is caught by its exit code without a
   broad substring that also matches genuine failures.

3. **Separate the streams.** `commit_gate` joins `stdout` and `stderr` with `"\n"` before matching.

4. **Make the transcript read truly best-effort.** `_read_transcript_sessions` opens with
   `errors="replace"`, so one bad byte can't crash the bundle.

The fail-open direction is unchanged (a guardrail that can't run must not block); this ADR only
makes "can't run" **precise**, so genuine failures block again.

## Alternatives considered

- **Keep `"not found"` but anchor it** (e.g. require `": not found"` adjacent to the gate binary):
  rejected — still brittle across shells/tools; the exit-code path (127/126) is the robust, portable
  signal for the shell's own not-found, and the specific substrings cover npm/python/Windows.
- **Parse each tool's exit taxonomy per stack:** rejected as over-engineered (same reasoning as
  0058); exit code + a short specific list is enough.

## Consequences

- A genuine gate failure whose output contains `not found` / `no such file` **blocks again** (the
  0058 regression is fixed); a real missing-script / uninstalled-linter / shell-not-found still fails
  open and records an `anomaly`.
- The bundle build no longer crashes on a non-UTF-8 transcript byte.
- Covered by regression tests: `gate_unrunnable` false-on-real-failure cases (SKILL.md/pytest/eslint/
  HTTP/gcc), the exit-code fail-open path, and a bad-UTF-8 transcript. Ships in `2026.7.4`.
