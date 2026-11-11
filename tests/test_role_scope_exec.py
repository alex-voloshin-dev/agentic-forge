"""The role-scope hook, end to end (ADR 0106): what the hook lets run is run, through bash and
through zsh with extended globbing, in a real repository whose config, environment and files are
set up to make git run a program or write a file.

The finding, config and environment cases first spring their trap with the raw command (the
control), then show that the hook either refuses the command or rewrites it into a form that does
not spring it. The look-alike cases test the allowed path only: the command the hook lets run
springs nothing.

Every subprocess has a 20 s timeout and runs in the foreground; nothing is left behind.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agentic_forge import role_scope

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None
    or not Path("/usr/bin/env").exists(),
    reason="needs git, bash and /usr/bin/env",
)

REVIEWER = "agentic-forge:reviewer"
_TIMEOUT = 20
_IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
_HAS_ZSH = shutil.which("zsh") is not None
SHELLS = [
    "bash",
    pytest.param("zsh", marks=pytest.mark.skipif(not _HAS_ZSH, reason="zsh is not installed")),
]


def _argv(shell: str, command: str) -> list[str]:
    if shell == "bash":
        return ["bash", "--norc", "--noprofile", "-c", command]
    if shell == "zsh-magic":  # MAGIC_EQUAL_SUBST expands after a `=` inside a word too
        return ["zsh", "-f", "-c", "setopt extendedglob magicequalsubst; " + command]
    return ["zsh", "-f", "-c", "setopt extendedglob; " + command]


@dataclass
class World:
    """A repository whose own config runs a marker program for every external-program hook git
    has, a linked worktree holding a planted repository (``wt/wt``), a planted repository under a
    literal ``~`` directory, files whose names are options, and a marker program."""

    root: Path
    repo: Path
    mark: Path
    marker_log: Path
    env: dict[str, str]

    def reset(self) -> None:
        for path in (self.marker_log, self.repo / "WRITTEN"):
            if path.exists():
                path.unlink()

    def sprung(self) -> list[str]:
        """What the last run did that it must not: ran the marker, or wrote a file."""
        out = []
        if self.marker_log.exists():
            out.append("ran: " + self.marker_log.read_text(encoding="utf-8").strip())
        if (self.repo / "WRITTEN").exists():
            out.append("wrote WRITTEN")
        return out

    def run(self, shell: str, command: str, env: dict[str, str] | None = None) -> None:
        self.reset()
        subprocess.run(
            _argv(shell, command), cwd=str(self.repo), env={**self.env, **(env or {})},
            stdin=subprocess.DEVNULL, capture_output=True, timeout=_TIMEOUT, check=False,
        )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *_IDENT, *args], cwd=str(cwd), check=True, capture_output=True, timeout=_TIMEOUT,
        stdin=subprocess.DEVNULL,
    )


def _repo_with_a_change(path: Path, name: str = "f.txt") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    (path / name).write_text("one\n", encoding="utf-8")
    _git(path, "add", name)
    _git(path, "commit", "-q", "-m", "init")
    (path / name).write_text("one\ntwo\n", encoding="utf-8")


def _base(tmp_path: Path, repo_name: str = "r") -> World:
    """A marker program, a private home and environment, and the path a repository will take."""
    root = tmp_path.resolve()
    home = root / "home"
    home.mkdir(exist_ok=True)
    marker_log = root / "MARK"
    mark = root / "mark.sh"
    mark.write_text(
        f'#!/bin/sh\necho "$0 $*" >> "{marker_log}"\ncat "$1" 2>/dev/null\nexit 0\n',
        encoding="utf-8",
    )
    mark.chmod(0o755)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    return World(root, root / repo_name, mark, marker_log, env)


@pytest.fixture
def world(tmp_path: Path) -> World:
    base = _base(tmp_path)
    root, mark, marker_log, env = base.root, base.mark, base.marker_log, base.env

    repo = root / "r"
    repo.mkdir()
    (repo / ".gitattributes").write_text("*.txt diff=conv\n", encoding="utf-8")
    _repo_with_a_change(repo, "a.txt")
    hooks = root / "hooks"
    hooks.mkdir()
    (hooks / "post-index-change").write_text(
        f'#!/bin/sh\necho post-index-change >> "{marker_log}"\n', encoding="utf-8"
    )
    (hooks / "post-index-change").chmod(0o755)
    for key, value in (("diff.external", str(mark)), ("diff.conv.textconv", str(mark)),
                       ("core.fsmonitor", str(mark)), ("core.hooksPath", str(hooks)),
                       ("core.pager", str(mark))):
        _git(repo, "config", key, value)
    _git(repo, "worktree", "add", "-q", "wt")
    for planted in (repo / "wt" / "wt", repo / "~" / "p"):  # M1, B2
        _repo_with_a_change(planted)
        _git(planted, "config", "diff.external", str(mark))
    for name in ("--output=WRITTEN", "-nOcat", "f1", "f2"):  # B1, M2, M3
        (repo / name).write_text(name + "\n", encoding="utf-8")
    world = World(root, repo, mark, marker_log, env)
    world.reset()
    return world


def _what_runs(world: World, command: str) -> str | None:
    """The command the hook lets run for a reviewer: None on a refusal, the rewritten command on an
    allow (this hook never passes a lens's git call through unchanged)."""
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse", "agent_type": REVIEWER, "tool_name": "Bash",
        "cwd": str(world.repo), "tool_input": {"command": command},
    }
    decision, out = role_scope.respond(payload)
    if decision.block:
        return None
    assert out is not None
    return str(out["hookSpecificOutput"]["updatedInput"]["command"])


