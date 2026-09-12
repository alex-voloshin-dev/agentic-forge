# ADR 0081 — The 2026-09 field bundle: rules read text as text, and writes leak back into the repo

Status: Accepted (implemented)
Date: 2026-09-11

## Context

A 60-day diagnostics bundle arrived from one workstation running `2026.7.11` against a polyglot
monorepo: 92 diagnostic records, 311 audit sessions, and ten agent-memory notes. It is the first
report collected *after* the ADR 0079/0080 batch shipped, so it also says which of those fixes
held. Two did (heredoc bodies as data; the migration CLI). The rest of the bundle is evidence that
three separate assumptions were wrong.

Every claim below was reproduced against the installed version's own `guardrails` module, with the
controls (`rm -rf /`, `curl … | sh`) asserted first.

### 1. One rule never adopted the command-word discipline

ADR 0054 made every deny rule fire only on a **command word** in a segment, precisely so quoted
text about a command is not read as the command. ADR 0075's remote-environment-dump rule was added
afterwards as two raw-text regexes over the whole command string, and nobody noticed it had opted
out. The result composes two harmless halves into a block:

```sh
echo ssh; echo set          # blocked on 2026.7.11
```

`ssh` matched the remote-exec half (as a `for … in` word-list item, an `echo` argument, or text
inside a Python string), and `set` matched the bare-dump half *as an argument of `echo`*, because
the pattern only required a separator to follow. Both field cases have this shape — one is a
capability probe (`for t in az ssh scp sshpass psql; …`), the other a `python3` heredoc whose
**string literal** mentioned the shape. The second blocked the operator's analysis of the first,
and they routed around the guardrail by writing the script to a file.

This is not a heredoc problem. ADR 0079 correctly keeps an interpreter heredoc's body — it is a
program. The same text blocks without a heredoc.

### 2. `rm -rf` on macOS's own temp directory

`mktemp -d` returns `/var/folders/<hash>/<hash>/T/tmp.XXXX`, and `/var` is in the system-directory
list, so deleting one's own temp directory blocked — twice in one session. `/private/var/folders/…`
(the same path; `/var` is a symlink to it) passed, which is how visible the inconsistency was.

### 3. The write paths used the reader's helper, so the legacy directory fed itself

ADR 0072's rule — writes go to `state_root()`, reads may fall back to the legacy in-repo path —
existed only as a docstring on `existing_state_file()`. Four write sites called it anyway. Once a
legacy file existed, every later write went back into the repository: the bundle carries 18 765
audit records and 6 diagnostics written into `<repo>/.agentic-forge/` over 19 days, *after* that
repo had been migrated and verified clean. The user-level log has no trace of them.

ADR 0080's `legacy_state_notice()` did fire — into **stderr from a SessionStart hook that exits 0**,
which reaches nobody. Two months later the orphan was still there.

### 4. The gate did not run, and said so only to a file

`stacks.py` hardcodes `ruff check .`; the host has no global `ruff` (it lives in a service
virtualenv), and `eslint` only in `node_modules/.bin`. 50 of 69 recorded fail-opens are that one
`FileNotFoundError`. The fail-open itself is correct (ADR 0058/0059) and should stay. What was
wrong is that the gate resolved the tool as a bare name the way nothing in the project does, and
that two months of "the safety feature did not run" was visible only to whoever ran the digest.

(The bundle reads the 11 `block` records as the same problem still open. They are not: all ten
`npm run lint` blocks predate the operator's upgrade to 2026.7.10, and the one after it is a
genuine eslint failure. ADR 0058/0059 held.)

### 5. A logged block is not diagnosable

`context.command` is capped at 500 characters, and for 11 of 14 security blocks the matched text
was past the cut — replaying the record returns "no block" and there is nothing left to minimise.
The most recent evidence was the least usable.

### 6. Rotation discards the one artifact a field report is built from

10 MiB / 5 MiB is ~11–15 days on this workload (~950 tool calls/day). The 60-day request could
never have been answered; two thirds of the window was gone before it was asked for.

## Decision

1. **The remote-env-dump rule is per segment, on command position.** The remote wrapper must be a
   segment's command word (`ssh`, or `kubectl`/`docker`/`oc`/`fly`/`heroku` with its subcommand),
   and the dump must be that command's own **last** word — a following token means an exact lookup
   (`printenv PGHOST`) or a wrapper (`env VAR=1 ./run`). A remote command passed as one quoted
   string is re-split and checked the same way, so `ssh host 'printenv | grep KEY'` still blocks.
   An unparseable segment keeps the old text match, scoped to that segment.
