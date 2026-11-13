# ADR 0101 — The commit gate only narrows what it already does

Status: Accepted (implemented)
Date: 2026-11-03

Amends [0019](0019-l4-guardrails.md) (what the test-gate runs on). Closes part of field report AF-04.

> **Amended 2026-11-11 by [ADR 0109](0109-four-field-bugs.md):** the gate runs `npm run lint` only when a `lint` script exists, reads only the cwd's stack and a hint's first name, and refuses shell syntax.

> **Amended 2026-11-13 by [ADR 0111](0111-commit-gate-follows-the-commits-directory.md):** "cwd" here is now the directory the commit acts on: a leading `cd` that surely takes effect and git's `-C` are followed, within the same repository only. Narrowing is unchanged: a command with a `cd` or `-C` is never simple, so it runs whole in that directory.

## Context

`commit_gate.py` passed the hook payload's `cwd` to `guardrails.choose_gate` and ran the result there. It never asked
what was being committed. A field report, reproduced on a monorepo in a linked worktree with no skip in play, the same
empty commit each time:

| Session cwd | `choose_gate` | `git commit --allow-empty` |
| --- | --- | --- |
| repo root (no manifest) | `None` | succeeded |
| a package with `pyproject.toml` | `ruff check .` | **blocked by 97 old findings** |
| a package with `go.mod` | `go vet ./...` | not attempted |
| a directory with no stack | `None` | not attempted |

So an empty or unrelated commit from a package paid for old debt. The other half of the table, that a Python change
committed from the root is not linted at all, is real too, and **this ADR leaves it as it is**.

## Decision

**The gate that runs is exactly what `choose_gate(cwd)` picks, from the same cwd, or less. Nothing else ever runs.** No
gating from the root, no walking to a package root, no new tool, no following `git -C` or `cd`. The hook calls
`gate_scope.narrow(gate, command, cwd)`, which returns one of three things: the gate unchanged, `None` to skip it, or
`ruff check` with files. There is no other output, so it cannot widen.

**1. A small strict matcher decides whether the command is understood at all** (`parse_simple`, 45 lines). Accepted:

- optionally one `git add <literal paths>`, `git add -- <paths>`, `git add -A`, `--all` or `.`, joined by `&&`, then
- `git commit` with only `-m`, `--message`, `-am`, `-qm`, `-a`, `--all`, `--allow-empty`, `--no-verify`, `-n`, `-q`,
  `--quiet`, `-s`, `--signoff`; or
- `git push`, `git push <r>`, `git push <r> HEAD` or `git push <r> <branch>`, each optionally `-u` or `--set-upstream`. A
  `git add` before a push is not accepted.

A word is safe characters or a quoted part. Quoted text is data, so `-m "fix(x): a; b #3"` is understood. Anything the
shell could act on is not: `$`, a backtick, a backslash, a glob, `~`, `{`, a word that starts with `=` once its quotes are off
(zsh expands `=ls`, and `''=ls` too), or outside quotes `(`, `)`, `;`, `|`, `<`, `>`, `#`, a lone `&`, and any newline, quoted or not. A flag not on the list is not
understood either, which is how `--amend`, `--git-dir`, `-C`, a pathspec and an abbreviated `--mess` are refused without
naming them.

There are two exceptions to the newline rule, because they are how agents write commit messages: `-m "$(cat <<'EOF' ... EOF\n)"`
and `-F - <<'EOF' ... EOF`, recognised strictly. Either must end the command, nothing before it may be quoted (so an open
quote cannot make it mean something else), the delimiter must be quoted (so the body is not expanded), and the first line
that starts with the delimiter closes it, since bash also closes on `EOF)`. A second `EOF` further down is a smuggled command and fails.

**Any other shape, or any git failure, behaves exactly as before.** Uncertainty is never an allow and never a new block.

**2. Git says what changed.** Paths and modes, NUL-separated, as bytes, so any filename survives.

| Command | Read |
| --- | --- |
| `git commit` | `git diff --cached` |
| `-a` | also `git diff`: tracked changes, not untracked files, which `-a` cannot take |
| `git add x && ...` | also `git diff -- x` and `git ls-files -o --exclude-standard -- x`: what that add covers, not every dirty file |
| `git add -A` | the same with the pathspec `:/` |
| `git add .` | the same with `.`: this directory, as git reads it |
| `git push` | `git log -c --no-renames --name-only HEAD --not <what the remote has>` |

A push narrows only when it can only send the current branch to the same name on one remote. Otherwise the gate runs whole:

- **The branch**, if named, must be `HEAD` or the current branch. HEAD must be on a branch.
- **The remote** is the one named, else git's own answer through `@{push}`, and it must be in `git remote`. With no name
  given, `@{push}` must be exactly `refs/remotes/<remote>/<current branch>`: a remote may hold a slash, so
  `refs/remotes/team/fork/main` is not parsed, it is compared with each remote in turn.
- **Config:** `push.default` must be unset, `simple` or `current`, and `remote.<r>.push` and `remote.<r>.mirror` unset, for every
  form. `push.default=upstream` and a `remote.<r>.push` mapping each land a commit on `main` while the command reads as a push of
  `feature`, and that was reproduced with real pushes. `GIT_CONFIG_COUNT` or `GIT_CONFIG_PARAMETERS` in the environment also run
  whole, since they steer the real push while the read would not see them.
- **What the remote has** is the tracking ref `refs/remotes/<r>/<current branch>` when it exists, and then `@{push}` must equal it. So
  a commit on `origin/wip` fast-forwarded onto `main` is news to `main`. With no such ref, as for a new branch, it is
  `--remotes=<r>`.

`-c` lists a merge's own changes, the files that differ from every parent: plain `git log` lists no merge diff. `--no-renames`
lists both sides of a move.

**3. What follows from the changed set.**

- **Empty: skip the gate, whichever it is.** This is what lets an empty commit pass. It is the only case in which
  `dev/validate.py`, `npm run lint`, `cargo clippy` or `rubocop` do not run as they did.
- **`ruff check .`** runs whole if a tracked lintable name under cwd is a symlink (`git ls-files -s`, mode 120000), even when
  nothing under cwd changed: ruff follows a file symlink, so the whole gate lints its target wherever that is, and a change to the
  target can only be seen by running it. A block's tail is redacted, so running it is safe. Then only files under cwd count, and if
  there are none it is skipped. It stays whole, in order, if:
  - one of them is a `pyproject.toml`, `ruff.toml` or `.ruff.toml`, because a commit of a broken config would otherwise pass on
    its files alone and then disarm later commits;
  - a user-level ruff config exists (`$XDG_CONFIG_HOME/ruff/`, `~/.config/ruff/`);
  - any config in cwd, above it, or on the way from cwd to a changed file mentions `include`, `extend-include`, `extension`, or
    `extend` (quoted or not) as a key, because the fixed extension list does not hold there. A `pyproject.toml` counts if it
    mentions the word `ruff` at all. This is a word match and not TOML on purpose, and over-triggering it is correct;
  - a changed path is a directory (a submodule, an untracked nested repo), a gitlink (mode 160000, whatever is on disk), or is, or
    runs through, a symlink.

  Otherwise it is skipped when no file under cwd has a lintable extension (`.py`, `.pyi`, `.pyw`, `.ipynb`) and is still there, and
  if one does it runs as `ruff check ./a.py ./b.py`, from the same cwd, with the same tool resolution. `./` keeps `-x.py` from being
  a flag and `@x.py` from being an argument file. A file gone from the tree is dropped, because ruff reports it as E902, exit 1.
- **`go vet ./...`:** skip only when no changed file is under cwd, otherwise unchanged. Cgo, headers, assembly, `embed` and
  `go.work` are all build inputs, so no extension list is safe.
- **Any other gate:** as before.

**4. A narrowed failure only says there is something to look at. The whole gate decides.** On any non-zero narrowed exit, the hook
runs the whole gate and applies the classification it always applied to that result: exit 0 allows, could-not-run fails
open with the notice, and anything else blocks, showing the narrowed run's findings rather than the old debt. So a block
happens only where the old gate would have blocked. This matters in three ways, all measured on ruff 0.17.3:

- An explicit path reaches what `ruff check .` does not walk: a gitignored file, and anything the project excludes.
  `--force-exclude` is not the way out. It covers `exclude` only, and it tests the cwd's own name too, so from a directory
  named `dist`, `venv`, `.venv`, `_build`, `node_modules` or `site-packages` a narrowed run linted nothing and said nothing.
- A finding quoting a signature such as `ModuleNotFoundError` is read as a tool that could not run. That is a defect of the
  text match, and it stays that defect here rather than becoming a block the old gate did not give.
- A broken config blocks as before.

This costs one extra run, on a failure only, of the command that always ran.