# --- the round-2 findings: the raw shape springs its trap; the hook refuses it ----------------

# (finding, the raw command, the shell the trap needs, extra environment)
FINDINGS = [
    ("B1 quote desync", "git diff --line-prefix=\"\\\"'\" {--output=WRITTEN,--stat} "
                        "--src-prefix='\\'", "bash", {}),
    ("B2 quoted tilde", 'git -C "~/p" diff', "bash", {}),
    ("M1 stacked -C", "git -C wt -C wt diff", "bash", {}),
    ("M2 zsh ^", "git log -1 --o^x", "zsh", {}),
    ("M3 --no-index", "git diff --no-index f1 f2", "bash", {"GIT_EXTERNAL_DIFF": "MARK"}),
    # round 3: `--text` is cat-file's abbreviation of --textconv
    ("cat-file --text", "git cat-file --text HEAD:a.txt", "bash", {}),
]


def _env(world: World, extra: dict[str, str]) -> dict[str, str]:
    return {k: (str(world.mark) if v == "MARK" else v) for k, v in extra.items()}


@pytest.mark.parametrize(("finding", "command", "trap_shell", "extra"), FINDINGS,
                         ids=[f[0] for f in FINDINGS])
def test_each_finding_springs_raw_and_is_refused(
    world: World, finding: str, command: str, trap_shell: str, extra: dict[str, str]
) -> None:
    if trap_shell == "zsh" and not _HAS_ZSH:
        pytest.skip("zsh is not installed")
    world.run(trap_shell, command, _env(world, extra))
    assert world.sprung(), f"control: {finding} no longer springs raw; the test proves nothing"
    assert _what_runs(world, command) is None, finding


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "command",
    [
        # B1's neighbours: quoting the scanner and the shells agree on
        "git diff --line-prefix=\"'\" '{--output=WRITTEN,--stat}' --src-prefix=\"'\"",
        "git log -1 \"'\" '*' \"'\"",
        "git log -1 -- '*' '{--output=WRITTEN,--stat}'",
        # B2's and M1's: one -C, no tilde
        "git -C wt diff", "git -C . diff", "git log -1 -- '~/p'",
        # M2's: a quoted ^ and the zsh glob qualifiers, quoted
        "git log -1 'HEAD^'", "git log -1 -- '--o^x' '*(e:true:)' '^x'",
        # M3's: the repository's own diff, with the program in the environment
        "git diff", "git diff --stat", "git show", "git log -p -1",
    ],
)
def test_what_the_hook_lets_run_springs_nothing(world: World, shell: str, command: str) -> None:
    executed = _what_runs(world, command)
    assert executed is not None, command
    world.run(shell, executed, {"GIT_EXTERNAL_DIFF": str(world.mark)})
    assert world.sprung() == [], (command, executed)


