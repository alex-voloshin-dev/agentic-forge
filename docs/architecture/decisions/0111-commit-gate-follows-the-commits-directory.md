# ADR 0111 — The commit gate follows the commit's directory

Status: Accepted (implemented)
Date: 2026-11-13

Amends [0101](0101-the-commit-gate-only-narrows.md) ("no following `git -C` or `cd`") and
[0019](0019-l4-guardrails.md) (where the test-gate runs).

## Context

A field report, verified on 2026.11.11. The hook (`commit_gate.gate_decision` then, `decide`/`_gate` now) took
`cwd = payload["cwd"]`. That is the shell's
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

ADR 0101 had refused to follow `cd` and `-C`, but for narrowing: a narrowed gate is computed from git reads in one
directory. Running the whole gate in the directory the command leaves was never the intent; it was the old behaviour,
kept.

## Decision

**`commit_gate.decide` resolves the directory first, with `guardrails.commit_dir(command, cwd)`, and `_gate` uses it for
every `cwd` use.** Everything ADR 0101 says about "cwd" now means that directory. `commit_dir` returns either the
payload `cwd` unchanged (what the gate always did) or the real path of a directory it is sure of. The same path is used
for the checks below and for the run. `decide` returns the decision with that directory, so `main` names the right
config file in the skip notice without resolving it twice (`gate_decision` remains as a wrapper returning the
decision alone). When the directory moved, a block's shape hint does not advise a bare `git commit`, which would run in
the start directory under another gate: it says to run `cd <dir>` as its own call, then the commit as its own call.

**1. An allowlist of the whole line.** A first version read the line with the merge gate's lexer and refused what it knew
could move a shell. Review found what it did not know:

- a push inside `{ }`, after `!` or `if`, or in a trailing subshell, which it did not count;
- a `cd` joined by `;` that fails at run time, so the commit runs in the start directory;
- `env --chdir=` and `sudo --chdir=`;
- `CDPATH=` before a `cd`;
- `export GIT_DIR`.

So the line is now followed only when **every character** is one of:

- a word of safe characters and plain quotes (`gate_scope._WORD`: no `$`, backtick, backslash, glob, `~`, brace or
  newline, and no word starting with `=`);
- a balanced `-m "$(cat <<'EOF' … EOF\n)"` message, read as one opaque word;
- blanks;
- `&&`.

There is then no `;`, newline, `||`, `|`, `&`, redirection, comment, subshell or group anywhere. Each `&&`-joined
segment must be one of:

- **`cd <dir>` or `pushd <dir>`**: exactly one argument, with no prefix assignment and no option (`-P`, `-`, `+1`,
  `~…` are refused).
- **A plain `git`**: the bare word `git`, with no prefix assignment and no wrapper. Its global options may only be
  `-C <dir>`, and its subcommand must be `add`, `commit` or `push`. Any other git subcommand falls back, to keep it
  simple.

At least one segment must be a commit or push, and all of them must resolve to the same directory. Only `&&` joins the
segments, so a `cd` that fails stops the line before the commit, and a misread failure cannot move the gate. Each `cd`
step must still exist, both as written and as normalised: bash and zsh refuse `cd nowhere/..`, dash does not. With
`CDPATH` set in the hook's environment, only the forms bash and zsh do not search are followed: `/…`, `.`, `..`, `./…`
and `../…`. `cd .github` is searched like any other name.

The heredoc message is the shape `gate_scope._HEREDOC_MESSAGES` already accepts: a quoted delimiter, so the body is
not expanded, and the first line starting with the delimiter must be exactly it, followed by `)"`. bash also closes the
body on a line like `EOF)`, so that shape is refused. Here it may sit anywhere in the line, so the field's commit-then-push
(`cd .. && git commit -m "$(cat <<'EOF' …)" && git push`) is followed. A test proves that case.

The merge gate's lexer (`_lex`) is not used and is unchanged.

**2. `cd` is logical, `-C` physical.** `cd ..` from a directory reached through a symlink goes to the link's parent, as
the shell's does. git `chdir()`s to each `-C` in turn, so each step is `os.path.realpath(os.path.join(dir, arg))`, and
`git -C lnk/..` lands in the parent of the link's target. Each step's joined path must exist before it is resolved, as
git refuses `-C missing/../x`. `-C ''` changes nothing, as in git.

**3. Only tracked, not ignored, in the start directory's own work tree.** The gate runs project scripts
(`dev/validate.py`, `npm run lint`, `ruff`) before the user's permission prompt, so a command must not be able to steer
it into files the session has not been working in. The checks run in this order, and the first that fails keeps the
start directory:

- **Under the start's top, on the path.** The start side is read first. The target's real path must be the start
  directory's real top or lie under it, before any git runs in the target.
