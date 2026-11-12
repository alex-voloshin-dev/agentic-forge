"""The role-scope guardrail (ADR 0106): the read-only roles are held to their tool scope by a
PreToolUse hook, in every permission mode, because a plugin agent's ``tools:`` specifier does not
restrict Bash."""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_forge import diagnostics, frontmatter, role_scope

_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / "plugin" / "hooks" / "scripts" / "role_scope.py"
sys.path.insert(0, str(_HOOK.parent))

import role_scope as role_scope_hook  # noqa: E402

REVIEWER = "agentic-forge:reviewer"
SECURITY = "agentic-forge:security-engineer"
GRADER = "agentic-forge:grader"
ARCHITECT = "agentic-forge:architect"
GIT_ROLES = (REVIEWER, SECURITY)
_REAL_GIT_VERSION = role_scope._git_version  # before the autouse fixture pins it


def _bash(command: Any, agent: str | None = REVIEWER, cwd: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
    }
    if agent is not None:
        payload["agent_type"] = agent
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


def _tool(tool: str, agent: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}}
    if agent is not None:
        payload["agent_type"] = agent
    return payload


@pytest.fixture(autouse=True)
def _git_2_43(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unit tests see one git: 2.43, which has --attr-source. The real one is asked in
    test_role_scope_exec.py and in the hook-process tests."""
    monkeypatch.setattr(role_scope, "_git_version", lambda: (2, 43))


# --- the read-only git rule: allowed forms ---------------------------------------------------

ALLOWED_GIT = [
    "git diff",
    "git diff --stat",
    "git --no-pager log -p",
    "git show HEAD:a.txt",
    "git blame -L 1,5 f",
    "git log --oneline -n 5",
    "git log -p -- src/app.py",
    "git status --porcelain",
    "git ls-files",
    "git ls-tree -r HEAD",
    "git rev-parse HEAD",
    "git merge-base HEAD main",
    "git cat-file -p HEAD",
    "git grep -n needle",
    "git shortlog -sn",
    "git describe --tags",
    "git log 'HEAD^'",  # a quoted `^` is git's; an unquoted one is refused
    "git log 'HEAD^^' HEAD~3..HEAD",
    'git log "x"=y x=y',  # `=` inside a word, after literal content
    "git log '=x'",
    "git diff main...HEAD",
    "git diff --text",  # a prefix of --textconv, but its own (harmless) option
    "git diff --no-ext-diff --no-textconv",
    "git diff -C -M50%",  # -C AFTER the subcommand is copy detection
    "git log -- 'src/*.py'",  # a quoted pathspec is git's glob, not the shell's
    'git log --grep "fix the bug"',
    "git show 'HEAD@{1}'",
    "git log --format=%H%x09%s",
    "git\tdiff",
    "'git' diff",
    '"git" "diff"',
    "g''it di\"\"ff",  # quote removal gives `git diff`, to the shell and to shlex alike
    "git log --grep='é'",  # non-ASCII inside quotes
]


@pytest.mark.parametrize("command", ALLOWED_GIT)
def test_read_only_git_is_allowed(command: str) -> None:
    assert role_scope.git_problem(command) is None
    for role in GIT_ROLES:
        assert role_scope.decide(_bash(command, role)) == role_scope.ALLOW


# --- the read-only git rule: refused forms ---------------------------------------------------

METACHARACTERS = [
    "git diff; ls",
    "git diff;ls",
    "git diff & ls",
    "git diff && ls",
    "git diff | cat",
    "git diff || ls",
    "git diff < f",
    "git diff > f",
    "git diff >> f",
    "git diff 2>&1",
    "git diff `ls`",
    "git diff $(ls)",
    "git diff ${HOME}",
    "git diff $HOME",
    "git diff $'\\x2d-output=f'",
    "git diff\nls",
    "git diff\rls",
    "git diff\x00ls",
    "git diff\x01",
    "git diff\x7f",
    "git log --grep='a;b'",  # refused anywhere, quoted or not
    'git log --grep "a|b"',
    "git diff -- *.py",
    "git diff -- ?.py",
    "git diff -- [ab].py",
    "git diff -- a]",
    "git diff {--stat,}",
    "git diff a}",
    "git diff (a)",
    "git diff !",
    "git diff #x",
    "git diff ^main",  # `^` is a pattern under zsh's extended globbing, anywhere in a word
    "git log a/^b",
    "git log HEAD^",
    "git log --o^x",
    # zsh expands a word that starts with an unquoted `=` to a command's path
    "git log =ls",
    'git log ""=ls',
    "git log ''=ls",
    # a backslash is refused anywhere: shlex, bash and zsh read it differently inside quotes
    "g\\it diff",
    "git diff \\--output=f",
    'git log "a\\"b"',
    "git log 'a\\'",
    "git diff 'unclosed",
    'git diff "unclosed',
    "git diff \\",  # a trailing escape does not tokenize
]


@pytest.mark.parametrize("command", METACHARACTERS)
def test_shell_syntax_is_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] == "role-bash-shell", (command, problem)


UNICODE_TRICKS = [
    "gіt diff",  # Cyrillic і
    "git diff ；ls",  # fullwidth semicolon
    "git diff",  # no-break space
    "git diff é",  # unquoted non-ASCII
    "git diff ‮x",  # bidi override
]


@pytest.mark.parametrize("command", UNICODE_TRICKS)
def test_unicode_outside_quotes_is_refused(command: str) -> None:
    assert role_scope.git_problem(command) is not None


FORBIDDEN_OPTION_FORMS = [
    "git diff --output=f",
    "git diff --output f",
    "git log --output=/tmp/x -p",
    "git diff --output-indicator-new=x",  # starts with --output: refused with it
    "git show -o f",
    "git show -ofile",
    "git log --ext-diff",
    "git show --textconv HEAD:a",
    "git cat-file --textconv HEAD:a",
    "git cat-file --filters HEAD:a",
    "git log -c",
    "git log -cfoo",
    "git diff --config-env=a=b",
    "git log --exec-path",
    "git log --exec-path=/x",
    "git log --upload-pack=x",
    "git log --paginate",
    "git grep --open-files-in-pager needle",
    "git grep -O needle",
    "git grep -Ovim needle",
    "git grep -nO needle",
    "git diff --help",
    "git log --help-all",
    # git accepts a unique prefix of a long option
    "git diff --out=f",
    "git diff --outp f",
    "git log --ext",
    "git log --textc",
    "git log --exec=/x",
    "git log --upload=x",
    "git log --pag",
    "git grep --open-files needle",
    "git diff --hel",
    # quoting does not hide an option
    'git diff "--output=f"',
    "git diff '--'output=f",
    # --no-index takes git outside the repository, where an external diff program runs
    "git diff --no-index a b",
    "git diff --no-ind a b",
    # refused after `--` too: the rule does not model where git stops reading options
    "git log -- --output=f",
]


@pytest.mark.parametrize("command", FORBIDDEN_OPTION_FORMS)
def test_options_that_write_or_run_a_program_are_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] == "role-bash-option", (command, problem)


@pytest.mark.parametrize("option", role_scope.FORBIDDEN_GIT_OPTIONS)
def test_every_forbidden_option_is_refused_bare_and_with_a_value(option: str) -> None:
    for token in (option, f"{option}=x"):
        problem = role_scope.git_problem(f"git log {token}")
        assert problem is not None and problem[0] == "role-bash-option", token


ROUND_3_REFUSED = [
    # cat-file: only -p, -t, -s, -e; `--text` is its abbreviation of --textconv
    "git cat-file --text HEAD:a", "git cat-file --batch-check", "git cat-file --batch",
    "git cat-file --batch-command", "git cat-file --batch-all-objects", "git cat-file -Z",
    "git cat-file --path=a HEAD", "git cat-file --use-mailmap -p HEAD",
    "git cat-file --allow-unknown-type -t HEAD", "git cat-file -pt HEAD",
    # `--text` means textconv where it is not its own option
    "git blame --text f", "git shortlog --text", "git ls-files --text",
    # nested submodule diffs, in every form and abbreviation
    "git diff --submodule", "git diff --submodule=diff", "git diff --submodule=log",
    "git log -p --submod=diff", "git show --submodule=short",
    # signatures run gpg
    "git log --show-signature", "git show --show-sig", "git log --format='%G?'",
    "git log --pretty=format:%GS", 'git log --format="%h %GK"', "git log --pretty=tformat:%GF",
    "git log --grep=%G",
    # with a modifier: `%+G…`, `%-G…`, `% G…` are placeholders too
    "git log --format=%+GS", "git log --format=%-GS", "git log '--format=% GS'",
    "git log --pretty=tformat:x%+GK", "git shortlog --group=format:%+GS",
    # a format alias from config could hold a signature placeholder
    "git log --pretty=sig", "git log --format=mine", "git show --pretty=",
]


@pytest.mark.parametrize("command", ROUND_3_REFUSED)
def test_options_that_reach_a_program_through_config_are_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] == "role-bash-option", (command, problem)


@pytest.mark.parametrize(
    "command",
    ["git cat-file -p HEAD", "git cat-file -t HEAD", "git cat-file -s HEAD:a",
     "git cat-file -e HEAD", "git cat-file blob HEAD:a", "git diff --text", "git show --text",
     "git log -p --text", "git grep --text x", "git diff -a", "git log --pretty=oneline",
     "git log --pretty", "git log --format=%H", "git log --format='%h %s'",
     "git log --pretty=format:%h", "git log --format=tformat:%an", "git show --pretty=fuller",
     "git log --oneline", "git log --show-notes", "git rev-parse --show-toplevel",
     "git blame --show-stats f", "git log --format=%g", "git log --format=%+gD",
     "git log --format=%+H"],
)
def test_their_harmless_neighbours_are_allowed(command: str) -> None:
    assert role_scope.git_problem(command) is None, command


def test_the_tilde_hint_comes_only_with_a_tilde(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    with_tilde = role_scope.git_problem("git -C '~/repo' log", str(repo))
    without = role_scope.git_problem("git -C src log", str(repo))
    assert with_tilde is not None and "without '~'" in with_tilde[1]
    assert without is not None and "~" not in without[1]


GLOBAL_OPTIONS = [
    "git -c x=y diff",
    "git -cx=y diff",
    "git -p log",  # --paginate as a GLOBAL option (after `log`, -p is a patch)
    "git --paginate log",
    "git -P log",
    "git --git-dir=/x diff",
    "git --work-tree=/x diff",
    "git --exec-path=/x diff",
    "git --config-env=a=b diff",
    "git --bare log",
    "git -C",  # -C with no path
    "git -C/x diff",  # only the separate form is accepted
]


@pytest.mark.parametrize("command", GLOBAL_OPTIONS)
def test_global_options_other_than_dash_c_path_and_no_pager_are_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] == "role-bash-global-option", (command, problem)


@pytest.mark.parametrize(
    "subcommand",
    ["push", "commit", "checkout", "config", "fetch", "pull", "reset", "clean", "rm", "add",
     "stash", "tag", "branch", "apply", "am", "gc", "worktree", "submodule", "help", "archive",
     "format-patch", "difftool", "bisect", "notes", "update-ref", "ls-remote", "restore",
     "switch", "merge", "rebase", "cherry-pick", "init", "clone"],
)
def test_subcommands_outside_the_read_only_set_are_refused(subcommand: str) -> None:
    problem = role_scope.git_problem(f"git {subcommand}")
    assert problem is not None and problem[0] == "role-bash-subcommand"


def test_a_quoted_subcommand_is_still_the_subcommand() -> None:
    problem = role_scope.git_problem('git "push"')
    assert problem is not None and problem[0] == "role-bash-subcommand"


@pytest.mark.parametrize("command", ["git", "git --no-pager", "git -C . --no-pager"])
def test_git_without_a_subcommand_is_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] in ("role-bash-subcommand", "role-bash-c-path")


@pytest.mark.parametrize(
    "command",
    ["ls", "python3 -m pytest", "pytest -q", "docker ps", "/usr/bin/git diff", "gitk",
     "GIT_DIR=x git diff", "env git diff", "sudo git diff", "command git diff", "'git diff'",
     "''", "cat a.txt"],
)
def test_commands_other_than_git_are_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] == "role-bash-not-git", (command, problem)


@pytest.mark.parametrize("command", ["", "   ", "\t"])
def test_an_empty_command_is_refused(command: str) -> None:
    problem = role_scope.git_problem(command)
    assert problem is not None and problem[0] == "role-bash-empty"


# --- -C must be a working tree of the session's repository -----------------------------------


def _main_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / ".git" / "worktrees").mkdir(parents=True)
    (repo / "src").mkdir()
    return repo


def _linked_worktree(repo: Path, at: Path, name: str = "wt") -> Path:
    """What `git worktree add` lays down: a private git directory under the main one, holding a
    `commondir` file that points back (relative to itself), and a `.git` file naming it."""
    gitdir = repo / ".git" / "worktrees" / name
    gitdir.mkdir(parents=True, exist_ok=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    at.mkdir(parents=True)
    (at / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return at


@pytest.mark.parametrize("name", ["worktrees", "modules"])
def test_a_checkout_in_a_folder_named_like_git_metadata_is_its_own_repository(
    tmp_path: Path, name: str
) -> None:
    """Repository identity comes from git's `commondir` file, never from a directory name: an
    ordinary checkout at `<x>/worktrees` (or `modules`) once counted as part of `<x>`, so `-C`
    reached any sibling repository beside it."""
    session = tmp_path / name
    (session / ".git").mkdir(parents=True)
    sibling = tmp_path / "unrelated"
    (sibling / ".git").mkdir(parents=True)
    for command in (f"git -C {sibling} diff", "git -C ../unrelated diff"):
        problem = role_scope.git_problem(command, str(session))
        assert problem is not None and problem[0] == "role-bash-c-path", command
    assert role_scope.git_problem("git -C . diff", str(session)) is None


def test_a_real_linked_worktree_is_recognised(tmp_path: Path) -> None:
    """The same membership on a worktree git itself created, not a hand-made one."""
    import subprocess

    repo = tmp_path / "repo"
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", str(repo)], check=True, timeout=20)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run([*git, "-C", str(repo), "add", "a.txt"], check=True, timeout=20)
    subprocess.run([*git, "-C", str(repo), "commit", "-qm", "x"], check=True, timeout=20)
    wt = tmp_path / "worktrees" / "wt"
    subprocess.run(
        [*git, "-C", str(repo), "worktree", "add", "-q", str(wt)], check=True, timeout=20
    )
    assert role_scope.git_problem(f"git -C {wt} log", str(repo)) is None
    assert role_scope.git_problem(f"git -C {repo} log", str(wt)) is None
    stranger = tmp_path / "worktrees" / "stranger"
    (stranger / ".git").mkdir(parents=True)
    problem = role_scope.git_problem(f"git -C {stranger} log", str(wt))
    assert problem is not None and problem[0] == "role-bash-c-path"


def test_dash_c_to_the_session_repository_is_allowed(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    assert role_scope.git_problem(f"git -C {repo} diff --stat", str(repo)) is None
    assert role_scope.git_problem("git -C . diff", str(repo)) is None
    assert role_scope.git_problem(f"git -C {repo} diff", str(repo / "src")) is None
    assert role_scope.decide(_bash(f"git -C {repo} log", cwd=str(repo / "src"))) == role_scope.ALLOW


def test_dash_c_to_a_linked_worktree_and_back_is_allowed(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    wt = _linked_worktree(repo, repo / ".claude" / "worktrees" / "wt")
    assert role_scope.git_problem(f"git -C {wt} diff --stat", str(repo)) is None
    assert role_scope.git_problem(f"git -C {repo} diff", str(wt)) is None
    relative = _linked_worktree(repo, tmp_path / "sibling", "sib")
    assert role_scope.git_problem("git -C ../sibling log", str(repo)) is None
    assert relative.is_dir()


def test_dash_c_to_a_submodule_of_the_repository_is_allowed(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    sub = repo / "vendor" / "lib"
    sub.mkdir(parents=True)
    (repo / ".git" / "modules" / "lib").mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../../.git/modules/lib\n", encoding="utf-8")
    assert role_scope.git_problem(f"git -C {sub} diff", str(repo)) is None


def test_dash_c_to_a_repository_shaped_directory_is_refused(tmp_path: Path) -> None:
    """A directory with HEAD, config, objects and refs is a repository to git, and its config is
    read; a reviewed change can ship one. -C must name a working tree of THIS repository."""
    repo = _main_repo(tmp_path)
    shaped = repo / "fixtures" / "shaped"
    (shaped / "objects").mkdir(parents=True)
    (shaped / "refs").mkdir()
    (shaped / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (shaped / "config").write_text("[core]\n\tbare = true\n", encoding="utf-8")
    for target in (shaped, repo / "src", repo / "missing"):
        problem = role_scope.git_problem(f"git -C {target} diff", str(repo))
        assert problem is not None and problem[0] == "role-bash-c-path", target


def test_dash_c_to_another_repository_is_refused(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    foreign = _linked_worktree(other, tmp_path / "foreign")
    for target in (other, foreign):
        problem = role_scope.git_problem(f"git -C {target} diff", str(repo))
        assert problem is not None and problem[0] == "role-bash-c-path"


@pytest.mark.parametrize("content", ["", "not a gitdir line\n", "gitdir:\n", b"\xff\xfe\x00"])
def test_a_dot_git_file_that_names_no_directory_is_refused(tmp_path: Path, content: Any) -> None:
    repo = _main_repo(tmp_path)
    odd = repo / "odd"
    odd.mkdir()
    if isinstance(content, bytes):
        (odd / ".git").write_bytes(content)
    else:
        (odd / ".git").write_text(content, encoding="utf-8")
    problem = role_scope.git_problem(f"git -C {odd} diff", str(repo))
    assert problem is not None and problem[0] == "role-bash-c-path"


def test_dash_c_is_refused_outside_any_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    problem = role_scope.git_problem("git -C . diff", str(plain))
    assert problem is not None and problem[0] == "role-bash-c-path"
    assert role_scope.git_problem("git diff", str(plain)) is None  # no -C, nothing to resolve


def test_a_second_dash_c_is_refused(tmp_path: Path) -> None:
    """git resolves a relative -C from the previous one, so `-C wt -C wt` runs in wt/wt: one -C."""
    repo = _main_repo(tmp_path)
    wt = _linked_worktree(repo, repo / "wt")
    for command in (f"git -C {repo} -C {tmp_path} diff", "git -C wt -C wt status",
                    f"git -C {wt} -C {wt} log", "git --no-pager -C . --no-pager -C . log"):
        problem = role_scope.git_problem(command, str(repo))
        assert problem is not None and problem[0] == "role-bash-global-option", command


@pytest.mark.parametrize("path", ["~", "~/repo", "'~/repo'", '"~"/repo', "repo/~", "x~y"])
def test_dash_c_with_a_tilde_is_refused(tmp_path: Path, path: str) -> None:
    """A quoted `~` reaches git literally (it enters cwd/~/…) while expanduser would check $HOME:
    a `~` anywhere in a -C path is refused, and nothing is expanded."""
    repo = _main_repo(tmp_path)
    literal = repo / "~" / "repo"
    literal.mkdir(parents=True)
    (literal / ".git").write_text(f"gitdir: {repo / '.git'}\n", encoding="utf-8")
    problem = role_scope.git_problem(f"git -C {path} log", str(repo))
    assert problem is not None and problem[0] == "role-bash-c-path", path


def test_dash_c_is_resolved_as_git_enters_it(tmp_path: Path) -> None:
    """Relative to cwd, symlinks first and then `..`, as chdir does; the rewrite carries the
    resolved absolute path, so git enters what was checked."""
    repo = _main_repo(tmp_path)
    wt = _linked_worktree(repo, tmp_path / "wt")
    (repo / "link").symlink_to(wt)
    call = role_scope.parse_git("git -C link log", str(repo))
    assert call.c_path == str(wt.resolve())
    assert role_scope.parse_git("git -C src/.. log", str(repo)).c_path == str(repo.resolve())
    # `link/..` is the worktree's parent to chdir, not the repo, and that is no working tree
    problem = role_scope.git_problem("git -C link/.. log", str(repo))
    assert problem is not None and problem[0] == "role-bash-c-path"


def test_a_c_path_that_cannot_be_encoded_is_refused(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    assert role_scope._resolve_c_path("x\ud800", str(repo)) is None


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_dash_c_against_a_real_git_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "real"
    repo.mkdir()
    run = {"cwd": str(repo), "check": True, "capture_output": True}
    subprocess.run(["git", "init", "-q"], **run)  # type: ignore[call-overload]
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", *ident, "commit", "-q", "--allow-empty", "-m", "i"], **run)  # type: ignore[call-overload]
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt)], **run)  # type: ignore[call-overload]
    assert role_scope.git_problem(f"git -C {wt} diff --stat", str(repo)) is None
    assert role_scope.git_problem(f"git -C {repo} log", str(wt)) is None


# --- the tool allowlist per role ---------------------------------------------------------------

OUTSIDE_READING = ["Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Agent",
                   "Task", "mcp__github__create_issue", "mcp__plugin_x__run", "TodoWrite",
                   "Monitor", "PowerShell", "Skill", "SlashCommand", "ListMcpResourcesTool",
                   "ReadMcpResourceTool", "BashOutput", "KillShell", "NewToolOfTomorrow", ""]


@pytest.mark.parametrize("role", GIT_ROLES)
@pytest.mark.parametrize("tool", OUTSIDE_READING)
def test_review_lenses_are_refused_every_tool_but_reading(role: str, tool: str) -> None:
    decision = role_scope.decide(_tool(tool, role))
    assert decision.block and decision.rule == "role-tool"


@pytest.mark.parametrize("role", [REVIEWER, SECURITY, GRADER, ARCHITECT])
@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
def test_every_role_may_read(role: str, tool: str) -> None:
    assert role_scope.decide(_tool(tool, role)) == role_scope.ALLOW


@pytest.mark.parametrize("tool", ["Bash", "Write", "Edit", "Agent", "mcp__x__y", "WebFetch"])
def test_the_grader_may_only_read(tool: str) -> None:
    payload = _bash("git diff", GRADER) if tool == "Bash" else _tool(tool, GRADER)
    decision = role_scope.decide(payload)
    assert decision.block and decision.rule == "role-tool"


def _write(file_path: Any, cwd: str | None = None) -> dict[str, Any]:
    payload = _tool("Write", ARCHITECT)
    payload["tool_input"] = {"file_path": file_path, "content": "x"}
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


def test_the_architect_may_write_and_nothing_else_outside_reading(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    design = _write(str(repo / "docs" / "design.md"), str(repo))
    assert role_scope.decide(design) == role_scope.ALLOW
    for tool in ("Edit", "MultiEdit", "NotebookEdit", "Bash", "WebSearch", "Task", "mcp__x__y"):
        payload = _bash("git diff", ARCHITECT) if tool == "Bash" else _tool(tool, ARCHITECT)
        assert role_scope.decide(payload).block, tool


def _architect_world(tmp_path: Path) -> tuple[Path, Path]:
    """A session repository with a linked worktree under a hidden directory (as this project keeps
    them), a submodule, a nested independent repository, and a home directory beside it."""
    repo = _main_repo(tmp_path)
    _linked_worktree(repo, repo / ".claude" / "worktrees" / "wt")
    _linked_worktree(repo, tmp_path / "sibling", "sib")
    sub = repo / "vendor" / "lib"
    sub.mkdir(parents=True)
    (repo / ".git" / "modules" / "lib").mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../../.git/modules/lib\n", encoding="utf-8")
    (repo / "fixtures" / "clone" / ".git").mkdir(parents=True)
    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (repo / "docs").mkdir()
    return repo, home


@pytest.mark.parametrize(
    "relative",
    ["docs/design.md", "docs/sdlc/new-feature/plan.md", "docs/architecture/payments.md",
     "docs/Design.MD", ".claude/worktrees/wt/docs/adr.md", "../sibling/docs/plan.md"],
)
def test_the_architect_may_write_markdown_documents_in_the_working_tree(
    tmp_path: Path, relative: str
) -> None:
    """Design documents under docs/ of the checkout or a linked worktree (the doc-delivery
    worktree is a sibling of the repository); directories that do not exist yet are fine."""
    repo, _ = _architect_world(tmp_path)
    for file_path in (relative, str(repo / relative)):
        assert role_scope.decide(_write(file_path, str(repo))) == role_scope.ALLOW, file_path


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        # the review's probe shapes: shell and git configuration, the agents' own settings
        ("home/.zshrc", "outside this session's repository"),
        ("home/.gitconfig", "outside this session's repository"),
        ("home/.config/git/config", "outside this session's repository"),
        ("home/.claude.json", "outside this session's repository"),
        ("repo/.mcp.json", "outside the docs/ directory"),
        ("repo/CLAUDE.md", "outside the docs/ directory"),
        ("repo/.claude/agents/x.md", "outside the docs/ directory"),
        # and around them
        ("repo/docs/CLAUDE.md", "agent instruction or skill file"),
        ("repo/docs/CLAUDE.local.md", "agent instruction or skill file"),
        ("repo/docs/AGENTS.md", "agent instruction or skill file"),
        ("repo/docs/gemini.MD", "agent instruction or skill file"),
        ("repo/docs/skills/x/SKILL.md", "agent instruction or skill file"),
        ("repo/docs/skill.md", "agent instruction or skill file"),
        ("repo/docs/notes.txt", "not a Markdown document"),
        ("repo/Makefile", "outside the docs/ directory"),
        ("repo/src/payments/README.md", "outside the docs/ directory"),
        ("repo/notes.md", "outside the docs/ directory"),
        ("repo/docs", "outside the docs/ directory"),
        ("repo/plugin/skills/x/SKILL.md", "outside the docs/ directory"),
        ("repo/docs/hook.md.sh", "not a Markdown document"),
        ("repo/.github/workflows/x.md", "hidden"),
        ("repo/docs/.hidden/x.md", "hidden"),
        ("repo/docs/.x.md", "hidden"),
        ("repo/vendor/lib/docs/a.md", "outside this session's working trees"),
        ("repo/fixtures/clone/docs/a.md", "outside this session's working trees"),
        ("other/docs/a.md", "outside this session's repository"),
    ],
)
def test_the_architect_may_write_only_design_documents(
    tmp_path: Path, target: str, reason: str
) -> None:
    repo, _ = _architect_world(tmp_path)
    decision = role_scope.decide(_write(str(tmp_path / target), str(repo)))
    assert decision.block and decision.rule == "role-write-path", target
    assert reason in decision.message, decision.message


@pytest.mark.parametrize(
    "relative",
    [".git/config", ".git/hooks/pre-commit", "sub/.git/config", ".GIT/config", "a/.Git/x.md",
     ".claude/settings.json", ".claude/settings.local.json", ".Claude/Settings.json",
     ".agentic-forge/config.json", "pkg/.claude/settings.json"],
)
def test_the_blocklist_stays_as_a_second_layer(tmp_path: Path, relative: str) -> None:
    repo = _main_repo(tmp_path)
    for file_path in (str(repo / relative), relative):
        decision = role_scope.decide(_write(file_path, str(repo)))
        assert decision.block and decision.rule == "role-write-path", file_path
        assert any(r in decision.message for r in (".git directory", "Claude Code settings",
                                                   "agentic-forge config")), decision.message


@pytest.mark.parametrize("relative", ["../x.md", "../unregistered/docs/a.md", "../../x.md"])
def test_a_sibling_escape_is_outside_the_working_trees(tmp_path: Path, relative: str) -> None:
    """From a worktree under .claude/worktrees, `..` lands in the main checkout's hidden space
    around its worktrees: that is outside every working tree, not a hidden document."""
    repo, _ = _architect_world(tmp_path)
    decision = role_scope.decide(_write(relative, str(repo / ".claude" / "worktrees" / "wt")))
    assert decision.block and "outside this session's working trees" in decision.message, (
        decision.message
    )


def test_a_link_cannot_lead_the_architect_out_of_bounds(tmp_path: Path) -> None:
    repo, home = _architect_world(tmp_path)
    (home / ".zshrc").write_text("", encoding="utf-8")
    (repo / "docs" / "out").symlink_to(home)
    (repo / "docs" / "agents").symlink_to(repo / ".claude")
    (repo / "docs" / "rc.md").symlink_to(home / ".zshrc")
    (repo / "innocent").symlink_to(repo / ".git")
    for relative in ("docs/out/notes.md", "docs/agents/agents/x.md", "docs/rc.md",
                     "innocent/notes.md", "innocent/docs/notes.md"):
        decision = role_scope.decide(_write(relative, str(repo)))
        assert decision.block and decision.rule == "role-write-path", relative


def test_an_architect_outside_any_repository_may_not_write(tmp_path: Path) -> None:
    decision = role_scope.decide(_write(str(tmp_path / "a.md"), str(tmp_path)))
    assert decision.block and "outside this session's repository" in decision.message


@pytest.mark.parametrize("file_path", [None, "", 5, "x\ud800"])
def test_an_architect_write_without_a_usable_path_is_refused(file_path: Any) -> None:
    decision = role_scope.decide(_write(file_path))
    assert decision.block and decision.rule == "role-write-path"


# --- the architect outside docs/: the repository's own feature folders --------------------------


def _feature_world(tmp_path: Path) -> Path:
    """A monorepo that keeps features and decisions outside docs/, in the checkout and in a linked
    worktree, beside the probe shapes the widening must not open."""
    repo, _ = _architect_world(tmp_path)
    for tree in (repo, repo / ".claude" / "worktrees" / "wt"):
        files = {
            "features/in-progress/foo/prd.md": "| **Status** | Draft |",
            "features/in-progress/foo/README.md": "x",
            "features/in-progress/bar/plan.md": "x",
            "features/architecture/adr/adr-066-x.md": "x",
            "features/architecture/adr/ADR-G14-y.md": "x",
            "doc/adr/0001-record.md": "x",
            "src/payments/notes.md": "x",
            "lib/adr/README.md": "x",
            "Feature Foo/prd.md": "x",
            ".github/foo/prd.md": "x",
            "features/in-progress/foo/.drafts/prd.md": "x",
            "plan.md": "x",
            "adr-001-top.md": "x",
            "vendor/lib/features/foo/prd.md": "x",
        }
        for relative, text in files.items():
            path = tree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (tree / "features" / "in-progress" / "foo" / "adr").mkdir()
    return repo


@pytest.mark.parametrize(
    "relative",
    [
        "features/in-progress/foo/tech-design.md",  # a feature folder: holds prd.md
        "features/in-progress/foo/prd.md",
        "features/in-progress/foo/Design.md",
        "features/in-progress/foo/adr-001-store.md",  # the unnumbered or numbered record name
        "features/in-progress/foo/adr-datastore.md",
        "features/in-progress/foo/adr/adr-001-store.md",  # an existing adr/ in a feature folder
        "features/in-progress/foo/adr/ADR-001.md",
        "features/in-progress/bar/tech-design.md",
        "features/architecture/adr/adr-067-cache.md",  # a series directory
        "features/architecture/adr/ADR-G15-z.md",
        "doc/adr/0002-use-x.md",  # adr-tools numbering, by its series member name
    ],
)
def test_the_architect_may_write_into_an_existing_feature_folder_or_adr_directory(
    tmp_path: Path, relative: str
) -> None:
    repo = _feature_world(tmp_path)
    wt = repo / ".claude" / "worktrees" / "wt"
    for file_path, cwd in ((relative, repo), (str(repo / relative), repo),
                           (relative, wt), (str(wt / relative), wt)):
        assert role_scope.decide(_write(file_path, str(cwd))) == role_scope.ALLOW, file_path


@pytest.mark.parametrize(
    ("relative", "reason"),
    [
        # the right directory, the wrong name: the widening is the role's documents only
        ("features/in-progress/foo/README.md", "not a feature document"),
        ("features/in-progress/foo/notes.md", "not a feature document"),
        ("features/architecture/adr/index.md", "not a feature document"),
        ("doc/adr/README.md", "not a feature document"),
        ("doc/adr/03-x.md", "not a feature document"),  # two digits: not adr-tools numbering
        # a directory that is not one the repository keeps for these documents
        ("features/in-progress/new-feature/prd.md", "outside the docs/ directory"),  # not there
        ("features/in-progress/bar/adr/adr-001-x.md", "outside the docs/ directory"),  # no adr/
        ("features/in-progress/foo/sub/tech-design.md", "outside the docs/ directory"),
        ("src/payments/tech-design.md", "outside the docs/ directory"),
        ("lib/adr/adr-001-x.md", "outside the docs/ directory"),  # an adr/ with no feature
        ("Feature Foo/tech-design.md", "outside the docs/ directory"),  # not a slug's shape
        ("tech-design.md", "outside the docs/ directory"),  # the top beside a plan.md
        ("adr-002-top.md", "outside the docs/ directory"),  # the top beside a record
        ("src/tech-design.md", "outside the docs/ directory"),
        # every earlier refusal still applies inside a qualifying directory
        (".github/foo/tech-design.md", "hidden"),
        ("features/in-progress/foo/.drafts/tech-design.md", "hidden"),
        ("features/in-progress/foo/CLAUDE.md", "agent instruction or skill file"),
        ("features/in-progress/foo/AGENTS.md", "agent instruction or skill file"),
        ("features/in-progress/foo/claude.local.md", "agent instruction or skill file"),
        ("features/in-progress/foo/GEMINI.md", "agent instruction or skill file"),
        ("features/in-progress/foo/SKILL.md", "agent instruction or skill file"),
        ("features/in-progress/foo/tech-design.txt", "not a Markdown document"),
        ("features/in-progress/foo/adr-001.sh", "not a Markdown document"),
        ("vendor/lib/features/foo/tech-design.md", "outside this session's working trees"),
    ],
)
def test_the_architect_outside_docs_is_refused_everything_else(
    tmp_path: Path, relative: str, reason: str
) -> None:
    repo = _feature_world(tmp_path)
    decision = role_scope.decide(_write(str(repo / relative), str(repo)))
    assert decision.block and decision.rule == "role-write-path", relative
    assert reason in decision.message, decision.message


def test_a_symlinked_feature_document_does_not_open_its_directory(tmp_path: Path) -> None:
    repo = _feature_world(tmp_path)
    folder = repo / "features" / "linked"
    folder.mkdir()
    (folder / "prd.md").symlink_to(repo / "features" / "in-progress" / "foo" / "prd.md")
    decision = role_scope.decide(_write(str(folder / "tech-design.md"), str(repo)))
    assert decision.block and "outside the docs/ directory" in decision.message


def test_a_link_cannot_lead_into_a_feature_folder_outside_the_repository(tmp_path: Path) -> None:
    repo = _feature_world(tmp_path)
    outside = tmp_path / "outside" / "foo"
    outside.mkdir(parents=True)
    (outside / "prd.md").write_text("x", encoding="utf-8")
    (repo / "features" / "away").symlink_to(outside, target_is_directory=True)
    (repo / "features" / "in-progress" / "foo" / "out.md").symlink_to(outside / "prd.md")
    for relative in ("features/away/tech-design.md", "features/in-progress/foo/out.md"):
        decision = role_scope.decide(_write(str(repo / relative), str(repo)))
        assert decision.block and "outside this session's repository" in decision.message


def test_a_link_inside_the_tree_is_judged_where_it_leads(tmp_path: Path) -> None:
    """A linked directory resolves first; the rule applies to the real directory."""
    repo = _feature_world(tmp_path)
    (repo / "shortcut").symlink_to(repo / "features" / "in-progress" / "foo")
    (repo / "to-src").symlink_to(repo / "src" / "payments")
    allowed = role_scope.decide(_write(str(repo / "shortcut" / "tech-design.md"), str(repo)))
    assert allowed == role_scope.ALLOW
    refused = role_scope.decide(_write(str(repo / "to-src" / "tech-design.md"), str(repo)))
    assert refused.block and "outside the docs/ directory" in refused.message


def test_an_unreadable_directory_is_not_a_feature_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _feature_world(tmp_path)
    real = os.scandir

    def deny(path: Any) -> Any:
        if str(path).endswith("foo"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(os, "scandir", deny)
    target = repo / "features" / "in-progress" / "foo" / "tech-design.md"
    decision = role_scope.decide(_write(str(target), str(repo)))
    assert decision.block and "outside the docs/ directory" in decision.message


def test_the_refusal_names_the_widened_scope() -> None:
    message = role_scope.decide(_tool("Edit", ARCHITECT)).message
    assert "in a feature folder or ADR directory it already keeps" in message


def test_hook_process_lets_the_architect_write_into_a_feature_folder(tmp_path: Path) -> None:
    repo = _feature_world(tmp_path)
    target = repo / "features" / "in-progress" / "foo" / "tech-design.md"
    payload = {**_tool("Write", ARCHITECT), "cwd": str(repo),
               "tool_input": {"file_path": str(target), "content": "c"}}
    done = _run_hook(json.dumps(payload), tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    payload["tool_input"]["file_path"] = str(target.with_name("README.md"))
    done = _run_hook(json.dumps(payload), tmp_path)
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_feature_folder_check_failing_closes_the_hook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An error in the new check refuses, through the hook's fail-closed path."""
    repo = _feature_world(tmp_path)
    monkeypatch.setattr(role_scope.artifact_home, "is_feature_dir", _boom)
    target = repo / "features" / "in-progress" / "foo" / "tech-design.md"
    payload = {**_write(str(target), str(repo)), "session_id": "feature-boom"}
    _stdin(monkeypatch, json.dumps(payload))
    assert role_scope_hook.main() == 0
    spec = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    assert "could not be checked (RuntimeError)" in spec["permissionDecisionReason"]


@pytest.mark.parametrize("tool", ["Bash", "Write", "Edit", "Agent", "mcp__x__y", "WebFetch"])
def test_the_main_session_is_always_allowed(tool: str) -> None:
    """No agent_type: the main session. The hook has nothing to say about it."""
    payload = _bash("rm -rf build && pytest", None) if tool == "Bash" else _tool(tool, None)
    assert role_scope.decide(payload) == role_scope.ALLOW


@pytest.mark.parametrize(
    "agent",
    ["reviewer", "security-engineer", "grader", "architect", "other-plugin:reviewer",
     "agentic-forge:software-engineer", "agentic-forge:qa-engineer", "Explore",
     "general-purpose", "AGENTIC-FORGE:REVIEWER", "agentic-forge:reviewer ", "", 123, None,
     ["agentic-forge:reviewer"]],
)
def test_other_agents_are_allowed(agent: Any) -> None:
    """Only the plugin's own namespaced roles are held: a bare `reviewer` is a user's own agent."""
    payload = _bash("docker ps", None)
    payload["agent_type"] = agent
    assert role_scope.decide(payload) == role_scope.ALLOW
    payload = _tool("Edit", None)
    payload["agent_type"] = agent
    assert role_scope.decide(payload) == role_scope.ALLOW


@pytest.mark.parametrize("tool_input", [None, {}, {"command": None}, {"command": 5}, "git diff"])
def test_a_lens_bash_call_without_a_command_string_is_refused(tool_input: Any) -> None:
    payload = _bash("x")
    payload["tool_input"] = tool_input
    decision = role_scope.decide(payload)
    assert decision.block and decision.rule == "role-bash-empty"


def test_a_missing_cwd_resolves_against_the_hook_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _main_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert role_scope.decide(_bash("git -C . diff")) == role_scope.ALLOW


# --- the refusal message ---------------------------------------------------------------------


def test_the_refusal_names_the_role_its_scope_and_who_runs_tools() -> None:
    message = role_scope.decide(_bash("python3 -m pytest", SECURITY)).message
    assert "security-engineer role" in message
    assert "Read" in message and "read-only git" in message and "git diff" in message
    assert "orchestrating skill" in message and "not by a review lens" in message
    assert "git show <base>:<path>" in message


def test_the_refusal_for_a_non_lens_role_does_not_call_it_a_lens() -> None:
    message = role_scope.decide(_tool("Edit", ARCHITECT)).message
    assert "architect role may use Glob, Grep, Read, Write" in message
    assert "orchestrating skill" in message and "review lens" not in message
    assert "read-only git" not in message and "git show" not in message
    assert "Write only Markdown design documents (.md)" in message


_SECRET = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.mark.parametrize(
    "command",
    [f"{_SECRET} diff", f"git --token={_SECRET} diff", f"git -C {_SECRET} diff",
     f"git {_SECRET}", f"git diff --output={_SECRET}", f"git diff; echo {_SECRET}"],
)
def test_the_refusal_carries_no_secret_from_the_command(command: str, tmp_path: Path) -> None:
    decision = role_scope.decide(_bash(command, REVIEWER, str(tmp_path)))
    assert decision.block
    assert _SECRET not in decision.message and _SECRET not in decision.evidence


def test_a_long_command_is_cut_in_the_evidence() -> None:
    decision = role_scope.decide(_bash("ls " + "x" * 500))
    assert decision.block and len(decision.evidence) <= 60


# --- the contract with the rest of the plugin ------------------------------------------------


def test_the_namespace_is_the_plugin_name() -> None:
    manifest = json.loads(
        (_REPO / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == role_scope.PLUGIN_NAMESPACE


@pytest.mark.parametrize("agent_type", sorted(role_scope.ROLE_TOOLS))
def test_each_allowlist_matches_its_role_file(agent_type: str) -> None:
    """The hook's allowlist is the role's own `tools:` list, specifiers aside."""
    name = agent_type.split(":", 1)[1]
    meta, _ = frontmatter.parse(
        (_REPO / "plugin" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    )
    declared = {t.strip().split("(", 1)[0] for t in str(meta["tools"]).split(",")}
    assert declared == set(role_scope.ROLE_TOOLS[agent_type])
    assert ("Bash" in declared) == (agent_type in role_scope.GIT_ROLES)


# --- the hook script ---------------------------------------------------------------------------


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_the_hook_script_knows_the_held_roles_without_the_library() -> None:
    assert role_scope_hook.HELD_ROLES == frozenset(role_scope.ROLE_TOOLS)


def test_hook_denies_with_the_pre_tool_use_decision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _stdin(monkeypatch, json.dumps({**_tool("Edit", REVIEWER), "cwd": str(tmp_path)}))
    assert role_scope_hook.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    out = json.loads(captured.out)
    assert set(out) == {"hookSpecificOutput"}
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["permissionDecision"] == "deny"
    assert "reviewer role" in spec["permissionDecisionReason"]


@pytest.mark.parametrize(
    "payload",
    [_bash("rm -rf build", None), _tool("mcp__x__y", None), _tool("Read", REVIEWER),
     _bash("docker ps", "agentic-forge:software-engineer"),
     {**_bash("docker ps", None), "agent_type": ["agentic-forge:reviewer"]}],
)
def test_hook_allows_silently(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, json.dumps(payload))
    assert role_scope_hook.main() == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '"a string"', "null", "{"])
def test_hook_fails_open_silently_on_a_payload_it_cannot_read(
    text: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stdin(monkeypatch, text)
    assert role_scope_hook.main() == 0
    assert capsys.readouterr() == ("", "")


def _boom(payload: dict[str, Any]) -> Any:
    raise RuntimeError("kaboom")


@pytest.mark.parametrize("payload", [_bash("git diff"), _tool("Read", GRADER),
                                     _tool("Write", ARCHITECT)])
def test_hook_crash_fails_closed_for_a_held_role_and_is_recorded(
    payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """A boundary that opens on an error is no boundary against content written to cause one."""
    monkeypatch.setattr(role_scope, "respond", _boom)
    body = json.dumps({**payload, "cwd": str(tmp_path), "session_id": "crash"})
    _stdin(monkeypatch, body)
    assert role_scope_hook.main() == 0
    out = json.loads(capsys.readouterr().out)
    spec = out["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    assert "could not be checked (RuntimeError)" in spec["permissionDecisionReason"]
    assert "kaboom" not in spec["permissionDecisionReason"]
    notice = out["systemMessage"]
    assert "role-scope hook crashed: RuntimeError" in notice and "failing closed" in notice
    assert "kaboom" not in notice  # the type only: an exception can repeat the command
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    assert "kaboom" in log.read_text(encoding="utf-8")
    _stdin(monkeypatch, body)
    assert role_scope_hook.main() == 0
    again = json.loads(capsys.readouterr().out)
    assert again["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "systemMessage" not in again  # announced once per session, still refused and recorded
    records = log.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(r)["message"] for r in records] == ["RuntimeError: kaboom"] * 2


def test_hook_fails_closed_when_the_library_cannot_be_imported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    import agentic_forge

    monkeypatch.delattr(agentic_forge, "role_scope")
    monkeypatch.setitem(sys.modules, "agentic_forge.role_scope", None)
    _stdin(monkeypatch, json.dumps({**_bash("git diff"), "cwd": str(tmp_path)}))
    assert role_scope_hook.main() == 0
    spec = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    assert "could not be checked (ModuleNotFoundError)" in spec["permissionDecisionReason"]


def test_hook_fails_closed_even_when_the_record_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(role_scope, "respond", _boom)
    monkeypatch.setattr(diagnostics, "hook_crash", _boom)
    _stdin(monkeypatch, json.dumps({**_bash("git diff"), "cwd": str(tmp_path)}))
    assert role_scope_hook.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "systemMessage" not in out


@pytest.mark.parametrize(
    "agent", ["agentic-forge:software-engineer", "reviewer", None, ["agentic-forge:reviewer"]]
)
def test_hook_exits_before_the_library_for_a_caller_that_is_not_held(
    agent: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Not a held role, our namespace or not: the hook never reaches the library, so nothing in it
    can fail for these callers."""
    monkeypatch.setattr(role_scope, "respond", _boom)
    _stdin(monkeypatch, json.dumps({**_bash("pytest", agent), "cwd": str(tmp_path)}))
    assert role_scope_hook.main() == 0
    assert capsys.readouterr() == ("", "")


def test_hook_keeps_its_refusal_when_recording_it_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(diagnostics, "emit", _boom)
    _stdin(monkeypatch, json.dumps({**_bash("git push"), "cwd": str(tmp_path)}))
    assert role_scope_hook.main() == 0
    spec = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"


def test_hook_records_a_refusal_with_its_rule_when_diagnostics_are_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    _stdin(monkeypatch, json.dumps({**_bash("git push", SECURITY), "cwd": str(tmp_path),
                                    "session_id": "s"}))
    assert role_scope_hook.main() == 0
    capsys.readouterr()
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    event = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert event["component"] == "role-scope-hook" and event["kind"] == "block"
    assert event["context"]["rule"] == "role-bash-subcommand"
    assert event["context"]["agent_type"] == SECURITY and event["context"]["tool"] == "Bash"


def _run_hook(stdin: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AGENTIC_FORGE_STATE_HOME": str(tmp_path / "state")}
    return subprocess.run(
        [sys.executable, str(_HOOK)], input=stdin, capture_output=True, text=True,
        cwd=str(tmp_path), env=env, timeout=60, check=False,
    )


def test_hook_process_speaks_json_on_stdout(tmp_path: Path) -> None:
    deny = _run_hook(json.dumps({**_bash("pytest -q", REVIEWER), "cwd": str(tmp_path)}), tmp_path)
    assert deny.returncode == 0 and deny.stderr == ""
    spec = json.loads(deny.stdout)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    assert "orchestrating skill" in spec["permissionDecisionReason"]
    allow = _run_hook(json.dumps({**_bash("git log -1", REVIEWER), "cwd": str(tmp_path)}), tmp_path)
    assert allow.returncode == 0 and allow.stderr == ""
    spec = json.loads(allow.stdout)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "allow"
    words = shlex.split(spec["updatedInput"]["command"])
    assert words[:1] == ["/usr/bin/env"] and words[-4:] == ["log", "--no-ext-diff",
                                                            "--no-textconv", "-1"]
    broken = _run_hook("{not json", tmp_path)
    assert (broken.returncode, broken.stdout, broken.stderr) == (0, "", "")
    main_session = _run_hook(json.dumps(_bash("rm -rf build", None)), tmp_path)
    assert (main_session.returncode, main_session.stdout, main_session.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "command", ['git -C "x\ud800" log', "git log \ud800", "git log 'a\udc80'"]
)
def test_hook_process_refuses_a_lone_surrogate(tmp_path: Path, command: str) -> None:
    """JSON can carry a lone surrogate (`\\ud800`), which no path or file can hold."""
    body = json.dumps({**_bash(command, REVIEWER), "cwd": str(tmp_path)})
    assert "\\ud" in body  # escaped, as JSON.stringify sends it
    done = _run_hook(body, tmp_path)
    assert done.returncode == 0 and done.stderr == ""
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_process_lets_the_architect_write_a_design_document(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    payload = {**_tool("Write", ARCHITECT), "cwd": str(repo),
               "tool_input": {"file_path": str(repo / "docs" / "sdlc" / "x" / "plan.md"),
                              "content": "c"}}
    done = _run_hook(json.dumps(payload), tmp_path)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "target", ["home/.zshrc", "home/.gitconfig", "home/.config/git/config", "home/.claude.json",
               "repo/.mcp.json", "repo/CLAUDE.md", "repo/.claude/agents/x.md"],
)
def test_hook_process_refuses_the_architect_the_review_probe_paths(
    tmp_path: Path, target: str
) -> None:
    repo = _main_repo(tmp_path)
    payload = {**_tool("Write", ARCHITECT), "cwd": str(repo),
               "tool_input": {"file_path": str(tmp_path / target), "content": "x"}}
    done = _run_hook(json.dumps(payload), tmp_path)
    assert done.returncode == 0 and done.stderr == ""
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_process_refuses_an_architect_write_to_an_unencodable_path(tmp_path: Path) -> None:
    payload = {**_tool("Write", ARCHITECT), "cwd": str(tmp_path),
               "tool_input": {"file_path": str(tmp_path / "x\ud800.md"), "content": "c"}}
    done = _run_hook(json.dumps(payload), tmp_path)
    assert done.returncode == 0 and done.stderr == ""
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- what runs is what was checked: the rewrite ----------------------------------------------


def _updated(payload: dict[str, Any]) -> dict[str, Any]:
    decision, out = role_scope.respond(payload)
    assert not decision.block and out is not None
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and spec["permissionDecision"] == "allow"
    return dict(spec["updatedInput"])


def test_an_allowed_git_call_is_answered_with_allow_and_the_hardened_command() -> None:
    """The PreToolUse contract: `updatedInput` under `hookSpecificOutput` replaces the WHOLE input,
    so the other fields are carried; a request to leave the sandbox is not."""
    payload = _bash("git log -1 'HEAD^'")
    payload["tool_input"].update(
        {"description": "d", "timeout": 5000, "dangerouslyDisableSandbox": True}
    )
    updated = _updated(payload)
    assert updated == {"command": updated["command"], "description": "d", "timeout": 5000}
    words = shlex.split(updated["command"])
    assert words[: len(role_scope.HARDENED_PREFIX)] == list(role_scope.HARDENED_PREFIX)
    assert words[len(role_scope.HARDENED_PREFIX):] == [
        "log", "--no-ext-diff", "--no-textconv", "-1", "HEAD^"
    ]


def test_the_hardened_prefix_clears_the_environment_and_disables_configured_programs() -> None:
    prefix = role_scope.HARDENED_PREFIX
    assert prefix[0] == "/usr/bin/env"
    git_at = prefix.index("git")
    assert prefix[git_at - 1] == "GIT_NO_LAZY_FETCH=1"
    unset = {prefix[i + 1] for i in range(1, git_at - 1, 2) if prefix[i] == "-u"}
    assert len(unset) == (git_at - 2) // 2 == len(role_scope.UNSET_ENV)
    for name in ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "PAGER", "GIT_DIR", "GIT_WORK_TREE",
                 "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT",
                 "GIT_CONFIG_PARAMETERS", "GIT_EXEC_PATH", "GIT_SSH", "GIT_SSH_COMMAND",
                 "GIT_ASKPASS", "SSH_ASKPASS", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_ATTR_SOURCE",
                 "GIT_TRACE", "GIT_TRACE2_EVENT"):
        assert name in unset, name
    config = [prefix[i + 1] for i in range(git_at, len(prefix) - 1) if prefix[i] == "-c"]
    assert config == ["safe.bareRepository=explicit", "core.fsmonitor=false",
                      "core.hooksPath=/dev/null", "diff.submodule=log",
                      "log.showSignature=false", "format.pretty=medium",
                      "core.attributesFile=/dev/null", "gpg.program=/dev/null",
                      "gpg.ssh.program=/dev/null", "gpg.x509.program=/dev/null"]
    assert prefix[-2:] == ("--no-pager", f"--attr-source={role_scope.EMPTY_TREE}")
    assert role_scope.EMPTY_TREE == "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    assert role_scope.LEGACY_PREFIX == prefix[:-1]


@pytest.mark.parametrize(
    ("version", "expected"),
    [((2, 39), False), ((2, 40), False), ((2, 41), True), ((2, 43), True), ((3, 0), True),
     (None, True)],
)
def test_attr_source_follows_the_git_version(
    version: Any, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--attr-source arrived in git 2.41.0 (its RelNotes): 2.40.x gets no option, 2.41 does, and
    an unknown version gets it, so a git that rejects it fails to start instead of running
    without it."""
    monkeypatch.setattr(role_scope, "_git_version", lambda: version)
    assert role_scope.git_supports_attr_source() is expected
    words = shlex.split(_updated(_bash("git status"))["command"])
    assert (f"--attr-source={role_scope.EMPTY_TREE}" in words) is expected


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [("git version 2.43.0\n", (2, 43)), ("git version 2.39.5 (Apple Git-154)\n", (2, 39)),
     ("git version 2.40.4\n", (2, 40)), ("git version 2.41.0\n", (2, 41)),
     ("git version 2.45.1.windows.1\n", (2, 45)), ("nonsense", None), ("", None)],
)
def test_the_git_version_is_parsed(
    stdout: str, expected: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] <= 5
        assert os.path.isabs(argv[0]) and argv[1:] == ["--version"]
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git")
    real_cache = _REAL_GIT_VERSION
    monkeypatch.setattr(subprocess, "run", fake_run)
    real_cache.cache_clear()
    try:
        assert real_cache() == expected
    finally:
        real_cache.cache_clear()


@pytest.mark.parametrize("found", [None, "git", "bin/git", "./git"])
def test_only_an_absolute_git_is_asked(found: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative PATH entry could find a `git` in the reviewed checkout: never run it. The
    version is then unknown, which adds --attr-source and so fails closed on an old git."""
    def must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("ran a git that is not an absolute path")

    real_cache = _REAL_GIT_VERSION
    monkeypatch.setattr(shutil, "which", lambda name: found)
    monkeypatch.setattr(subprocess, "run", must_not_run)
    real_cache.cache_clear()
    try:
        assert real_cache() is None
    finally:
        real_cache.cache_clear()


def test_a_git_that_cannot_be_asked_counts_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("git")

    real_cache = _REAL_GIT_VERSION
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(subprocess, "run", no_git)
    real_cache.cache_clear()
    try:
        assert real_cache() is None
    finally:
        real_cache.cache_clear()


@pytest.mark.parametrize(
    ("command", "flags"),
    [("git diff", ["--no-ext-diff", "--no-textconv"]),
     ("git show HEAD", ["--no-ext-diff", "--no-textconv"]),
     ("git log -p", ["--no-ext-diff", "--no-textconv"]),
     ("git blame f", ["--no-textconv"]), ("git grep x", ["--no-textconv"]),
     ("git status", []), ("git cat-file -p HEAD", []), ("git describe", [])],
)
def test_the_hardening_flags_follow_the_subcommand(command: str, flags: list[str]) -> None:
    words = shlex.split(_updated(_bash(command))["command"])[len(role_scope.HARDENED_PREFIX):]
    sub = command.split()[1]
    assert words[: 1 + len(flags)] == [sub, *flags]
    assert words[1 + len(flags):] == command.split()[2:]


def test_dash_c_is_rewritten_to_the_resolved_path(tmp_path: Path) -> None:
    repo = _main_repo(tmp_path)
    words = shlex.split(_updated(_bash("git -C src/.. diff", cwd=str(repo)))["command"])
    rest = words[len(role_scope.HARDENED_PREFIX):]
    assert rest[:3] == ["-C", str(repo.resolve()), "diff"]


@pytest.mark.parametrize("command", ["git log -1", "git -C . diff -- 'a b'", "git blame f",
                                     "git log '=x' 'HEAD^'"])
def test_the_rewrite_is_a_fixed_point(command: str, tmp_path: Path) -> None:
    """A model may send the rewritten command back; it is checked as the plain one and comes out
    the same."""
    repo = _main_repo(tmp_path)
    once = _updated(_bash(command, cwd=str(repo)))["command"]
    assert _updated(_bash(once, cwd=str(repo)))["command"] == once


def test_the_hardened_prefix_does_not_smuggle_options(tmp_path: Path) -> None:
    prefix = shlex.join(role_scope.HARDENED_PREFIX)
    for tail in ("-c core.pager=x log", "--exec-path=/x log", "push"):
        decision = role_scope.decide(_bash(f"{prefix} {tail}"))
        assert decision.block, tail


@pytest.mark.parametrize("word", ["=ls", "=", "~", "~/x", "a'b", "*", "{a,b}", "HEAD^", "#x",
                                  "a b", "é", "-", "", "x=~/y", "--x==git", "plain", "'", "''"])
def test_every_word_is_single_quoted(word: str) -> None:
    """Unconditionally: even a word shlex would leave bare (zsh's MAGIC_EQUAL_SUBST rewrites a
    bare `--x==cmd`)."""
    call = role_scope.GitCall(None, "log", ("--", word))
    command = role_scope.hardened_command(call)
    words = shlex.split(command)
    assert words[-1] == word
    assert command == " ".join("'" + w.replace("'", "'\"'\"'") + "'" for w in words)


# --- the matcher reaches every tool but the read tools ---------------------------------------


def _role_matcher() -> str:
    hooks = json.loads((_REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    matchers = [
        group["matcher"] for group in hooks["hooks"]["PreToolUse"]
        if any("role_scope.py" in h["command"] for h in group["hooks"])
    ]
    assert len(matchers) == 1
    return str(matchers[0])


@pytest.mark.parametrize("tool", [*OUTSIDE_READING, "Bash", "ReadX", "XRead", "Grep2"])
def test_the_matcher_reaches_every_tool_but_the_read_tools(tool: str) -> None:
    """Claude Code tests a matcher with JavaScript's RegExp `test` (unanchored); this pattern means
    the same to Python's `re.search`. A tool that never reaches the hook is never refused."""
    assert re.search(_role_matcher(), tool) is not None


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
def test_the_matcher_skips_the_read_tools(tool: str) -> None:
    assert re.search(_role_matcher(), tool) is None
