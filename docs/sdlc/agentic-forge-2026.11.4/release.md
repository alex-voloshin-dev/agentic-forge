---
type: release
feature: agentic-forge-2026.11.4
status: final
version: 2026.11.4
date: 2026-11-03
changelog:
  - "Changed: for a simple `git commit` or `git push` the commit gate reads what changes, and can only narrow what it did before."
  - "Changed: a gate block no longer tells the agent how to switch the gate off; the operator gets that step in a `systemMessage`."
  - "Security: a gate block is redacted before it reaches the model, and control characters in filenames are escaped."
breaking:
  - "A block's message to the model no longer names `test_gate.skip`. The operator still sees that step."
---
# Release 2026.11.4

The commit gate stops blocking on what a commit does not change. This answers a field report from a monorepo: an empty
commit from a package directory was blocked by every old `ruff check .` finding in that package.

## Upgrade notes

- For a simple `git commit`, with an optional single `git add` before it, or a simple `git push`, git now says what changes.
  Nothing changed skips the gate, and `ruff` gets only the changed lintable files. Touching a file with old findings still blocks.
- Any other command shape, or any doubt, runs the gate as before. That includes `git commit -m x && git push`, `cd x && git commit` and
  `git -C`. A block on such a shape says to run the command on its own.
- **A change committed from a repo root with no manifest stays ungated, as before.**
- `dev/validate.py`, `npm run lint`, `cargo clippy` and `rubocop` run whole whenever something changed.
- **Breaking:** the block text the model reads now says to fix the findings or ask you. You get the `test_gate.skip` step yourself, in a
  `systemMessage`.

## Measured

- Tier-0: `dev/validate.py`, ruff and mypy clean; 3257 tests pass, coverage 95.71%. `dev/hook_smoke.py` passes on Python 3.12, and on
  real Python 3.9.25 with git installed, including a narrowed commit. CI's Tier-0 and Python 3.9 jobs are required before merge.
- The field case on a fixture monorepo: empty, docs-only and clean-new-file commits from a package directory, and their pushes, in a plain
  repo and in linked worktrees, against the old hook. Master blocks each; this release allows each, and a bad file in the commit still blocks.
- Real zsh, bash and dash against the command matcher: no mismatch on the accepted shapes.
- Reviews: reviewer, security-engineer and external codex lenses, three rounds. **The last three fixes (a config above cwd, a deleted
  `__init__.py`, a heredoc close) had the unit gate only, not another review.**

## Not validated

- **Tier-1, Tier-1b, Tier-2 and Tier-3 were not run.** No `SKILL.md`, role or description changed.
- The reporter's real monorepo, real `go`, `rubocop` and `cargo` (fakes only), macOS and a case-insensitive filesystem.

## Known limits

Recorded in ADR 0101. Scoping is per file, not per line. A change can still create a finding in a file it does not touch, such as an import
order after a module moves. A sibling Go package that cwd imports is not gated when only it changed.
