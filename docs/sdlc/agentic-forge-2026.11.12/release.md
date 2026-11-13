---
type: release
feature: agentic-forge-2026.11.12
status: final
version: 2026.11.12
date: 2026-11-13
changelog:
  - "The commit gate runs in the directory the commit acts on: a leading cd or pushd, and git -C, are followed (ADR 0111)."
  - "It follows only a plain line of && segments, and only into a tracked, not ignored directory of the start directory's own work tree."
  - "A block on a moved commit names the directory to cd into; the Python 3.9 hook smoke runs a moved commit."
breaking:
  - "A commit written as cd <dir> && git commit, or git -C <dir> commit, is now gated as <dir>. It can block where it passed before, and pass where it was blocked."
---
# Release 2026.11.12

One fix from the field queue: board `known-issues` item 7, reported in thread 6b032379 by the f4ai fleet. ADR 0111
records the decision.

## What changed

- **The commit gate runs where the commit happens.**
  - **Before:** the hook used the directory the shell stood in when the Bash call started. After an earlier
    `cd svc`, `cd .. && git commit` and `git -C <root> commit` were gated as `svc`. The package's old lint findings
    blocked a root commit that would pass from the root. The fleet's workaround was a separate `cd` call before
    every commit.
  - **Now:** `guardrails.commit_dir` reads the command. The gate's settings, its choice, its narrowing, its tool
    resolution and its messages all use the directory the commit acts on.
- **What is followed.** Only a line of `&&`-joined plain segments:
  - `cd <dir>` or `pushd <dir>`;
  - `git [-C <dir>]… add|commit|push …`, including a `-m "$(cat <<'EOF' … EOF)"` message.

  Anything else keeps the start directory, as before: `;`, `||`, pipes, subshells, groups, wrappers, prefix
  assignments, variables, other git options.
- **Where it may go.** The gate runs the project's scripts before you are asked, so a command must not steer it
  into code the session has not been working in. The target must be:
  - inside the start directory's own work tree (not another repo, not a linked worktree, not a submodule);
  - not ignored by git;
  - holding a regular tracked file beneath it, matched literally.
- **A block on a moved commit** says to run `cd <dir>` as its own call, then the commit. It no longer suggests a
  bare `git commit`, which would run in the start directory.
- **CI under Python 3.9** now runs a moved commit through the hook.

## Breaking

- **A moved commit is gated as the directory it moves to.** `cd <dir> && git commit` and `git -C <dir> commit` are
  now gated as `<dir>`. A commit that passed because the start directory was clean can now block on `<dir>`'s
  findings, and the reverse.

## How it was checked

- Five review rounds: reviewer, security-engineer and the external lens (codex). Round 3 used up the budget of
  three and was escalated to the owner, who chose one more round before release. The final round is approve from
  all three.
- QA added six end-to-end tests that run the hook as Claude Code does, under the test interpreter and Python 3.9.
  All six fail on 2026.11.11.
- Tier-0: `dev/validate.py`, `ruff`, `mypy` (including `plugin/bin`), the full pytest suite, and
  `dev/hook_smoke.py` under Python 3.9.25.

## Not validated

No skill description or role changed, so per the eval policy this release ran Tier-0 and the direct tests only.

- Tier-1 (trigger), Tier-1b (activation): not run.
- Tier-2 (quality): not run.
- Tier-3 (E2E spine): not run.

## Known limits (ADR 0111)

- A tracked directory passes whatever untracked files sit in it. The start directory has the same exposure.
- A `cd` into a subdirectory with no gate, or with its own `test_gate.skip`, turns the gate off for a commit that
  records the whole index. That was reachable before in two calls.
- The hook cannot see a shell set for physical `cd`, or a `CDPATH` set only in the shell's rc files.
- Follow-ups: the merge gate's background-`cd` gap; the narrowing's git reads run git by bare name.
