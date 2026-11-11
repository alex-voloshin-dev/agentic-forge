---
type: release
feature: agentic-forge-2026.11.7
status: final
version: 2026.11.7
date: 2026-11-11
changelog:
  - "Security: the read-only roles (reviewer, security-engineer, grader, architect) are held to their tool allowlists by a PreToolUse hook, in every permission mode."
  - "Security: a review lens runs one read-only git command, rewritten into a hardened form so what runs is what was checked."
  - "Security: architect writes Markdown only under docs/ of the session's own working tree."
  - "Security: the audit log masks *_PWD/*_CRED names, the value after secret flags, sshpass -p and the MySQL clients' -p<value>."
breaking:
  - "A review lens no longer runs tests, linters, docker or scripts; the orchestrating skill runs them."
  - "architect can no longer write outside docs/, into hidden directories, or to agent instruction files and skill definitions."
---
# Release 2026.11.7

A security release. The `reviewer` and `security-engineer` subagents read code that may come from someone else, and
the plugin treated them as read-only because their frontmatter said `tools: Read, Grep, Glob, Bash(git diff:*)`.
Claude Code does not restrict a `Bash(...)` specifier in a plugin agent's tool list: the agent gets Bash. Outside
`default` permission mode, and in `bypassPermissions` above all, only the agent's prompt kept a lens from running what
a reviewed change asked it to. This release holds those roles with a hook. It also widens the audit log's redaction
of secrets. Advisory: see the GitHub Security Advisory published with this release.

## Upgrade notes

Upgrade from any earlier version, and restart running sessions so they load the new hooks.

- **A review lens no longer runs tests, linters, docker or scripts.** It may run one read-only git command per call
  (diff, show, log, status, blame, ls-files, ls-tree, rev-parse, merge-base, cat-file, grep, shortlog, describe), with
  no shell operators, and verifies by reading. If your prompts asked a lens to run something, run it in the session
  that spawned the lens; `code-review` and `deep-review` already do.
- The git command a lens runs is rewritten into a hardened form: each word quoted, the external diff, textconv, pager,
  hooks, fsmonitor, signature display, gpg programs and nested submodule diffs turned off, the checkout's attributes
  ignored on git 2.41 and later, and git's redirecting environment variables cleared. The transcript shows the long
  command; that is expected.
- **`architect` writes Markdown only under `docs/`** of the session's own working tree (main checkout or a linked
  worktree), outside hidden directories, agent instruction files (`CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`,
  `GEMINI.md`) and `SKILL.md`. Today's skills write only `docs/sdlc/<slug>/`, so nothing in the plugin changes.
- **Audit log:** logs written before this release keep what they hold. If a session passed a credential inline,
  scrub `audit.jsonl` and its `archive/` under `~/.agentic-forge/state/<repo>-<hash>/`.

## Measured

- Tier-0: `dev/validate.py` clean, listing 6910/6910 chars; ruff and mypy clean; about 4,470 tests pass, coverage
  95.5%; `dev/hook_smoke.py` passes on Python 3.12 and 3.9.25. The role-scope library is at 99% coverage.
- **Live, Claude Code 2.1.322, in `default` and `bypassPermissions`:** a `reviewer` subagent's `git log` ran in the
  rewritten form without a permission prompt; its `python3` and `git diff --output=…` were refused; no file was
  written. The main session was unaffected.
- **Tier-2, real model `claude-opus-4-8`, N = 5:** reviewer, security-engineer, architect and grader all 1.000.
- Execution tests run every reviewer-reported bypass on a real repository, under bash and under zsh with
  `extendedglob` and `magicequalsubst`. Each checks its trap fires on the raw command first, then shows the hook
  refuses it or the rewritten command does not fire it.
- Reviews: four rounds with a reviewer, a security engineer and the external codex lens, then a confirming pass the
  user approved after the third round escalated. Both internal lenses approve. The external lens's last findings on
  redaction edge cases are fixed or recorded as the best-effort limit below.

## Not validated

- Tier-1 and Tier-1b were not run: no skill description changed.
- Tier-2 for code-review and deep-review, and Tier-3, were not run. Their bodies changed by one paragraph each
  (verification by reading), and the roles they delegate to passed Tier-2.
- macOS (BSD `env -u`), Windows, git 2.44+ (`GIT_NO_LAZY_FETCH`), git below 2.41 beyond the unit tests.

## Known limits and follow-ups

Recorded in ADR 0106. A hook that cannot start fails open, as every Claude Code hook does. On git older than 2.41, a
clean filter the user's own config defines can still run when `.gitattributes` selects it. Read, Grep and Glob are not
confined, so a lens can read any file the user can. Markdown under `docs/` can still reach a later session through an
`@` import in `CLAUDE.md` or a project that runs its Markdown as tests. Audit-log redaction is a best effort over
text, not a shell parser.

Next in the queue: the dependency update the user approved, then the external reviewer's 128 KiB limit, the vault's
folder loading, the handoff readiness field and stack detection.
