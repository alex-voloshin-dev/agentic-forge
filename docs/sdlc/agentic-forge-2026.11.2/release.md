---
type: release
feature: agentic-forge-2026.11.2
status: final
version: 2026.11.2
date: 2026-11-03
changelog:
  - "Security: `state.in_repo` is honoured only from the user-level config; a value in a repo file is ignored with a warning."
  - "Security: every plugin state write goes through `agentic_forge.state_io`, which does not follow a symlink, and readers treat a state file behind a link as absent."
  - "Security: a knowledge vault must resolve inside the repo unless the user-level `knowledge.allow_external_vault` is set; vault writes refuse a linked file and name the path."
  - "Security: session-start notices no longer repeat text a repo chose."
  - "Fixed: the legacy-state notice can be followed to its end, and `state_migrate` follows no link and names what it leaves."
  - "Fixed: `run_scheduled.py` exits non-zero when it cannot save its job state."
  - "Fixed: a refused archive leaves the log untrimmed, and a failed archive says so."
  - "Fixed: a vault note that is not UTF-8 or has unusable frontmatter costs that note only."
breaking:
  - "A repo-level `state.in_repo` is now ignored with a warning. Set it in ~/.agentic-forge/config.json, or run the migration the session-start notice gives."
  - "A vault that resolves outside the repo needs `knowledge.allow_external_vault: true` in ~/.agentic-forge/config.json. Until then its writes are refused and its reads act as an empty vault."
---
# Release 2026.11.2

A security release for the plugin's state and knowledge-vault writes, found during the review of feedback
from the `agentic-forge-feedback` topic.

## Upgrade notes

Upgrade from any earlier version. Through 2026.11.1 a repository's committed content could make the plugin's
hooks and vault writes modify files outside the checkout, with the operator's permissions, and could bring
titles from outside into the session context. Now the operator decides where state and notes may live.

- **Breaking:** a repo-level `state.in_repo` is ignored with a warning. New state goes to the user-level root,
  and the session-start notice gives the command that merges what is already in the repo.
- **Breaking:** if you keep a knowledge vault outside the repo and reach it by a link, set
  `knowledge.allow_external_vault: true` in `~/.agentic-forge/config.json`. A link that stays inside the repo keeps
  working. A linked worktree counts as its own repo here.
- A title or tag in a vault note that is not a string, such as `title: 2024`, is now ignored.
- **Recommended until the next release:** do not run the scheduled PR watcher on checkouts you do not fully trust,
  and keep `pr_watcher.auto_merge` off. Hardening of those settings follows.

## Measured

- Tier-0: `dev/validate.py`, ruff and mypy clean; 2573 tests pass, coverage 96.17%.
- `dev/hook_smoke.py` passes on Python 3.12.3 and on real Python 3.9.25. On 3.9, 258 vault, state, migration and
  import-safety tests pass and 34 are skipped; the image has no git. The CI Tier-0 and Python 3.9 hook jobs are also
  required before merge.
- The reported scenario was replayed against the real hook: on 2026.11.1 the target files change, on this release they
  do not.
- Three review rounds, reviewer, security-engineer and external codex, plus a QA round on the upgrade path from
  2026.11.1. In the final round the reviewer approved and the security review found no blocker or major in this
  change. The small fixes from that round had the unit gate and an external codex pass, not another full round.

## Not validated

- **Tier-1, Tier-1b, Tier-2 and Tier-3 were not run.** No `SKILL.md`, role or description changed.
- macOS, Windows and a real case-insensitive filesystem.
- A live Claude Code session: hooks ran as real processes fed with payloads, not through `hooks.json`.

## Known limits and follow-ups

Recorded in ADR 0102. The next releases address the skills' inline `python -c` calls, which resolve modules from the
current directory first and may not find the module on a plugin-only install, and repo-settable `pr_watcher` settings.