# --- configured programs: in the repository's config and in the environment -----------------

CONFIGURED = ["git diff", "git log -p -1", "git show", "git blame a.txt", "git status",
              "git diff --stat", "git grep -n one", "git -C wt diff", "git ls-files"]


def test_the_repository_config_springs_raw(world: World) -> None:
    """The control: each program hook is live in the fixture."""
    seen = set()
    for command in ("git diff", "git log -p -1", "git blame a.txt", "git status"):
        world.run("bash", command)
        assert world.sprung(), command
        seen.add(world.marker_log.read_text(encoding="utf-8"))
    log = "".join(seen)
    assert "post-index-change" in log  # the hook ran on status
    assert " 2 " in log  # the fsmonitor protocol's version argument
    assert "/a.txt" in log  # an external diff or textconv was handed the file


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("command", CONFIGURED)
def test_the_rewrite_runs_no_program_from_the_repository_config(
    world: World, shell: str, command: str
) -> None:
    executed = _what_runs(world, command)
    assert executed is not None
    world.run(shell, executed)
    assert world.sprung() == [], executed


def _env_traps(world: World) -> dict[str, dict[str, str]]:
    mark = str(world.mark)
    planted = world.root / "r" / "~" / "p"  # the fixture's planted repository, configured
    return {
        "GIT_EXTERNAL_DIFF": {"GIT_EXTERNAL_DIFF": mark},
        "GIT_CONFIG_COUNT": {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "diff.external",
                             "GIT_CONFIG_VALUE_0": mark, "GIT_CONFIG_KEY_1": "core.fsmonitor",
                             "GIT_CONFIG_VALUE_1": mark},
        "GIT_CONFIG_PARAMETERS": {"GIT_CONFIG_PARAMETERS": f"'diff.external'='{mark}'"},
        "GIT_DIR": {"GIT_DIR": str(planted / ".git"), "GIT_WORK_TREE": str(planted)},
        "GIT_TRACE": {"GIT_TRACE": str(world.repo / "WRITTEN")},
    }


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "trap", ["GIT_EXTERNAL_DIFF", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_DIR",
             "GIT_TRACE"],
)
def test_the_rewrite_runs_no_program_from_the_environment(
    tmp_path: Path, world: World, shell: str, trap: str
) -> None:
    """A clean repository (nothing configured), so only the environment can spring the trap."""
    clean = tmp_path / "clean"
    _repo_with_a_change(clean)
    world.repo = clean
    env = _env_traps(world)[trap]
    world.run("bash", "git diff", env)
    assert world.sprung(), f"control: {trap} does not spring raw"
    executed = _what_runs(world, "git diff")
    assert executed is not None
    world.run(shell, executed, env)
    assert world.sprung() == [], executed


# --- the rewritten words reach git exactly as checked ----------------------------------------

ARGV_CASES = [
    "git log --x==git '--y==git' x==git",
    "git log -- '*' '?' '[ab]' '{a,b}' 'HEAD^' '^x' '#x' '~' '~/x' '=ls' '!x' 'a b' ''",
    'git log --grep "it\'s" --format="%H %s" -- "*(e:true:)"',
    "git show 'HEAD@{1}' x=~/y --opt=~",
    'git log "x"=y "--o^x" "-nO"cat',
    "git -C . diff -- 'é'",
]


