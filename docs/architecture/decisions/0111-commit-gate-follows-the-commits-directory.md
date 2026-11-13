# ADR 0111 — The commit gate follows the commit's directory

Status: Accepted (implemented)
Date: 2026-11-13

Amends [0101](0101-the-commit-gate-only-narrows.md) ("no following `git -C` or `cd`") and
[0019](0019-l4-guardrails.md) (where the test-gate runs).

## Context

A field report, verified on 2026.11.11. `commit_gate.gate_decision` took `cwd = payload["cwd"]`. That is the shell's
directory when the Bash call **starts**. Claude Code keeps the shell's directory between calls, so one `cd svc` makes
`svc` the start directory of every later call. Then:

| Call (start directory `repo/svc`) | Commits in | Gated as | Result |
| --- | --- | --- | --- |
| `git commit --allow-empty -m x` | `svc` | `svc` (narrowed: nothing changed) | passes |
| `cd .. && git commit --allow-empty -m x` | the root | `svc`, `ruff check .` whole | **blocked by svc's old findings** |
| `git -C <root> commit --allow-empty -m x` | the root | `svc`, `ruff check .` whole | **blocked** |

The same commit from the root passes: the root has no manifest, so it is ungated (ADR 0101's rule). The wrong directory
reached everything the hook does with `cwd`:

- `settings.resolve` (which `.agentic-forge/config.json` decides `test_gate.skip`);
- `choose_gate` and `narrow`;
- `resolve_gate`/`gate_env` (whose `.venv/bin`);
- where the gate runs;
- the block and skip messages, which named the wrong config file.

ADR 0101 had deliberately refused to follow `cd` and `-C`, but for narrowing: a narrowed gate is computed from git
reads in one directory. Running the whole gate in the directory the command leaves was never the intent; it was the
old behaviour, kept.

## Decision

**The hook resolves the directory first, with `guardrails.commit_dir(command, cwd)`, and uses it for every `cwd` use in
`gate_decision`.** Everything ADR 0101 says about "cwd" now means that directory. `commit_dir` returns either the payload
`cwd` unchanged (what the gate always did) or a directory it is sure of.

**1. Reading the command.** It reuses the merge gate's lexer (`_lex`, `_cd_takes_effect`, `_cd_target`,
`_git_subcommand`). The lexer gains a `partial` mode, off for the merge gate. When a command substitution cuts a
command short, it keeps the words read so far and marks the word holding the substitution as dynamic. Without it,
the form agents commit with, `git commit -m "$(cat <<'EOF' …)"`, would never be read. For each `git commit`/`git
push` in command position, start from `cwd` and:

- apply each earlier `cd`/`pushd` with one literal argument. It counts only when the merge gate's rule says it takes
  effect, and when nothing but `&&`, `;` or a newline separates it from the commit. The merge gate's rule alone would
  accept `cd x && sleep 1 & git commit`, where the `cd` runs in a background subshell;
- then apply the commit segment's global `-C` options in order, a relative one relative to the one before. That is
  how git applies them. `-C ""` changes nothing, as in git.

**2. What keeps the start directory** (`cwd` returned unchanged):

- **A target only a shell can work out:** `~`, a variable, a glob, `cd` alone, `cd -`, `cd -P x`.
- **A `cd` that may not take effect:** `||`, `|`, `&`, a subshell, a `{ }` group or a compound command.
- **A directory change the reading does not follow:** `popd`, `source`/`.`, `eval`, `builtin`, `command cd`.
- **Another tree:** `--git-dir`/`--work-tree`, `-c core.worktree=`, `--config-env`, or `GIT_DIR=`/`GIT_WORK_TREE=` on
  the commit. The same holds when the hook's own environment has one of the variables that make `narrow` leave the
  gate as it is.
- **An uncertain line:** an unbalanced quote; several commits/pushes that resolve to different directories; or a
  line cut short by a substitution where the trigger (`is_commit_or_push`) counts more commits/pushes than were read,
  which means one may hide in the unread tail.
