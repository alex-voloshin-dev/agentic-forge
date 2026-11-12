---
type: review
feature: agentic-forge-2026.11.11
target: master..release-2026.11.11
iteration: 3
verdict: approve
findings: []
---
# Review, final round (decision: proceed, after a user-approved escalation)

The develop review loop over items 7 to 15 (ADR 0110) ran three rounds. Each round used four reviewers (one per
task, T1/T5/T6 combined), a security engineer and the external codex lens.

- **Round 1 (`changes`).** Majors fixed:
  - repository folder names reaching shell commands (artifact-home now prints shell-quoted commands, safe names
    only);
  - the merge gate judging the PR before earlier commands ran, and being switched off by `2>&1`;
  - pr-review's mention neutralising (now every `@`) and a symlinked `--out` directory;
  - amend mode editing the main checkout;
  - ux-design's second home;
  - `PRD.md` spelling.
- **Round 2 (reviewer and security `approve`; codex `changes`).** Fixed:
  - the GraphQL read inheriting `GH_HOST`;
  - amend's clean-start check;
  - security's minors (wrapped and compound merges, read-only allowlist, outbound host allowlist, `--out` into
    hidden directories, `\Z` anchors).
- **Round 3 (`changes`).** An uppercase URL scheme bypassed the host allowlist. Fixed, together with the last minors.
  The budget was spent, so the loop escalated. The user chose "apply the fixes, confirm, release".
- **Confirming checks (user-approved).** They found two more bypasses of the host allowlist, both pre-existing:
  - a non-PR URL selector with `-R`;
  - a nested checkout's remotes.

  Then insteadOf/pushurl effective URLs. All are fixed by one rule: every host gh could use (URL, `-R`, `GH_HOST`,
  every effective remote) must be github.com or the session's origin, else the gate fails open with a notice and
  asks nothing. The security engineer's final check approved.

QA added end-to-end tests that run every field repro through the shipped entry points; no defects. Gate:
`dev/validate.py`, pytest (96%), ruff, mypy and `dev/hook_smoke.py` on Python 3.9.25 all pass.
