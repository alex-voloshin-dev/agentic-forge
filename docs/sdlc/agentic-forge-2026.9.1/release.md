---
type: release
feature: agentic-forge-2026.9.1
status: final
version: 2026.9.1
date: 2026-09-11
changelog:
  - "Fixed: the remote-environment-dump rule is per segment, on command position (ADR 0081) — it was added after ADR 0054 and never adopted its command-word discipline, so `echo ssh; echo set` blocked: `ssh` matched from a `for … in` word list, an `echo` argument or a Python string literal, and `set` matched as `echo`'s own argument. Every ADR 0075 true positive still blocks, plus `docker compose exec app printenv` and a dump inside a quoted remote command string"
  - "Fixed: the macOS per-user temp tree (`/var/folders/<hash>/<hash>/…`, and under `/private`) is exempt from the recursive-delete and permissive-chmod target check — deleting one's own `mktemp -d` is cleanup, not an attack on a system directory. `/var`, `/var/folders` and `/var/folders/<x>` stay protected"
  - "Fixed: writes go through the new `diagnostics.state_file()` (ADR 0081) — four write sites used the READER's helper, so a legacy in-repo state directory kept receiving every later write and could never drain. A field bundle carried 18,765 audit records and 6 diagnostics written there over 19 days, after that repo had been migrated and verified clean"
  - "Fixed: the legacy-state notice moves from a SessionStart hook's stderr (which, on exit 0, reaches nobody) to `additionalContext` plus `systemMessage`"
  - "Fixed: the commit gate resolves its linter project-first — `node_modules/.bin`, `.venv/bin`, `venv/bin` at `cwd` and at the repo root — and hands the gate subprocess those directories on `PATH`, so a package script's own linter resolves too. 50 of 69 recorded fail-opens were one `ruff` that lived in a service virtualenv"
  - "Added: the first commit-gate fail-open of a session says one line to the operator through `systemMessage`, naming the gate that did not run and what to do about it (`diagnostics.once_per_session`)"
  - "Changed: a security block record carries `rule` and `evidence` — the command is capped at 500 characters and for 11 of 14 field records the matched text was past the cut, leaving nothing to diagnose"
  - "Changed: audit-log rotation archives the records it drops to `<state root>/archive/audit-<timestamp>.jsonl.gz` (new `logs.archives`, default 6; `0` restores discarding), and the notice states the span in DAYS and where the records went"
breaking: []
---

# Release 2026.9.1

The first release built from a **60-day** field bundle rather than a same-week one: 92 diagnostic
records, 311 audit sessions, one workstation, one polyglot monorepo, all on 2026.7.11. Everything
below was reproduced against that exact version's own `guardrails` module, with the controls
(`rm -rf /`, a pipe-to-shell) asserted first — and every one of the 14 recorded security blocks now
passes while those controls still fire.

## One rule had opted out of the discipline, and nobody noticed

ADR 0054 exists so that *text about* a dangerous command is never read as the command. The
environment-dump rule (ADR 0075) arrived after it as two raw-text regexes over the whole command
string, and that is enough to compose two harmless halves into a block:

```sh
echo ssh; echo set          # blocked on 2026.7.11
```

`ssh` matched the remote-exec half as an item of a `for … in` word list, and `set` matched the
bare-dump half **as an argument of `echo`**. The two field cases are exactly this: a capability
probe listing `az ssh scp sshpass psql`, and a `python3` heredoc whose *string literal* mentioned
the shape. The second one blocked the operator's analysis of the first, and the only way to run it
was to write the script to a file — the guardrail pushing someone around itself.

This is not a heredoc bug. ADR 0079 is right to keep an interpreter heredoc's body; the same text
blocks with no heredoc at all. The rule now requires the remote wrapper to be a segment's command
word and the dump to be that command's own last word.

## The state directory was feeding itself

ADR 0072's rule — writes to the state root, reads may fall back — lived only in a docstring, and
four write sites called the reader's helper. Once a legacy in-repo file existed, every later write
went back into the repository. The bundle carries 18,765 audit records and 6 diagnostics written
there over 19 days, *after* that repo had been migrated and the migration verified clean. None of
those 6 diagnostics exist in the user-level log at all.

ADR 0080's notice for exactly this case did fire — into stderr, from a SessionStart hook that exits
0. Two months later the orphan was still there.

## The safety feature had not run since July

50 of 69 fail-opens are one `FileNotFoundError: 'ruff'`. Failing open on a broken toolchain is
correct and unchanged; executing a bare tool name the way nothing in that project does, and then
telling only a log file about it, was not.

The bundle also reads the gate's 11 `block` records as the same problem still open. They are not:
all ten `npm run lint` blocks predate the reporter's upgrade to 2026.7.10, and the single one after
it is a genuine eslint failure. ADR 0058/0059 held — this release says so with the dates.

## What this release deliberately does not do

27 days of audit log show **183 `Agent` calls against 3 `Skill` calls**: the subagent roles carried
a six-week feature in a per-PR implement → review → security loop, while `develop` — the skill for
exactly that loop — fired once. That is the bundle's strongest signal and it is recorded, not
acted on. The audit log says what ran, never what was considered; the router listing is already at
its budget ceiling; and re-tuning descriptions on a hypothesis is how that budget gets spent for
nothing. ADR 0081 and the roadmap name the measurement it needs first.

## Verification

- `python dev/validate.py` — Tier-0 clean.
- `pytest -q --cov=agentic_forge --cov-fail-under=80` — green, 97.8% coverage.
- `ruff check .`, `mypy plugin/lib plugin/hooks plugin/bin dev` — clean.
- All 14 security-block records from the bundle replayed against the new classifier: none blocks,
  controls still block.
