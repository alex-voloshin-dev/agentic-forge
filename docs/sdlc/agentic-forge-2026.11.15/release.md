---
type: release
feature: agentic-forge-2026.11.15
status: final
version: 2026.11.15
date: 2026-11-25
changelog:
  - "The commit gate no longer takes its program from, or puts on PATH, a project-local bin directory that git tracks; a package-script gate beside one is skipped (ADR 0115)."
  - "The gate runs its program by absolute path from absolute PATH entries only (.exe/.com only on Windows, except the fixed npm run lint argv); nothing resolved means fail open with no process."
  - "The gate subprocess gets no credential-named environment variables; a block names the withheld names."
breaking: []
---
# Release 2026.11.15

One hardening change: a board known limit since ADR 0101 ("a tracked `.venv/bin/ruff` runs as it did; a follow-up ADR
is planned"). ADR 0115 records the decision.

## What changed

- **A tracked tool directory is not trusted.** The commit gate is a `PreToolUse` hook, so it runs when a session
  attempts `git commit`/`git push`, before the user is asked. Since ADR 0081 it took its program from
  `node_modules/.bin`, `.venv/bin`, `venv/bin`, `.venv/Scripts` or `venv/Scripts` and put them on `PATH`. Now such a
  directory is used only when git tracks nothing under it, checked from git's toplevel down with exact spelling. An
  untracked or gitignored install still resolves, as in ADR 0081's field case.
- **A package-script gate beside an untrusted `node_modules/.bin` is skipped** (fail open with a notice), because
  npm, pnpm and yarn put those directories back on `PATH` themselves.
- **The program runs by absolute path** from absolute `PATH` entries only; empty and relative entries are dropped and
  `PATH` is never left empty. On Windows only `.exe`/`.com` run, except the fixed `npm run lint` argv. If nothing
  resolves, the gate fails open without starting a process.
- **No credential-named environment variables reach the gate.** Names with TOKEN, SECRET, PASSWORD, CREDENTIAL, AUTH,
  API KEY and similar words are withheld. When a gate blocks on what looks like an authentication failure, the model is
  told which names were withheld (never values); the operator's notice always names them.
- **Unchanged by design:** the project's declared checks (`dev/validate.py`, `npm run lint`, a ruff config) still run,
  as the project's code under the workspace trust the user granted. `test_gate.skip` is the protection for an
  untrusted repository.

## How it was checked

- Four review rounds (reviewer, security-engineer, external lens codex); round 4 was an owner-approved verification
  round after round 3 escalated on Windows-only findings. Final: all three approve. Details in `review-code-4.md`.
- Tests: 175 cases in `tests/test_gate_tool_trust.py`, including real git repositories, a real npm run, a planted
  tool that must never execute, Windows path and extension handling via `PureWindowsPath` and a patched platform
  flag, and the hook end to end under Python 3.9. `dev/hook_smoke.py` gained an untrusted-tool commit, so the
  `hooks-py39` CI job exercises the new code.
- Tier-0: `dev/validate.py`, `ruff`, `mypy`, the full pytest suite (6,139 passed, 96 % coverage), `dev/hook_smoke.py`
  under Python 3.9.25.

## Not validated

No skill description or role changed. Tier-1, Tier-1b, Tier-2 and Tier-3 were not run. No Windows host run: the
Windows behaviour is tested on Linux by simulation.

## Known limits (ADR 0115)

- Credentials on disk (`~/.aws`, `~/.config/gh`, `~/.npmrc`, `~/.git-credentials`, SSH keys) and in agents or
  keyrings remain reachable by the project's own checks; the name rule reads names, not values.
- The narrowing's own git reads (`gate_scope`) still run git by its bare name; on Windows a follow-up resolves it
  absolutely.
- A repository that deliberately vendors `node_modules/.bin` now gates from `PATH` or skips its npm gate, with a notice.
