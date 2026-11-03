---
type: release
feature: agentic-forge-2026.11.1
status: final
version: 2026.11.1
date: 2026-11-03
changelog:
  - "Security: `external_reviewer.command`, `isolated`, `model` and `effort` are honoured only from the built-in default or the user-level config; a repository's config could previously cause a program it chose to run on the operator's machine, and the verdict could be forged (ADR 0100). Affects released versions through 2026.9.5."
  - "Security: `review()` runs only the configured reviewer and honours `external_reviewer.enabled`; a user-level opt-out holds against a repo, and a clear `enabled: false` survives its file being dropped."
  - "Security: operators running the reviewer on repos with outside contributions should set `external_reviewer.isolated: true` (recommendation; see docs/configuration.md)."
  - "Added: opt-in reviewer isolation with a capability check and no fallback to a non-isolated run, and optional `model` and `effort` settings."
  - "Added: structured skip reasons from `review_outcome`, printed by the CLI; a skip never reads as approval."
  - "Changed: any review-shaped `changes` decides the verdict; finding fields are sanitised and capped; `--target` and `--out` refuse symlinks; a relative `--command` resolves against the caller's cwd; the reviewer's stdin is closed."
  - "Changed: the post-PR notice says /pr-watch is a manual command for the user and what an agent can do instead."
  - "Fixed: `settings.resolve` does not raise on binary, deeply nested or oversized config; schema warnings no longer echo file content; `dev/hook_smoke.py` no longer accumulates a shared budget counter; `benchmark.py` is clean under mypy 2.4.1."
breaking:
  - "A repo-level `external_reviewer.command` is now ignored with a warning. Each operator who needs another reviewer sets it in ~/.agentic-forge/config.json or passes --command."
  - "`review()` refuses a `command` other than the configured one, returning None."
---
# Release 2026.11.1

A security release for the external reviewer, found while working through feedback on the new
`agentic-forge-feedback` topic.

## Upgrade notes

Upgrade from any earlier version. The external reviewer is on by default, and through 2026.9.5 a
repository's `.agentic-forge/config.json` could cause a program it chose to run on the operator's machine
during a review, and could forge the review's verdict. Now the operator chooses the program.

- **Breaking:** a repo-level `external_reviewer.command` is ignored with a warning. Set it in
  `~/.agentic-forge/config.json` or pass `--command`.
- **Breaking:** `review()` refuses a `command` other than the configured one.
- **Recommended:** set `external_reviewer.isolated: true` at user level if you run the reviewer on repos
  that take outside contributions. See `docs/configuration.md`.

## Measured

- Tier-0: `dev/validate.py`, ruff and mypy clean; 2324 tests pass, coverage 95.8%; `dev/hook_smoke.py` passes
  on Python 3.12. CI's Tier-0 job and its Python 3.9 hook job are the proof for 3.11 and 3.9.
- Real codex-cli 0.164.0, run with `isolated: true`: `--ignore-user-config` and `--ephemeral` are accepted,
  and a parseable verdict came back.
- Three review rounds: reviewer, security-engineer and external codex lenses, plus a QA round. The
  final security round approved. Findings of the final round were fixed, and those fixes had the unit gate
  only, not another review round.

## Not validated

- **Tier-1, Tier-1b, Tier-2 and Tier-3 were not run.** No `SKILL.md`, role or description changed (user's
  decision for this release).
- `external_reviewer.effort`: whether codex honours `model_reasoning_effort` is untested.
- Real `go`, `rubocop` and `cargo` are not relevant here: the commit-gate change is not in this release.
- macOS and Windows behaviour of the path checks.

## Known limits and follow-ups

Recorded in ADR 0100: skills that call the library inline could be shadowed by repository files on
`sys.path` (needs `SKILL.md` edits and evals); the prompt still travels in argv, so a very large target or one
with a NUL is skipped; a reply's total size is uncapped, so a hostile reply can take about a minute to parse;
`review()` from a subdirectory does not see the repo's config.