@pytest.mark.parametrize(
    "shell",
    [*SHELLS, pytest.param("zsh-magic", marks=pytest.mark.skipif(not _HAS_ZSH, reason="no zsh"))],
)
@pytest.mark.parametrize("command", ARGV_CASES)
def test_git_receives_exactly_the_checked_words(
    world: World, tmp_path: Path, shell: str, command: str
) -> None:
    """A stand-in `git` on PATH records its argv: whatever the shell and its globbing options,
    git gets the words the hook checked, in the files' presence that a glob would match."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "argv"
    (bin_dir / "git").write_text(
        f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\0' \"$a\"; done > \"{argv_file}\"\n",
        encoding="utf-8",
    )
    (bin_dir / "git").chmod(0o755)
    executed = _what_runs(world, command)
    assert executed is not None, command
    call = role_scope.parse_git(command, str(world.repo))
    world.run(shell, executed, {"PATH": f"{bin_dir}{os.pathsep}{world.env['PATH']}"})
    got = argv_file.read_bytes().decode("utf-8").split("\0")[:-1]
    expected = shlex.split(executed)[shlex.split(executed).index("git") + 1:]
    assert got == expected
    assert got[len(got) - len(call.args):] == list(call.args)
    assert world.sprung() == []


def _fake_git(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    argv_file = tmp_path / "argv"
    (bin_dir / "git").write_text(
        f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\0' \"$a\"; done > \"{argv_file}\"\n",
        encoding="utf-8",
    )
    (bin_dir / "git").chmod(0o755)
    return bin_dir, argv_file


@pytest.mark.skipif(not _HAS_ZSH, reason="zsh is not installed")
def test_magic_equal_subst_rewrites_a_bare_word_but_not_a_quoted_one(
    world: World, tmp_path: Path
) -> None:
    """The control: zsh with MAGIC_EQUAL_SUBST turns a bare `--x==git` into a path, so the raw
    command is not what the hook checked; the rewrite, every word single-quoted, is."""
    bin_dir, argv_file = _fake_git(tmp_path)
    path = {"PATH": f"{bin_dir}{os.pathsep}{world.env['PATH']}"}
    world.run("zsh-magic", "git log --x==git", path)
    raw = argv_file.read_bytes().decode("utf-8").split("\0")[:-1]
    assert raw[-1] != "--x==git" and raw[-1].startswith("--x=/"), raw
    executed = _what_runs(world, "git log --x==git")
    assert executed is not None
    world.run("zsh-magic", executed, path)
    assert argv_file.read_bytes().decode("utf-8").split("\0")[-2] == "--x==git"


# --- round 3: submodules, signatures and filters ---------------------------------------------


@pytest.fixture
def sub_world(tmp_path: Path) -> World:
    """A superproject with a changed submodule whose own config runs the marker as its external
    diff, the program a nested inline diff would start."""
    world = _base(tmp_path)
    sub = world.root / "sub"
    _repo_with_a_change(sub)
    subprocess.run(["git", "checkout", "-q", "--", "."], cwd=str(sub), check=True,
                   capture_output=True, timeout=_TIMEOUT)
    _repo_with_a_change(world.repo, "a.txt")
    _git(world.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "sub")
    _git(world.repo, "commit", "-q", "-m", "sub")
    (world.repo / "sub" / "f.txt").write_text("changed\n", encoding="utf-8")
    _git(world.repo / "sub", "config", "diff.external", str(world.mark))
    world.reset()
    return world


@pytest.mark.parametrize(
    "command",
    ["git diff --no-ext-diff --submodule=diff", "git log -p -1 --submodule=diff"],
)
def test_an_explicit_submodule_diff_springs_raw_and_is_refused(
    sub_world: World, command: str
) -> None:
    """--no-ext-diff does not reach the nested diff git starts in the submodule."""
    sub_world.run("bash", command)
    assert sub_world.sprung(), f"control: {command} runs no nested diff program"
    assert _what_runs(sub_world, command) is None, command


@pytest.mark.parametrize("shell", SHELLS)
def test_a_configured_submodule_diff_is_shown_as_a_log(sub_world: World, shell: str) -> None:
    """`diff.submodule=diff` in config: the rewrite without `-c diff.submodule=log` still springs
    the nested diff's program (the control); the rewrite does not."""
    _git(sub_world.repo, "config", "diff.submodule", "diff")
    executed = _what_runs(sub_world, "git diff")
    assert executed is not None and "'diff.submodule=log'" in executed
    sub_world.run(shell, executed.replace("'-c' 'diff.submodule=log' ", ""))
    assert sub_world.sprung(), "control: the configured nested diff does not spring"
    sub_world.run(shell, executed)
    assert sub_world.sprung() == []