- **The target is not safe to use:** not an existing directory, or not inside a working tree.
- **No absolute `git`, a timeout, or any other failure.** It never raises.

**3. Only inside the same repository.** The gate runs project scripts (`dev/validate.py`, `npm run lint`, `ruff`) before the
user's permission prompt, so a command must not be able to steer it into another checkout. The target is used only when
`git rev-parse --is-inside-work-tree --git-common-dir` says `true` in both directories and the common directories
resolve to the same real path. A linked worktree of the same repository counts. That is the same trust the session already
extends to that repository, and the shared common directory means the same hooks and config.

The reads run git by the absolute path `PATH` gives, never a relative entry, as `merge_preflight` and `role_scope` do.
They use `gate_scope`'s hardened flags (`--no-replace-objects`, `core.fsmonitor=false`, `safe.bareRepository=explicit`,
…) and its twelve-name environment allowlist, with `GIT_NO_LAZY_FETCH=1`, and share one 2-second budget. A command with
neither a `cd` nor a `-C` (every plain commit) reads no git at all.

**4. Narrowing is untouched and cannot disagree with it.** `gate_scope.parse_simple` refuses any `cd` or `-C`, so a
command that moves the directory always runs whole in the new directory, and every command that narrows resolves to the
start directory itself. Two tests hold this: every `SIMPLE` shape resolves to `cwd`, and every moved shape fails
`parse_simple`.

**5. Messages.** The block names the resolved directory ("in <dir>"). The operator's skip notice names
`<dir>/.agentic-forge/config.json`, the file that decided. The hook's `main` resolves it again only on a block. The
diagnostics records use it too; they land in the same main repository either way.

## Rejected alternatives

- **Gate from the repository root always.** It would change which gate runs for every commit, not only the moved
  ones, and contradicts ADR 0101's rule that the root with no manifest stays ungated.
- **Follow any directory the command names.** The hook runs project scripts before the user is asked. A prompt-injected
  `git -C /elsewhere commit` would make it run another checkout's `dev/validate.py`.
- **Compare `diagnostics.main_repo_root` instead of asking git.** It parses `.git` files without git, which is cheap but
  approximates: a submodule, `GIT_DIR` layouts and a worktree whose pointer moved are read differently from how the
  commit will see them. Asking git costs two process starts, only when the command names a directory.
- **Make the merge gate's `_cd_takes_effect` stricter in the same change.** The extra separator check lives in
  `commit_dir` only, so the merge gate's behaviour is unchanged by this ADR. The merge gate has the same gap: `cd x &&
  git status & gh pr merge 5` is attributed to `x`, while the merge runs in the start directory, because `git status`
  is read-only. That gate fails open and only reads, so the gap is recorded as a follow-up, not fixed here.

## Limits

- **`CDPATH` is not read.** With `CDPATH` set, `cd sub` can go somewhere other than `./sub`. The same-repository check
  bounds where that can land.
- **A `cd` hidden in an alias, a function or a script** is not seen. The start directory stays, as before.
- **A wrapper before the commit is followed through as `is_commit_or_push` follows it** (`timeout 5 git -C .. commit`).
  `env -C dir git commit` is not a commit to either.
- **Logical `cd ..`.** From a start directory reached through a symlink, `cd ..` goes to the link's parent, as the shell's
  does. If that is outside the repository, the start directory stays.

## Consequences

- A root commit from a package's start directory is gated as the root, and a package commit from the root as the package.
  That one blocks where it used to pass: it now meets the package's gate, which is the gate it should have met.
- `test_gate.skip` is read from the directory the commit acts on.
- ADR 0101's invariant now reads "only the gate of the directory the commit acts on, from that directory". Its design
  test is unchanged: its commands use `cd .` and `-C .`, which resolve to the start directory.
- Hook-reachable, so Python 3.9; `dev/hook_smoke.py` imports it.