2. **The per-user temp tree is not a system directory.** `(/private)?/var/folders/<x>/<y>/…` is
   exempt from the `rm`/`chmod` target check; `/var`, `/var/folders` and `/var/folders/<x>` are not.
3. **Writes use `state_file()`, reads keep `existing_state_file()`.** The rule is a function now,
   not a docstring. Read-then-write state (the watch queue, scheduler state) reads with the
   fallback and writes to the state root, so the next write drains the legacy file instead of
   feeding it.
4. **A notice goes where a session can read it.** The legacy-state notice moves to SessionStart
   `additionalContext` plus `systemMessage`; the commit-gate fail-open says one line per session
   through `systemMessage` — naming what did not run and what to do about it.
5. **The gate resolves its tool the way the project does.** Project-local bins first
   (`node_modules/.bin`, `.venv/bin`, `venv/bin`, at `cwd` and at the repo root), then `PATH`; and
   the gate subprocess gets those directories on its `PATH` so a package script's own linter
   resolves too.
6. **A block record carries `rule` and `evidence`.** The rule id that fired plus a 160-character
   excerpt of what matched — a few dozen bytes that make a truncated record self-contained.
7. **Rotation archives instead of discarding.** The dropped prefix is gzipped to
   `<state root>/archive/audit-<timestamp>.jsonl.gz`, six kept by default (`logs.archives`, 0
   restores discarding), and the notice states the span in **days** and where the records went.

## Consequences

- The env-dump rule is narrower in exactly one direction: a mention is no longer a command. Every
  true positive in its ADR 0075 test matrix still blocks, plus two shapes the raw-text version
  missed (`docker compose exec`, a dump inside a quoted remote command string).
- Anyone with an orphaned in-repo directory now sees a notice each session and their writes stop
  feeding it; the history still needs `bin/state_migrate.py` — a merge is not something a hook
  should do behind a user's back.
- Archives cost disk. Six archives of a 5 MiB drop are roughly 3–5 MB compressed; an operator who
  wants the old behaviour sets `logs.archives: 0`.
- `Decision` grew two optional fields. Callers that construct it positionally are unaffected.

## Observed, not acted on: the spine skills did not trigger in the field

The bundle's strongest signal is one this ADR deliberately does not "fix". Over 27 days:
**183 `Agent` calls against 3 `Skill` calls** — 86 `software-engineer`, 48 `reviewer`, 42
`security-engineer`, invoked directly in a per-PR implement → review → security loop across some
twenty PRs, while `develop` (the skill whose job is exactly that loop) fired once.

The roles carried a six-week feature; the L2 workflow layer did not participate. The plausible
reason is that the work arrived as tasks from a plan already written in the target repo, whose own
`AGENTS.md` prescribes the loop — a standing project instruction is already in context, while a
skill has to be chosen. Tier-1 measures a cold prompt with no competing instruction, so a passing
Tier-1 number does not predict field triggering.

That is a hypothesis, and the plugin cannot currently observe *why* a skill was not chosen — the
audit log records what ran, never what was considered. Changing router descriptions on a guess is
how the listing budget gets spent for nothing. The next step is measurement: a Tier-1 condition
that runs the should-trigger set **with** a competing project instruction in context, and one more
field bundle from a repo without a prescriptive `AGENTS.md`. Recorded in the roadmap.

## Alternatives considered

- **Parse Python inside interpreter heredocs** (the bundle's own suggestion, to ignore matches
  inside string literals). Rejected: it fixes one interpreter and not the general case — the same
  false positive fires with no heredoc at all. Command position fixes both.
- **Downgrade an interpreter-heredoc match from block to warn.** Rejected for the same reason, and
  it would weaken the rule where it is genuinely right (`ssh host <<'EOF'` runs its body).
- **Drop the `set` half of the dump rule** (it is the noisiest word). Rejected: `docker exec app
  set` is a real dump. Command position makes the word safe to keep.
- **Auto-migrate the legacy directory at session start.** Rejected: merging someone's logs is a
  destructive-ish operation that belongs behind an explicit command, which already exists. The
  notice is the right amount of automation.
- **Raise the rotation bound instead of archiving.** Rejected as the default: it moves the cliff
  without removing it, and the setting is already there for anyone who wants it.