@pytest.fixture
def sig_world(tmp_path: Path) -> World:
    """A repository whose HEAD carries a signature, with the marker as its gpg program."""
    world = _base(tmp_path)
    _repo_with_a_change(world.repo)
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=str(world.repo), check=True,
                          capture_output=True, text=True, timeout=_TIMEOUT).stdout.strip()
    parent = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(world.repo), check=True,
                            capture_output=True, text=True, timeout=_TIMEOUT).stdout.strip()
    body = (f"tree {tree}\nparent {parent}\nauthor t <t@e> 1 +0000\ncommitter t <t@e> 1 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n \n -----END PGP SIGNATURE-----\n\nsigned\n")
    signed = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=str(world.repo), check=True,
        input=body, capture_output=True, text=True, timeout=_TIMEOUT,
    ).stdout.strip()
    _git(world.repo, "update-ref", "HEAD", signed)
    _git(world.repo, "config", "gpg.program", str(world.mark))
    world.reset()
    return world


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "config",
    [
        # a tracked file the user includes into their config, as the review's probe did
        {"include.path": "../shared.gitconfig"},
        {"format.pretty": "%h %G?"},
    ],
    ids=["included log.showSignature", "format.pretty with %G"],
)
def test_signature_display_from_config_springs_raw_but_not_rewritten(
    sig_world: World, shell: str, config: dict[str, str]
) -> None:
    (sig_world.repo / "shared.gitconfig").write_text(
        f"[log]\n\tshowSignature = true\n[gpg]\n\tprogram = {sig_world.mark}\n", encoding="utf-8"
    )
    for key, value in config.items():
        _git(sig_world.repo, "config", key, value)
    for command in ("git log -1", "git show -s"):
        sig_world.run("bash", command)
        assert sig_world.sprung(), f"control: {command} does not run gpg"
        executed = _what_runs(sig_world, command)
        assert executed is not None
        sig_world.run(shell, executed)
        assert sig_world.sprung() == [], executed


@pytest.mark.parametrize(
    "command",
    ["git log -1 --show-signature", "git log -1 --format='%G?'", "git show -s --pretty=format:%GS",
     "git log -1 --pretty=sig"],
)
def test_signature_options_spring_raw_and_are_refused(sig_world: World, command: str) -> None:
    _git(sig_world.repo, "config", "pretty.sig", "%h %G?")
    sig_world.run("bash", command)
    assert sig_world.sprung(), f"control: {command} does not run gpg"
    assert _what_runs(sig_world, command) is None, command