**5. A block tells the model to fix it or ask, and tells the operator how to skip it.** stderr reaches the model. It names the
argv (at most 12 words of it), "on the changed files only" or "run whole", and the cwd, then the tail through
`guardrails.redact_secrets`, since a tracked symlink to a credentials file made ruff quote secrets into the model's context, then
"Fix the findings, or ask the user." It does not say how to turn the guardrail off. That goes in `systemMessage`: set
`test_gate.skip: true` in `<cwd>/.agentic-forge/config.json` in a separate call first, because the hook runs before the
command. Measured on the CLI 2.1.317: on exit 2 a `systemMessage` on stdout is shown to the operator (`system/informational`) and
the model's tool result holds only stderr. Config lookup is unchanged: `settings.resolve(cwd)`, so that is the file it reads.

A block on a shape the matcher refused, for a ruff or go gate, adds one line: this command shape ran whole, and running `git
commit` or `git push` as its own call gates only what changed. So every fallback has a way back, with no parser growth.

Control characters and undecodable bytes are escaped in the message, and in the notice's argv and detail. The argv is escaped
down to one line.

**6. The reads run nothing a directory defines, and leave no trace.** Each is `git --no-replace-objects -c core.fsmonitor=false -c
safe.bareRepository=explicit -c diff.relative=false -c diff.autoRefreshIndex=false -c log.showSignature=false -c
log.showRoot=true`, and diff reads add `--ignore-submodules=dirty`, because a dirty submodule's clean filter and fsmonitor ran from
the hook's git. All run with `GIT_NO_LAZY_FETCH=1`, from cwd, with one 5-second budget shared by all of them, which with the gate's
110 stays under the hook's 120. `diff.autoRefreshIndex` is the one that keeps the index unwritten: measured, `--no-optional-locks`
did not stop `git diff` rewriting it, so it is not used. The environment is an allowlist of twelve names, so no token reaches a
clean filter a repo's own config names. If `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR` or `GIT_OBJECT_DIRECTORY`
is set, the command would inherit it and a read without it would describe the wrong repo, so the gate is left as it is. A file list
past 100,000 characters also runs whole, since an argv the OS refuses would otherwise read as a fail-open.

## Why the full design was rejected

A first attempt made the gate derive its work from the change: find each changed file's package, gate from the repo root,
follow `git -C` and `cd`, read compound shell. It failed three review rounds and was not merged, for reasons that come from
the design rather than from its bugs:

- **It needed about 600 lines of approximate shell parsing** in code that must run on Python 3.9, and every round found
  another shape it read wrongly, since parsing shell is not a thing one finishes. An approximate parse here decides
  whether to run a guardrail.
- **It added blocks.** Gating the root is right in principle and is still a new failure for every repo that never met the
  gate, in a release that set out to remove a false block.
- **It skipped silently.** Files of no known stack dropped out of the gate with nothing saying so.
- **It ran code in more places.** Walking to package roots ran `npm run lint` or a local `ruff` for directories the
  session never stood in. That grew its own trust rules (a tool git tracks, a manifest not in HEAD), which grew their own
  findings.

The rule that replaced it: this change may only remove work from what already runs, and anything it does not understand
changes nothing. That rule is what let the parser shrink by an order of magnitude, because a shape it refuses costs only
the old behaviour.

## Rejected alternatives

- **Reading ruff's exit code on a narrowed run** (1 findings, 2 could not run). A first version did. It blocked a finding that
  quoted `ModuleNotFoundError` where the old gate allowed, and it let a broken config through where the old gate blocked. Letting
  the whole gate decide removes the code and both differences.
- **`ruff check --show-files .` to intersect with the changed files.** Answers the question in section 4 directly, but on every
  run rather than on a failure, and it prints paths lossily, so a non-UTF-8 name would never match.
- **`git check-ignore` before the explicit run.** Covers `.gitignore` and not `include`.
- **`--remotes=<remote>` always.** It reads a merge from `main` as no news, which is friendlier, and hides a branch
  fast-forwarded onto `main` for the same reason.
- **Line-level scoping.** Needs a per-tool output parser and a diff mapper, and turns "this file is clean" into "this hunk
  is clean", which breaks when a change causes a finding elsewhere in the file.

## Limits

- **A commit from the repo root with no manifest stays ungated, as before.** So does any directory with no stack. This
  is the rule, not an oversight: nothing runs from there.
- **Per file, not per line.** Touching a file with old findings still blocks.
- **Whole-package tools are unchanged.** `npm run lint`, `cargo clippy`, `rubocop` and `dev/validate.py` run whole whenever
  anything changed anywhere, even outside cwd. Only an empty changed set skips them. So AF-04's sharp edge stays for them.