- **Same work tree.** One `git rev-parse --is-inside-work-tree --show-toplevel --absolute-git-dir` per side. The
  target is used only when both say `true` and both the real top and the real git directory are equal. A linked
  worktree of the same repository is refused: the plugin itself creates detached PR-head worktrees
  (`run_scheduled`, code review's trial merge) holding someone else's code. An initialised submodule, a nested
  repository, a directory whose `.git` file points into this repository, and `.git` itself are refused too. An
  uninitialised submodule has no `.git` of its own and so passes this check, but the tracked check below refuses it.
- **Not ignored.** `git check-ignore --no-index -q -- <target>` must exit 1 (not ignored). `node_modules/<pkg>` is
  inside the work tree, but it is not the project's code. `--no-index` keeps an ignored `dist/` ignored when one file
  in it was force-added. Exit 0 (ignored), an error or no time left keeps the start directory.
- **A regular tracked file beneath the target.** The check reads `git --literal-pathspecs ls-files -z -s --
  <target>/` from the start's top. At least one entry must be a regular entry (mode not `160000`) whose path lies
  strictly beneath the target (`<target>/…`, top-relative; for the top itself, any regular entry). Output that is
  not `<mode> <sha> <stage>\t<path>\0` records keeps the start directory.
  - **An exit code is not enough.** `ls-files --error-unmatch` also succeeds when the target is itself an index
    entry. Two such cases: a tracked file replaced on disk by a directory, and an uninitialised submodule's gitlink
    whose empty directory was filled with content.
  - **Refused:** those two; a directory whose only entry is a nested gitlink; an extracted archive or a clone with
    its `.git` removed (inside the work tree, not ignored, but holding nothing the repository tracks).
  - **Matched literally, on this read only.** As a pathspec glob, an untracked `x*` matched a tracked `xa/f`, and
    `x?` or `x[b]` a tracked file `xb`. The shared hardening flags are unchanged: the other reads take the target
    as a path, not a pathspec.

The reads run git by the absolute path `PATH` gives, never a relative entry, as `merge_preflight` and `role_scope` do.
They use `gate_scope`'s hardened flags (`--no-replace-objects`, `core.fsmonitor=false`, `safe.bareRepository=explicit`,
…) and its environment allowlist, with `GIT_NO_LAZY_FETCH=1`, and share one 2-second budget for the four calls. A
git-steering variable in the hook's own environment (the list `narrow` refuses) keeps the start directory. A line
naming no other directory (every plain commit) reads no git at all. Any exception keeps the start directory:
`commit_dir` never raises.

**4. Narrowing cannot pair with a moved directory, by construction.** `gate_scope.parse_simple` accepts only `git commit`,
`git push`, or one `git add <paths> && git commit`, with no `cd` and no global option. Such a line never names another
directory, so `commit_dir` returns the start directory for it, and a command that moves the directory always runs the
whole gate there. The tests check both directions over the matcher's own `SIMPLE` table and the moved shapes. The
guarantee comes from the matcher's grammar, not from the tests.

## Rejected alternatives

- **A denylist over the merge gate's lexer.** This was the first version, and review found five ways past it (§1).
- **The same repository, linked worktrees included.** It trusts files the session never worked in: a detached PR-head
  worktree, or any directory with a `.git` file pointing at the repository.
- **Gate from the repository root always.** It would change which gate runs for every commit, not only the moved
  ones, and contradicts ADR 0101's rule that the root with no manifest stays ungated.
- **Compare `diagnostics.main_repo_root` instead of asking git.** It parses `.git` files without git and approximates
  submodules and moved worktree pointers. Asking git costs up to four process starts, only when the line names a directory.

## Limits

- **One `cd` can turn the gate off for a whole commit.** A `cd` into a subdirectory with no gate, or with its own
  `test_gate.skip`, ungates a commit that records the whole index. This was reachable before in two calls (`cd sub`,
  then commit). The gate guards against accidents; it is not a boundary against the model.
- **Only the plain shapes are followed.** `cd x; git commit`, a wrapper, a multi-line message in plain quotes and
  `-F - <<'EOF'` all keep the start directory, as before this ADR. A `cd` hidden in an alias, a function or a shell
  hook (`zoxide`, `auto_cd`) is not seen. The work-tree check bounds where one could land.
- **The shell's own settings are not seen.** A shell set for physical `cd` (`set -P` in bash, `CHASE_LINKS` or
  `CHASE_DOTS` in zsh) resolves `cd lnk/..` through the link, so the commit may land in another directory of the same
  work tree than the one gated. The hook sees only its own environment's `CDPATH`, not one set in the shell's rc
  files. Both stay inside the start directory's own work tree, by the checks in §3.
- **The path checks have no timeout of their own.**
  - `os.path.isdir` and `os.path.realpath` on the `cd`/`-C` steps run before the 2-second budget starts.
  - The `realpath` of git's output (the top and git directory) runs inside the budget, but nothing interrupts it.

  A stalled mount (NFS, FUSE) can hold the hook up to its own 120-second cap. That fails open, and the commit is not
  gated.
- **The merge gate has a background-`cd` gap.** `pr_merge_target("cd x && git status & gh pr merge 5", "/w")`
  attributes the merge to `/w/x`, while the merge runs in `/w`, because `git status` is read-only. That gate fails
  open and only reads. This is a follow-up.
- **`gate_scope._git` runs git by bare name.** The narrowing reads resolve `git` through the subprocess `PATH`, where
  a relative entry resolves against the directory. `commit_dir` uses an absolute path; the narrowing reads were not
  changed here. This is a follow-up.

## Consequences

- A root commit from a package's start directory is gated as the root, and a package commit from the root as the package.
  The package commit blocks where it used to pass: it now meets the package's gate, which is the gate it should have met.
- `test_gate.skip` is read from the directory the commit acts on.
- ADR 0101's invariant now reads "only the gate of the directory the commit acts on, from that directory". Its design
  test is unchanged: its commands use `cd .` and `-C .`, which resolve to the start directory.
- Hook-reachable, so Python 3.9; `dev/hook_smoke.py` imports it.