@pytest.fixture
def filter_world(tmp_path: Path) -> World:
    """A change whose `.gitattributes` (part of the reviewed checkout) selects a clean filter the
    user has configured; the marker stands in for the filter's program."""
    world = _base(tmp_path)
    world.repo.mkdir()
    _git(world.repo, "init", "-q")
    (world.repo / ".gitattributes").write_text("*.txt filter=f\n", encoding="utf-8")
    (world.repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(world.repo, "add", ".")
    _git(world.repo, "commit", "-q", "-m", "init")
    _git(world.repo, "config", "filter.f.clean", str(world.mark))
    (world.repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    world.reset()
    return world


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("command", ["git diff", "git blame a.txt", "git diff --stat"])
def test_a_checkout_cannot_select_a_clean_filter(
    filter_world: World, shell: str, command: str
) -> None:
    """Git 2.41 and later: attributes come from the empty tree, so the checkout's
    `.gitattributes` selects nothing. Older git keeps this residual (ADR 0106)."""
    version = role_scope._git_version()  # asked directly, not through the function under test
    if version is not None and version < role_scope.ATTR_SOURCE_SINCE:
        pytest.skip("git older than 2.41 has no --attr-source")
    filter_world.run("bash", command)
    assert filter_world.sprung(), f"control: {command} does not run the clean filter"
    executed = _what_runs(filter_world, command)
    assert executed is not None and f"--attr-source={role_scope.EMPTY_TREE}" in executed
    filter_world.run(shell, executed)
    assert filter_world.sprung() == [], executed


@pytest.mark.parametrize("shell", SHELLS)
def test_a_configured_attributes_file_is_not_read(filter_world: World, shell: str) -> None:
    """`core.attributesFile` from config (an included file, say) is turned off on every git."""
    _git(filter_world.repo, "rm", "-q", "--cached", ".gitattributes")  # the index is read too
    _git(filter_world.repo, "commit", "-q", "-m", "no attributes")
    (filter_world.repo / ".gitattributes").unlink()
    attrs = filter_world.root / "attrs"
    attrs.write_text("* filter=f\n", encoding="utf-8")
    _git(filter_world.repo, "config", "core.attributesFile", str(attrs))
    filter_world.run("bash", "git diff -- a.txt")
    assert filter_world.sprung(), "control: the attributes file does not select the filter"
    executed = _what_runs(filter_world, "git diff -- a.txt")
    assert executed is not None
    filter_world.run(shell, executed.replace(f" '--attr-source={role_scope.EMPTY_TREE}'", ""))
    assert filter_world.sprung() == [], executed


MODIFIED_PLACEHOLDERS = ["git log -1 --format=%+GS", "git log -1 --format=%-GS",
                         "git log -1 '--format=% GS'", "git log -1 --pretty=tformat:x%+GK"]


@pytest.mark.parametrize("command", MODIFIED_PLACEHOLDERS)
def test_a_placeholder_with_a_modifier_springs_raw_and_is_refused(
    sig_world: World, command: str
) -> None:
    sig_world.run("bash", command)
    assert sig_world.sprung(), f"control: {command} does not run gpg"
    assert _what_runs(sig_world, command) is None, command


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("source", ["repo config", "included config", "ssh format"])
@pytest.mark.parametrize("command", [*MODIFIED_PLACEHOLDERS, "git log -1 --show-signature"])
def test_no_gpg_program_runs_even_past_the_placeholder_check(
    sig_world: World, shell: str, source: str, command: str
) -> None:
    """The primary fix: the hardened form sets every gpg program to /dev/null, so a placeholder
    that got past the check (built here directly, skipping it) still runs nothing."""
    if source == "included config":  # a tracked file the user includes, as the review's probe
        _git(sig_world.repo, "config", "--unset", "gpg.program")
        (sig_world.repo / "shared.gitconfig").write_text(
            f"[log]\n\tshowSignature = true\n[gpg]\n\tprogram = {sig_world.mark}\n",
            encoding="utf-8",
        )
        _git(sig_world.repo, "config", "include.path", "../shared.gitconfig")
    elif source == "ssh format":
        _git(sig_world.repo, "config", "gpg.format", "ssh")
        _git(sig_world.repo, "config", "gpg.ssh.program", str(sig_world.mark))
    words = shlex.split(command)
    sig_world.run("bash", command)
    assert sig_world.sprung(), f"control: {command} does not run the {source} program"
    executed = role_scope.hardened_command(
        role_scope.GitCall(None, words[1], tuple(words[2:])),
        role_scope.git_supports_attr_source(),
    )
    sig_world.run(shell, executed)
    assert sig_world.sprung() == [], executed