- **A project's custom `include` runs whole, not narrowed.** So does a commit touching a ruff config, any user-level ruff config, and
  a tracked lintable symlink. A config mention is plain text, so `include` under another tool's table counts too, and a package with
  a tracked `link.py` gets no narrowing at all.
  A user-level config on Windows is not looked for.
- **These shapes run whole**, with a line saying so if they block: `git commit -m x && git push`, `git add -A && git commit -m x &&
  git push`, two `git add`s, `git add x && git push`, `cd x && git commit`, `git -C`, `--amend`, `git commit <paths>`, a multi-line
  message in plain quotes, `$(...)` other than the heredoc above, `git push -q`, `--force`, `--tags`, a refspec, or another branch.
- **Landing an already-pushed branch is not gated where no tracking ref says what the target lacks**, as for a remote branch new to
  this clone, and never when the merge happens on the server, which is not a push. With a tracking ref, as for `main` here, it is
  read as news.
- **After merging `main` into a feature branch, the push reads what `main` brought**, because that is news to `origin/feature`. A file
  of someone else's with old findings blocks that push, as it did before this ADR. This was accepted.
- **A change can create a finding in a file it does not touch.** A deleted `__init__.py` runs whole. Moving a module into a package can
  still reorder another file's imports (`select = ["I"]`) and go unseen: it looks the same as a clean new file beside old findings,
  which is the case this ADR exists for. A shared config reached through `extend` under another name is not recognised as a config.
- **A sibling package that cwd imports is not gated when only it changed** (Go). `go vet ./...` follows imports, and the skip only
  looks under cwd. Anything changed under cwd runs it.
- **The narrowed run spends the shared deadline before the whole confirmation.** The two share the gate's 110 seconds, so a 10-second
  narrowed run plus a 105-second whole run fails open where the old gate, at 105 seconds, would have blocked.
- **A clean file with a non-UTF-8 name blocks, as it did.** ruff 0.17.3 exits 2 on such a name because it cannot serialise its cache,
  whatever the file holds, and the whole gate then fails the same way.
- **A gitlink is seen by its mode only in the diff reads.** A push reads names, so a submodule bump counts through the directory on
  disk, and one not checked out would not.
- **A tracked `.venv/bin/ruff` runs as it did**, because resolution is unchanged. A follow-up ADR is planned.
- **The gate reads the working tree, not the blob.** Partial staging lints the whole file as it stands; a push lints the
  files as they stand now, and a push of a branch other than HEAD lints this tree's copy of that branch's paths. A file
  removed with `git rm --cached` and still on disk is linted.
- **A tracking ref is as fresh as the last fetch.** A commit already on the remote but not fetched counts as new. With no tracking
  refs at all (a remote never fetched) all history counts, which is wide and still inside what the old gate linted, and usually runs
  whole because history holds a ruff config.
- **A narrowed block can name an out-of-scope file** if the directory also has real findings: the whole gate fails for
  its own reasons. It is never a block the old gate would not give.
- **A case-insensitive filesystem:** `git add Foo.py` for a file git knows as `foo.py` can read empty and skip the gate.
- **A stat-dirty file reads as changed.** `diff.autoRefreshIndex=false` means git does not compare content, so a touched tracked file
  is listed and linted, or makes a skip into a run. That only widens. It is also why a clean filter in the repo's own `.git/config`
  did not fire in the reads: on git 2.43, across 12 runs in review, plus a test. Other versions were not measured. `core.fsmonitor`,
  external diff, signature checks and a submodule's own config do not run either.
- **Real `go` was not available** where this was built. `go vet` is unchanged argv against a fake; only the skip is new.

## Consequences

- An empty or unrelated commit from a package no longer pays for old findings, and neither does an up-to-date push.
- A docs-only commit needs no lint toolchain, for ruff and go gates only.
- `choose_gate`, `resolve_gate`, `gate_env` and `settings.resolve` are untouched.
- The model is no longer told how to disable the gate that blocked it, on any path.
- `test_for_every_command_it_never_runs_or_blocks_beyond_master` holds the design in one test: for every tested command, from
  each directory, only that directory's own tool ran, from that directory, on nothing outside it, and a block appeared
  only where the whole gate fails.
- `dev/hook_smoke.py` now runs one real narrowed commit, with a stand-in ruff that fails if it runs, so the 3.9 job reaches this
  module. An image with no git, such as `python:3.9-slim`, says it did not run; on CI that is a failure.
