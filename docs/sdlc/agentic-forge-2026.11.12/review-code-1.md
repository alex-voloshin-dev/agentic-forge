---
type: review
feature: agentic-forge-2026.11.12
iteration: 1
verdict: changes
---

# Review round 1: the commit gate follows the commit's directory (item 7, ADR 0111)

Diff: branch `fix/commit-gate-cwd`, commit 23e54db against master 7b014d6.
Lenses: reviewer (changes), security-engineer (changes), external lens codex (changes).
Decision (`af.py review-decision --verdict changes --iteration 1`): revise.

## Findings (aggregated, verified against the source)

### Major
1. **A linked worktree of the same repository is trusted, but its files may not be** (security).
   Comparing only `--git-common-dir` accepts any linked worktree, including the detached PR-head
   worktrees the plugin itself creates (run_scheduled, code-review trial merge). The gate would run
   that checkout's own scripts before the permission prompt. A directory whose `.git` file points
   into this repository also passes. Fix: move only within the start directory's own work tree
   (same real `--show-toplevel` and `--absolute-git-dir`).
2. **Pushes and commits the counter does not see** (reviewer). A push inside `{ }`, after
   `if/then`, after `!`, or in a trailing subshell is not counted, so the "one directory" check
   passes while that push runs elsewhere.
3. **A `cd` joined by `;` can fail and the commit still runs in the start directory** (codex,
   reviewer). A redirection on the `cd`, or a path through a missing component (`nowhere/..`),
   fails at run time while the lexical target exists.
4. **`-C` resolved lexically, git resolves it physically** (codex major; reviewer and security
   minor/nit). `..` after a symlink lands in a different directory.

### Minor
5. Ignored directories (`node_modules/<pkg>`) pass `--is-inside-work-tree`; their scripts would be
   the gate (security).
6. Git-steering variables: only `GIT_DIR`/`GIT_WORK_TREE` on the commit are refused; not
   `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_CONFIG_*`, nor an earlier `export` (reviewer, security).
7. A wrapper with its own chdir (`env --chdir=`, `sudo --chdir=`) before the commit is skipped as a
   flag (reviewer). An assignment before `cd` (`CDPATH=`) is accepted (security).
8. Commit-then-push with a `"$(cat <<'EOF' ...)"` message falls back, so the field case remains for
   that common form, while the docs say the heredoc form is handled (reviewer).
9. One `cd` can reach a subdirectory's `test_gate.skip` or a directory with no gate for a commit that
   records the whole index (security). Reachable before in two calls; documented as a limit.

### Nit
10. `main` resolves the directory a second time on a block (reviewer).
11. ADR 0111 §4 overstates what the narrowing test proves (reviewer).
12. Check and run use the unresolved path string; return the real path (security).

## Direction for round 2
Replace the denylist with an allowlist: follow only a line of `&&`-joined segments that are plain
`cd <literal>` (no prefix, no redirection) and plain `git [-C <literal>]... add|commit|push`
segments, with no reserved word, group, subshell or other separator anywhere; a balanced heredoc
commit message is read as one word. Resolve `-C` physically. Accept a target only in the start
directory's own work tree and not ignored. Any `GIT_*` or `CDPATH` assignment or export in the line
falls back. Return the real path once and reuse it.
