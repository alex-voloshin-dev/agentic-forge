---
type: release
feature: agentic-forge-2026.11.3
status: final
version: 2026.11.3
date: 2026-11-03
changelog:
  - "Security: `pr_watcher` settings are honoured from the user-level config; a repo can only switch `enabled`, `auto_merge` or `auto_watch` off."
  - "Security: each scheduled pass runs in a detached worktree of its own under the user-level state root, and the operator's tree is not involved."
  - "Security: the fixer session loads no settings and is confined by the CLI's flags to the tree it works in, with no shell or web tool."
  - "Security: only threads from people with write access, or from reviewer apps listed in `pr_watcher.trusted_reviewers`, reach the fixer."
  - "Security: merges are pinned to the commit the gate read, and committed queue and schedule files are no longer read."
  - "Added: `pr_watcher.auto_merge` also takes a list of repos, and `pr_watcher.trusted_reviewers` lists reviewer apps."
  - "Fixed: a failed `git commit` no longer claims a fix, and a fix is pushed before the reply and the resolve."
  - "Fixed: a failed pass fails the sweep's job, and `--health` says why the watcher is off or what it dropped."
breaking:
  - "`pr_watcher` values set to anything but off in a repo's config are ignored with a warning. Move them to ~/.agentic-forge/config.json."
  - "A reviewer app's threads reach the fixer only if it is listed in `pr_watcher.trusted_reviewers`; other threads hold the merge gate until a person resolves them."
  - "A fixer authenticated through an `env` in a `settings.json` stops working. Use the CLI's login or the clock's environment."
  - "A PR queued at the legacy in-repo path is not carried over, every job with history there is due once, and a PR outside the checkout's `origin` gets no fix pass."
---
# Release 2026.11.3

A security release for the scheduled PR watcher, which runs unattended with the operator's GitHub credentials. It is
off by default, so this affects operators who turned it on, and a repository that turned it on for them.

## Upgrade notes

Upgrade from any earlier version. Through 2026.11.2 a repository's config could turn on the watcher and decide what it
acted on and whether it merged. A pull request's tree could influence later passes and run code in the fixer session,
and any account able to comment could drive that session.

- **Breaking:** if you set `pr_watcher` values per repo, move them to `~/.agentic-forge/config.json`. A repo can now
  only switch `enabled`, `auto_merge` or `auto_watch` off. For per-repo merging, set `auto_merge` to a list of repos.
- **Breaking:** if you rely on a reviewer app, list it in `pr_watcher.trusted_reviewers`. Otherwise its threads get no
  fix and hold the merge gate until a person resolves them.
- **Breaking:** a fixer authenticated through an `env` in a `settings.json` stops working. Use the CLI's login or the
  clock's environment.
- **Breaking:** a PR queued at the legacy in-repo path is not carried over, and every job with history there is due
  once. A PR outside the checkout's `origin` gets no fix pass, and an `origin` using an SSH host alias counts as outside.
- **Do this once:** put the clock's checkout back on its branch. The old driver left it on the last PR.
- `--health` now turns red on any thread left undetermined, including a usage limit.
- The fixer's tool calls no longer reach the audit log, since it loads no hooks.

## Measured

- Tier-0: `dev/validate.py`, ruff and mypy clean; 2983 tests pass, coverage 96.20%. `dev/hook_smoke.py` passes on Python
  3.12.3 and on real Python 3.9.25. CI's Tier-0 and Python 3.9 hook jobs are required before merge.
- Real Claude Code CLI 2.1.317: with a local stub in place of the API, and a scripted model that obeys an injection, the
  fixer's flags kept out the tree's hooks, MCP servers, `env`, `apiKeyHelper` and memory files, and reads and writes
  outside the tree including `~/.claude`. On a real login, one short session edited inside the tree and was refused
  outside it, with these flags.
- Real GitHub, read-only: the `authorAssociation`, `headRefOid`, `__typename` and `latestOpinionatedReviews` fields, the
  permission endpoint and the `refs/pull/N/head` fetch all answer as the code expects.
- Reviews: three rounds with reviewer, security-engineer and external codex lenses, a QA round on the upgrade from
  2026.11.2, then a fourth check of the last batch, past the usual budget of three. **The last fixes did not get another
  full round.** The reviewer's and the security review's final findings, and two from codex on that batch, had only the
  unit gate and, for the batch before the last two fixes, one more codex pass that raised those two.

## Not validated

- **Writes to real GitHub: push, reply, resolve, merge, and `--match-head-commit` refusing a moved head.** Every such
  scenario ran against a fake `gh` and a local bare origin, so run the runbook's wiring step on a repo of your own first.
- The trust check and the merge gate have not been driven through a real pass, though their queries were read for real.
- A real model's behaviour under injection: the stub measured what the harness allows, not how often a model complies.
- **Tier-1, Tier-1b, Tier-2 and Tier-3 were not run.** No description or role changed. The `pr-watch` skill's body
  changed, and it is off the listing.
- Real cron, macOS, Windows, git-lfs, and any CLI version but 2.1.317. The plugin pins no CLI version, so the
  confinement holds as measured on that one, and CI does not run the real-CLI tests.

## Known limits and follow-ups

Recorded in ADR 0103. A trusted thread can still carry an injected request, so a fixer can edit files in its tree and
have them pushed; the tree's commit subjects reach the model. A repo's `false` is read from the clock's own checkout, so
it does not bind a repo merged by slug or a commit not yet pulled. The next releases replace the skills' inline
`python -c` calls with a shipped script, and bring a narrower commit gate.
