"""The commit gate trusts no tracked tool directory, and its gate gets no credential-named
variables (ADR 0115).

The gate is a PreToolUse hook: it runs before the user is asked about the commit. A project-local
bin directory the repository itself ships is skipped (git is asked, from the repo the directory
belongs to), and the gate's environment drops every variable whose name looks like a credential.
ADR 0081's field case — an installed, untracked or gitignored `.venv/bin` or `node_modules/.bin`
— still resolves.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from agentic_forge import guardrails

_REPO = Path(__file__).resolve().parents[1]
HOOKS = _REPO / "plugin" / "hooks" / "scripts"
sys.path.insert(0, str(HOOKS))

import commit_gate  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")

_IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
_PY39 = shutil.which("python3.9")
_HOOK_PYTHONS = [
    pytest.param(sys.executable, id="current"),
    pytest.param(
        _PY39 or "python3.9", id="py39",
        marks=pytest.mark.skipif(not _PY39, reason="no python3.9 on PATH"),
    ),
]  # fmt: skip


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *_IDENTITY, *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


def _tool(path: Path, body: str = "exit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path.resolve() / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


def _skipped(cwd: Path) -> list[tuple[Path, str]]:
    return list(guardrails.bin_dirs(cwd).skipped)


def _commit_all(root: Path, *force: str) -> None:
    _git(root, "add", ".")
    if force:
        _git(root, "add", "-f", *force)
    _git(root, "commit", "-qm", "more")


# --- which directories are trusted ---------------------------------------------------------


def test_a_tracked_venv_is_neither_resolved_nor_on_path(repo: Path) -> None:
    local = _tool(repo / ".venv" / "bin" / "ruff").parent
    _commit_all(repo)
    assert guardrails.gate_bin_dirs(repo) == []
    assert _skipped(repo) == [(local, guardrails.BIN_DIR_TRACKED)]
    assert guardrails.resolve_gate(["ruff", "check", "."], repo)[0] != str(local / "ruff")
    path = guardrails.gate_env(repo, {"PATH": "/usr/bin"})["PATH"]
    assert path == "/usr/bin" and str(local) not in path


@pytest.mark.parametrize("ignored", [False, True], ids=["untracked", "gitignored"])
def test_an_installed_venv_still_resolves(repo: Path, ignored: bool) -> None:
    """ADR 0081's field case: the linter lives in the project's own, uncommitted venv."""
    if ignored:
        (repo / ".gitignore").write_text(".venv/\nnode_modules/\n", encoding="utf-8")
        _commit_all(repo)
    local = _tool(repo / ".venv" / "bin" / "ruff").parent
    node = _tool(repo / "node_modules" / ".bin" / "eslint").parent
    assert guardrails.gate_bin_dirs(repo) == [node, local]
    assert _skipped(repo) == []
    assert guardrails.resolve_gate(["ruff", "check", "."], repo) == [
        str(local / "ruff"),
        "check",
        ".",
    ]
    path = guardrails.gate_env(repo, {"PATH": "/usr/bin"})["PATH"]
    assert path == os.pathsep.join([str(node), str(local), "/usr/bin"])


def test_a_directory_outside_any_checkout_still_resolves(tmp_path: Path) -> None:
    local = _tool(tmp_path.resolve() / "venv" / "bin" / "ruff").parent
    assert guardrails.gate_bin_dirs(tmp_path) == [local]
    assert _skipped(tmp_path) == []


def test_a_force_added_file_in_an_ignored_venv_distrusts_it(repo: Path) -> None:
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _tool(repo / ".venv" / "bin" / "ruff")
    _commit_all(repo, ".venv/bin/ruff")
    assert guardrails.gate_bin_dirs(repo) == []


def test_a_tracked_link_on_the_way_distrusts_the_directory(repo: Path) -> None:
    """git lists a tracked link as an entry and nothing through it, so `ls-files .venv/bin` is
    empty when `.venv` is a committed link to a tracked directory; the link itself is asked."""
    _tool(repo / "tools" / "bin" / "ruff")
    (repo / ".venv").symlink_to("tools")
    _commit_all(repo)
    assert _skipped(repo) == [(repo / ".venv" / "bin", guardrails.BIN_DIR_TRACKED)]


def test_an_untracked_link_to_a_venv_outside_the_checkout_still_resolves(
    repo: Path, tmp_path: Path
) -> None:
    _tool(tmp_path.resolve() / "envs" / "x" / "bin" / "ruff")
    (repo / ".venv").symlink_to(tmp_path.resolve() / "envs" / "x")
    assert guardrails.gate_bin_dirs(repo) == [repo / ".venv" / "bin"]


def test_a_tracked_tool_link_in_node_modules_bin_distrusts_it(repo: Path) -> None:
    (repo / "node_modules" / ".bin").mkdir(parents=True)
    (repo / "node_modules" / ".bin" / "eslint").symlink_to("../../lint.js")
    _commit_all(repo, "node_modules/.bin/eslint")
    assert _skipped(repo) == [(repo / "node_modules" / ".bin", guardrails.BIN_DIR_TRACKED)]


def test_the_main_checkouts_tracked_venv_is_distrusted_from_a_linked_worktree(
    repo: Path, tmp_path: Path
) -> None:
    """`gate_bin_dirs` also looks at the main repo root; that directory is asked of its own repo."""
    _tool(repo / ".venv" / "bin" / "ruff")
    _commit_all(repo)
    linked = tmp_path.resolve() / "linked"
    _git(repo, "worktree", "add", "-q", str(linked))
    assert {d for d, _ in _skipped(linked)} == {
        linked / ".venv" / "bin",
        repo / ".venv" / "bin",
    }
    assert guardrails.gate_bin_dirs(linked) == []


# --- git could not answer: fail safe toward PATH --------------------------------------------


def _unchecked(repo: Path) -> None:
    local = _tool(repo / ".venv" / "bin" / "ruff").parent
    assert guardrails.gate_bin_dirs(repo) == []
    assert _skipped(repo) == [(local, guardrails.BIN_DIR_UNCHECKED)]


@pytest.mark.parametrize("relative", [False, True], ids=["no-git", "relative-git"])
def test_no_git_by_an_absolute_path_distrusts_a_directory_in_a_checkout(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    """A `git` a relative PATH entry finds in the session's directory is never run."""
    ran = tmp_path / "planted-git-ran"
    _tool(tmp_path / "planted-bin" / "git", f"touch '{ran}'\n")
    if relative:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", "planted-bin")
    else:
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    _unchecked(repo)
    assert not ran.exists()


def test_on_windows_the_tool_directory_check_runs_only_a_git_binary(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As on Windows: a `git.cmd` on an absolute PATH entry is never chosen, so with nothing else
    the directory is unchecked, as with no git; a later `git.exe` is the one asked."""
    _tool(repo / ".venv" / "bin" / "ruff")
    monkeypatch.setattr(guardrails, "_WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    shims, binaries = tmp_path / "win-cmd", tmp_path / "win-exe"
    for directory, name in ((shims, "git.cmd"), (binaries, "git.EXE")):
        directory.mkdir()
        (directory / name).write_text("")
    started: list[str] = []

    def spy(argv: list[str], **kwargs: object) -> object:
        started.append(argv[0])
        raise OSError("not a program this host can run")

    monkeypatch.setattr(guardrails.subprocess, "run", spy)
    monkeypatch.setenv("PATH", str(shims))
    assert guardrails._bin_dir_doubt(repo, ".venv/bin", 1e18) == guardrails.BIN_DIR_UNCHECKED
    assert started == []
    monkeypatch.setenv("PATH", os.pathsep.join([str(shims), str(binaries)]))
    assert guardrails._bin_dir_doubt(repo, ".venv/bin", 1e18) == guardrails.BIN_DIR_UNCHECKED
    assert started and set(started) == {str(binaries / "git.EXE")}


def test_no_git_outside_a_checkout_still_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    local = _tool(tmp_path.resolve() / ".venv" / "bin" / "ruff").parent
    assert guardrails.gate_bin_dirs(tmp_path) == [local]


def test_a_git_error_distrusts_the_directory(repo: Path) -> None:
    (repo / ".git" / "index").write_bytes(b"not an index")  # git ls-files exits 128
    _unchecked(repo)


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired("git", 2.0), OSError("exec format error")],
    ids=["timeout", "oserror"],
)
def test_a_git_that_does_not_answer_distrusts_the_directory(
    repo: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def broken(*args: object, **kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(guardrails.subprocess, "run", broken)
    _unchecked(repo)


def test_an_exhausted_budget_distrusts_the_directory(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guardrails, "_BIN_DIR_BUDGET", 0.0)
    _unchecked(repo)


# --- no credential-named variables reach the gate ------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "GH_TOKEN", "GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "NPM_TOKEN",
        "AWS_SECRET_ACCESS_KEY", "AWS_SECRETKEY", "AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN",
        "AWS_SESSION_KEY", "SSH_AUTH_SOCK", "DB_PASSWORD", "MYSQL_PASSWD", "STRIPE_SECRET",
        "GOOGLE_APPLICATION_CREDENTIALS", "AZURE_CREDENTIAL", "OPENAI_APIKEY", "DEPLOY_PRIVATE_KEY",
        "gh_token", "Session_Key", "npm_config__authToken", "NPM_CONFIG__AUTH", "TOKEN", "auth",
        # plurals; PAT, PASS, DSN
        "APP_SECRETS", "GITHUB_TOKENS", "DB_PASSWORDS", "GITHUB_PAT", "SMTP_PASS", "SENTRY_DSN",
        # a word ending in TOKEN, SECRET, PASSWORD or PASSWD
        "PGPASSWORD", "GITHUBTOKEN", "CLIENTSECRET", "ROOTPASSWD", "NPM_CONFIG__AUTHTOKEN",
        # camelCase humps
        "GithubToken", "apiKey", "APIKey", "clientSecret", "PGPassword", "dbPwd",
        # PWD and a last KEY/KEYS in a name of two or more words
        "MYSQL_PWD", "OPENAI_KEY", "SENDGRID_KEY", "SSH_KEYS", "PRIVATE_KEY_FILE",
        # exact names
        "KRB5CCNAME", "krb5ccname",
    ],
)  # fmt: skip
def test_a_credential_name_is_recognised(name: str) -> None:
    assert guardrails.looks_like_credential(name)


@pytest.mark.parametrize(
    "name",
    [
        "PATH", "HOME", "LANG", "LC_ALL", "VIRTUAL_ENV", "NPM_CONFIG_USERCONFIG",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "AUTHOR", "OAUTHLIB_INSECURE_TRANSPORT",
        "XAUTHORITY", "TOKENIZERS_PARALLELISM", "SECRETARY", "PASSWORDLESS", "KEY", "MONKEY",
        "API_URL", "ACCESS_LOG", "SESSION_ID", "PRIVATE", "AWS_REGION", "AWS_PROFILE",
        "AGENTIC_FORGE_SKIP_TEST_GATE", "", "PWD", "OLDPWD", "XDG_RUNTIME_DIR", "KEY_FILE",
        "KEYCHAIN_PATH", "COMPASS", "GIT_ASKPASS", "SSH_AGENT_PID", "ProgramFiles", "SystemRoot",
        "PSModulePath", "KRB5_CONFIG", "DBUS_STARTER_BUS_TYPE", "DBUS_SESSION_BUS_ADDRESS",
    ],
)  # fmt: skip
def test_a_name_that_only_contains_a_credential_word_is_kept(name: str) -> None:
    assert not guardrails.looks_like_credential(name)


def test_gate_env_drops_credentials_and_keeps_the_trusted_path_prefix(repo: Path) -> None:
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _commit_all(repo)
    local = _tool(repo / ".venv" / "bin" / "ruff").parent
    source = {
        "PATH": "/usr/bin", "HOME": "/h", "GIT_AUTHOR_NAME": "t", "VIRTUAL_ENV": "/v",
        "GH_TOKEN": "x", "ANTHROPIC_API_KEY": "x", "SSH_AUTH_SOCK": "/s",
    }  # fmt: skip
    env = guardrails.gate_env(repo, source)
    assert env == {
        "PATH": f"{local}{os.pathsep}/usr/bin", "HOME": "/h", "GIT_AUTHOR_NAME": "t",
        "VIRTUAL_ENV": "/v",
    }  # fmt: skip
    assert source["GH_TOKEN"] == "x"  # the caller's mapping is not changed


def test_gate_env_reads_the_process_environment_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = guardrails.gate_env(tmp_path)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env and env["LANG"] == "C.UTF-8"


# --- the hook: the notice, and what the gate actually runs ---------------------------------


def _staged_commit(repo: Path) -> dict[str, object]:
    source = repo / "a.py"
    source.write_text((source.read_text() if source.exists() else "") + "x = 1\n")  # a change
    _git(repo, "add", "a.py")
    return {
        "hook_event_name": "PreToolUse", "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"}, "cwd": str(repo), "session_id": "s",
    }  # fmt: skip


@pytest.mark.parametrize("python", _HOOK_PYTHONS)
@pytest.mark.parametrize("rc", [0, 1], ids=["passes", "blocks"])
def test_the_hook_runs_the_path_tool_without_credentials_and_says_why(
    repo: Path, tmp_path: Path, python: str, rc: int
) -> None:
    """End to end, on the hook's own interpreter: the shipped `.venv/bin/ruff` never runs, PATH's
    does, without the token, and the operator and the model are told which directory was
    ignored."""
    planted = tmp_path / "planted-ran"
    _tool(repo / ".venv" / "bin" / "ruff", f'touch "{planted}"\nexit 0\n')
    _commit_all(repo)
    seen = tmp_path / "env-seen"
    tools = _tool(tmp_path / "bin" / "ruff", f'env > "{seen}"\nexit {rc}\n').parent
    (tmp_path / "home").mkdir()
    env = {
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
        "AGENTIC_FORGE_STATE_HOME": str(tmp_path / "state"), "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1", "GH_TOKEN": "gh-secret", "GIT_AUTHOR_NAME": "t",
    }  # fmt: skip
    done = subprocess.run(
        [python, str(HOOKS / "commit_gate.py")], input=json.dumps(_staged_commit(repo)),
        env=env, capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert done.returncode == (2 if rc else 0), done.stderr
    assert not planted.exists()
    variables = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert "GH_TOKEN" not in variables and variables["GIT_AUTHOR_NAME"] == "t"
    assert str(repo / ".venv" / "bin") not in variables["PATH"]
    notice = f"ignored the project tool directory `{repo / '.venv' / 'bin'}` (tracked by git)"
    assert notice in done.stderr
    shown = json.loads(done.stdout)["systemMessage"]  # one JSON object, the notice first
    assert shown.startswith(f"agentic-forge test-gate: {notice}"), shown
    assert "For a repository you do not trust, set `test_gate.skip: true`" in shown
    # a block names what the gate ran without, by name only, to the operator; the model hears it
    # only when the output reads like a refused credential, which a bare exit 1 does not
    assert "The gate ran without GH_TOKEN" not in done.stderr
    assert ("test-gate blocked this" in shown and "without GH_TOKEN" in shown) == bool(rc)
    assert "gh-secret" not in done.stdout + done.stderr


def _main(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return commit_gate.main()


def test_an_untrusted_directory_and_a_fail_open_share_one_message(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    _tool(repo / ".venv" / "bin" / "ruff")
    _commit_all(repo)
    real_run = subprocess.run

    def run(cmd, **kwargs):  # git reads run for real; the gate's tool is missing
        if Path(cmd[0]).name == "git":
            return real_run(cmd, **kwargs)
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    monkeypatch.setattr(commit_gate.subprocess, "run", run)
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    out = capsys.readouterr().out
    message = json.loads(out)["systemMessage"]  # a single object: both notices in it
    assert "ignored the project tool directory" in message and "NOT gated" in message


def test_a_trusted_directory_prints_no_notice(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    local = _tool(repo / ".venv" / "bin" / "ruff").parent
    real_run = subprocess.run
    ran: list[list[str]] = []

    def run(cmd, **kwargs):
        if Path(cmd[0]).name == "git":
            return real_run(cmd, **kwargs)
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(commit_gate.subprocess, "run", run)
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "ignored" not in captured.err
    assert ran and all(cmd[0] == str(local / "ruff") for cmd in ran)


# --- one read per run, once per session -------------------------------------------------------


def _fake_gate(monkeypatch: pytest.MonkeyPatch, rc: int = 0) -> list[list[str]]:
    """``subprocess.run`` with git for real and every other program faked to exit ``rc``."""
    real_run = subprocess.run
    ran: list[list[str]] = []

    def run(cmd, **kwargs):
        if Path(cmd[0]).name == "git":
            return real_run(cmd, **kwargs)
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(commit_gate.subprocess, "run", run)
    return ran


def test_each_directory_is_asked_once_per_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The notice, the resolution and the gate's PATH read one `BinDirs`, so they cannot disagree
    and git is asked once per directory, within one budget."""
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    _tool(repo / ".venv" / "bin" / "ruff")
    _commit_all(repo)
    asked: list[tuple[str, ...]] = []
    real = guardrails._git_bytes

    def counting(git: str, directory: str, deadline: float, *args: str) -> tuple[int, bytes]:
        asked.append(args)
        return real(git, directory, deadline, *args)

    monkeypatch.setattr(guardrails, "_git_bytes", counting)
    ran = _fake_gate(monkeypatch)
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    assert [a for a in asked if "ls-files" in a] == [
        ("--literal-pathspecs", "ls-files", "-z", "--", ".")
    ]
    assert ran and all(cmd[0] != str(repo / ".venv" / "bin" / "ruff") for cmd in ran)
    capsys.readouterr()


def test_the_operator_hears_of_a_set_of_ignored_directories_once_per_session(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    _tool(repo / ".venv" / "bin" / "ruff")
    _commit_all(repo)
    _fake_gate(monkeypatch)
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    first = capsys.readouterr()
    assert "ignored the project tool directory" in json.loads(first.out)["systemMessage"]
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    again = capsys.readouterr()
    assert again.out == "" and "ignored the project tool directory" in again.err  # stderr stays
    payload = _staged_commit(repo)
    payload["session_id"] = "s-2"
    assert _main(monkeypatch, payload) == 0
    assert "systemMessage" in capsys.readouterr().out


def test_a_new_set_of_ignored_directories_is_announced_again(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    _tool(repo / ".venv" / "bin" / "ruff")
    _commit_all(repo)
    _fake_gate(monkeypatch)
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    capsys.readouterr()
    _tool(repo / "venv" / "bin" / "ruff")
    _commit_all(repo)
    assert _main(monkeypatch, _staged_commit(repo)) == 0
    message = json.loads(capsys.readouterr().out)["systemMessage"]
    assert str(repo / "venv" / "bin") in message and "directories" in message


# --- a package script: the package manager rebuilds PATH -----------------------------------


@pytest.fixture
def js(tmp_path: Path) -> Path:
    """A repository whose gate is `npm run lint`, with a stand-in `npm` and `eslint` on PATH that
    record whether they ran."""
    root = tmp_path.resolve() / "js"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "package.json").write_text(
        json.dumps({"name": "x", "scripts": {"lint": "eslint ."}}), encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    assert guardrails.choose_gate(root) == ["npm", "run", "lint"]
    return root


def _js_commit(root: Path, cwd: Path) -> dict[str, object]:
    (root / "a.js").write_text("x\n", encoding="utf-8")
    _git(root, "add", "a.js")
    return {
        "hook_event_name": "PreToolUse", "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"}, "cwd": str(cwd), "session_id": "s",
    }  # fmt: skip


def _hook(payload: dict[str, object], tmp_path: Path, path: str) -> subprocess.CompletedProcess:
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        "PATH": path, "HOME": str(tmp_path / "home"),
        "AGENTIC_FORGE_STATE_HOME": str(tmp_path / "state"), "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }  # fmt: skip
    return subprocess.run(
        [sys.executable, str(HOOKS / "commit_gate.py")], input=json.dumps(payload), env=env,
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip


@pytest.mark.parametrize("where", [".", "web"], ids=["at-the-package", "at-a-parent"])
def test_a_package_script_gate_is_not_run_beside_a_tracked_node_bin(
    js: Path, tmp_path: Path, where: str
) -> None:
    """npm, pnpm and yarn put the `node_modules/.bin` of the package and every parent on a
    script's PATH themselves, so the hook cannot keep a tracked one out: it does not run the
    script at all, and says why."""
    _tool(js / "node_modules" / ".bin" / "eslint", f'touch "{tmp_path / "planted-ran"}"\n')
    _commit_all(js, "node_modules/.bin/eslint")
    cwd = js / where
    if where != ".":
        cwd.mkdir()
        (cwd / "package.json").write_text(
            json.dumps({"name": "w", "scripts": {"lint": "eslint ."}}), encoding="utf-8"
        )
        _tool(cwd / "node_modules" / ".bin" / "eslint")  # the package's own: untracked
        (cwd / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    npm_ran = tmp_path / "npm-ran"
    fake = _tool(tmp_path / "bin" / "npm", f'touch "{npm_ran}"\nexit 1\n').parent
    done = _hook(_js_commit(js, cwd), tmp_path, f"{fake}{os.pathsep}{os.environ['PATH']}")
    assert done.returncode == 0, done.stderr
    assert not npm_ran.exists() and not (tmp_path / "planted-ran").exists()
    shown = json.loads(done.stdout)["systemMessage"]
    assert "`npm run lint` was NOT run — this commit was NOT gated" in shown
    assert f"`{js / 'node_modules' / '.bin'}` (tracked by git)" in shown
    assert "test_gate.skip" in shown


def test_a_package_script_gate_runs_beside_an_installed_node_bin(js: Path, tmp_path: Path) -> None:
    node = _tool(js / "node_modules" / ".bin" / "eslint").parent  # installed, untracked
    seen = tmp_path / "npm-env"
    fake = _tool(tmp_path / "bin" / "npm", f'env > "{seen}"\nexit 0\n').parent
    done = _hook(_js_commit(js, js), tmp_path, f"{fake}{os.pathsep}{os.environ['PATH']}")
    assert done.returncode == 0 and done.stdout == "", done.stderr
    path = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)["PATH"]
    assert path.split(os.pathsep)[0] == str(node)


@pytest.mark.skipif(not shutil.which("npm"), reason="no npm on PATH")
def test_real_npm_never_runs_a_tracked_node_bin_tool(js: Path, tmp_path: Path) -> None:
    """With the real npm: the control shows `npm run lint` does run a tracked
    `node_modules/.bin/eslint` (npm puts the directory on the script's PATH itself), and the hook
    then never lets it run."""
    planted = tmp_path / "planted-ran"
    _tool(js / "node_modules" / ".bin" / "eslint", f'touch "{planted}"\nexit 0\n')
    _commit_all(js, "node_modules/.bin/eslint")
    control = subprocess.run(
        ["npm", "run", "lint"], cwd=str(js), capture_output=True, text=True, timeout=120,
        env={**os.environ, "HOME": str(tmp_path / "npm-home")},
    )  # fmt: skip
    assert control.returncode == 0 and planted.exists(), control.stderr
    planted.unlink()
    done = _hook(_js_commit(js, js), tmp_path, os.environ["PATH"])
    assert done.returncode == 0, done.stderr
    assert not planted.exists()
    assert "`npm run lint` was NOT run" in json.loads(done.stdout)["systemMessage"]


# --- the withheld names ----------------------------------------------------------------------


def test_withheld_names_are_names_sorted_and_capped_in_the_messages() -> None:
    env = {"PATH": "/p", "GH_TOKEN": "v1", "ANTHROPIC_API_KEY": "v2", "LANG": "C"}
    assert guardrails.withheld_names(env) == ["ANTHROPIC_API_KEY", "GH_TOKEN"]
    many = [f"T{i:02d}_TOKEN" for i in range(15)]
    block = commit_gate.block_message(
        ["ruff", "check", "."], "/r", scoped=False, tail="E1 finding", withheld=many
    )
    assert "The gate ran without T00_TOKEN, " in block and "T11_TOKEN and 3 more" in block
    assert "T12_TOKEN" not in block and "test_gate.skip" not in block  # the model is not told
    notice = commit_gate.skip_notice("/r", many[:2])
    assert "The gate ran without T00_TOKEN, T01_TOKEN" in notice
    assert "without" not in commit_gate.skip_notice("/r")
    assert "without" not in commit_gate.block_message(["ruff"], "/r", scoped=False, tail="x")


# --- a name spelled otherwise on disk ---------------------------------------------------------


@pytest.mark.parametrize("failing", ["case", "oserror"])
def test_a_directory_spelled_otherwise_on_disk_is_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """On a case-insensitive filesystem `.venv/bin` opens a tracked `.VENV/bin`, which `ls-files`
    of `.venv` does not list; each component must be listed with exactly that spelling."""
    root = tmp_path.resolve()
    local = _tool(root / ".venv" / "bin" / "ruff").parent
    real = os.listdir

    def listdir(path: str) -> list[str]:
        if failing == "oserror" and Path(path) == root / ".venv":
            raise PermissionError(path)
        names = real(path)
        return [".VENV" if n == ".venv" else n for n in names] if failing == "case" else names

    monkeypatch.setattr(guardrails.os, "listdir", listdir)
    assert guardrails.bin_dirs(root) == guardrails.BinDirs(
        (), ((local, guardrails.BIN_DIR_UNCHECKED),), ()
    )


# --- the gate's program by absolute path --------------------------------------------------------


def test_the_gate_runs_its_program_by_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    tool = _tool(root / "abs" / "ruff")
    _tool(root / "rel" / "lint")
    monkeypatch.chdir(root)
    path = os.pathsep.join(["rel", "", str(tool.parent)])
    assert guardrails.executable(["ruff", "check"], path) == [str(tool), "check"]
    with pytest.raises(FileNotFoundError):  # only a relative entry has it: never a bare name
        guardrails.executable(["lint"], path)
    assert guardrails.executable(["./x", "y"], path) == ["./x", "y"]
    assert guardrails.executable([], path) == []
    env = guardrails.gate_env(root, {"PATH": path})
    assert env["PATH"] == str(tool.parent)  # no entry that names the directory the gate runs in


@pytest.mark.parametrize("path", ["", ".", "rel:bin", "::"])
def test_a_gate_path_with_no_absolute_entry_gets_the_safe_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setattr(guardrails, "_WINDOWS", False)
    assert guardrails.gate_env(tmp_path, {"PATH": path})["PATH"] == "/usr/bin:/bin"
    assert guardrails.gate_env(tmp_path, {})["PATH"] == "/usr/bin:/bin"
    local = _tool(tmp_path.resolve() / ".venv" / "bin" / "ruff").parent
    assert guardrails.gate_env(tmp_path, {"PATH": path})["PATH"] == f"{local}:/usr/bin:/bin"


def test_on_windows_the_safe_default_is_the_system_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guardrails, "_WINDOWS", True)
    monkeypatch.setenv("SystemRoot", "/sysroot")
    assert guardrails.gate_env(tmp_path, {"PATH": "rel"})["PATH"] == "/sysroot/System32"


def _windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """`executable` as on Windows: PATHEXT names, no execute bit needed."""
    monkeypatch.setattr(guardrails, "_WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.CMD")


@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
def test_a_program_in_the_current_directory_is_never_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    """Windows' own lookup (and `shutil.which` there) searches the current directory first; the
    gate's lookup reads only the absolute PATH entries."""
    if windows:
        _windows(monkeypatch)
    root = tmp_path.resolve()
    name = "ruff.EXE" if windows else "ruff"
    planted = _tool(root / "repo" / name)
    trusted = _tool(root / "abs" / name)
    monkeypatch.chdir(planted.parent)
    for path in (str(trusted.parent), os.pathsep.join(["", ".", str(trusted.parent)])):
        assert guardrails.executable(["ruff", "x"], path) == [str(trusted), "x"]


@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
def test_trusted_program_reads_the_hooks_path_as_the_gate_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    """The lookup the hooks' own git/gh runs use (`commit_dir`, the tool-directory check,
    `role_scope`, `merge_preflight`): the hook's PATH, absolute entries only, on Windows an
    `.exe`/`.com` only. A `git.cmd` on an absolute entry is never chosen; nothing found is None."""
    root = tmp_path.resolve()
    if windows:
        monkeypatch.setattr(guardrails, "_WINDOWS", True)
        monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        (root / "cmd").mkdir()
        (root / "cmd" / "git.cmd").write_text("")
        (root / "exe").mkdir()
        (root / "exe" / "git.EXE").write_text("")
        trusted = root / "exe" / "git.EXE"
    else:
        monkeypatch.setattr(guardrails, "_WINDOWS", False)
        _tool(root / "cmd" / "unrelated")
        trusted = _tool(root / "exe" / "git")
    _tool(root / "rel" / "git")  # found only through a relative entry
    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", os.pathsep.join(["rel", "", str(root / "cmd")]))
    assert guardrails.trusted_program("git") is None
    monkeypatch.setenv("PATH", os.pathsep.join(["rel", str(root / "cmd"), str(root / "exe")]))
    assert guardrails.trusted_program("git") == str(trusted)
    monkeypatch.delenv("PATH")
    assert guardrails.trusted_program("git") is None


def test_on_windows_a_binary_name_with_its_extension_is_tried_bare_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _windows(monkeypatch)
    root = tmp_path.resolve()
    (root / "abs").mkdir()
    for name in ("tool.exe", "lint.EXE", "shim.cmd"):
        (root / "abs" / name).write_text("")  # no execute bit: Windows does not use one
    abs_dir = str(root / "abs")
    assert guardrails.executable(["tool.exe"], abs_dir) == [str(root / "abs" / "tool.exe")]
    assert guardrails.executable(["lint"], abs_dir) == [str(root / "abs" / "lint.EXE")]
    with pytest.raises(FileNotFoundError):  # a script, named outright, is not run either
        guardrails.executable(["shim.cmd"], abs_dir)


def _scripts_and_binaries(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path]:
    """As on Windows with the usual PATHEXT: `bat/ruff.BAT` (a shim, first) and `exe/ruff.EXE`."""
    monkeypatch.setattr(guardrails, "_WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    for name in ("bat/ruff.BAT", "exe/ruff.EXE", "bat/npm.CMD"):
        (root / name).parent.mkdir(exist_ok=True)
        (root / name).write_text("")
    return root / "bat", root / "exe"


def test_on_windows_a_batch_shim_is_never_run_for_a_gate_with_repository_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cmd.exe reads `& ^ % ( )` in a `.bat`'s arguments, and the narrowed gate passes repository
    file names: with only a batch shim on PATH nothing starts."""
    bat, _ = _scripts_and_binaries(monkeypatch, tmp_path.resolve())
    started: list[object] = []
    monkeypatch.setattr(commit_gate.subprocess, "run", lambda *a, **k: started.append(a))
    payload = {"cwd": str(tmp_path), "session_id": None}
    gate = ["ruff", "check", "a&b.py"]
    assert commit_gate._run_gate(gate, str(tmp_path), payload, env={"PATH": str(bat)}) is None
    assert started == []
    with pytest.raises(FileNotFoundError):
        guardrails.executable(["ruff", "check", "."], str(bat))
    with pytest.raises(FileNotFoundError):  # a path to a script is refused too
        guardrails.executable([str(bat / "ruff.BAT"), "check"], str(bat))


def test_on_windows_a_later_binary_beats_an_earlier_batch_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bat, exe = _scripts_and_binaries(monkeypatch, tmp_path.resolve())
    path = os.pathsep.join([str(bat), str(exe)])
    assert guardrails.executable(["ruff", "check", "a&b.py"], path) == [
        str(exe / "ruff.EXE"), "check", "a&b.py",
    ]  # fmt: skip


def test_on_windows_the_fixed_npm_gate_may_run_npm_cmd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`npm run lint` has no word from the repository, and npm on Windows is `npm.cmd`."""
    bat, _ = _scripts_and_binaries(monkeypatch, tmp_path.resolve())
    assert guardrails.executable(["npm", "run", "lint"], str(bat)) == [
        str(bat / "npm.CMD"), "run", "lint",
    ]  # fmt: skip
    with pytest.raises(FileNotFoundError):  # any other argv: no script
        guardrails.executable(["npm", "run", "lint", "a&b.js"], str(bat))


def test_the_python_fallback_is_chosen_by_the_lookup_that_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`python` only in a relative PATH entry, `python3` on an absolute one: the gate runs python3,
    not a bare `python` the system would look up through the relative entry."""
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    root = tmp_path.resolve()
    (root / "dev").mkdir()
    (root / "dev" / "validate.py").write_text("", encoding="utf-8")
    _tool(root / "rel" / "python")
    python3 = _tool(root / "abs" / "python3")
    monkeypatch.chdir(root)
    path = os.pathsep.join(["rel", str(python3.parent)])
    monkeypatch.setenv("PATH", path)
    seen: list[list[str]] = []
    monkeypatch.setattr(
        commit_gate.subprocess, "run",
        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )  # fmt: skip
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(root)}
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW
    assert seen == [[str(python3), "dev/validate.py"]]
    assert guardrails.resolve_gate(["python", "x"], root, path=path) == ["python3", "x"]


@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
def test_a_program_only_in_the_current_directory_is_not_run_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    """Nothing resolves on the absolute entries: `_run_gate` fails open, and no process starts —
    neither the planted program nor a bare name for the system to look up."""
    if windows:
        _windows(monkeypatch)
    root = tmp_path.resolve()
    ran = root / "planted-ran"
    planted = _tool(root / "repo" / ("ruff.EXE" if windows else "ruff"), f'touch "{ran}"\n')
    (root / "empty").mkdir()
    monkeypatch.chdir(planted.parent)
    started: list[object] = []
    monkeypatch.setattr(commit_gate.subprocess, "run", lambda *a, **k: started.append(a))
    env = {"PATH": os.pathsep.join(["", ".", str(root / "empty")])}
    payload = {"cwd": str(planted.parent), "session_id": None}
    assert commit_gate._run_gate(["ruff", "check"], str(planted.parent), payload, env=env) is None
    assert started == [] and not ran.exists()
    with pytest.raises(FileNotFoundError, match="ruff"):
        guardrails.executable(["ruff"], env["PATH"])


@pytest.mark.parametrize("windows", [False, True])
def test_on_windows_the_gate_does_not_search_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(guardrails, "_WINDOWS", windows)
    env = guardrails.gate_env(tmp_path, {"PATH": "/usr/bin"})
    assert env.get("NoDefaultCurrentDirectoryInExePath") == ("1" if windows else None)


def test_the_hook_runs_the_gate_by_the_absolute_path_on_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    tool = _tool(tmp_path.resolve() / "bin" / "ruff")
    monkeypatch.setenv("PATH", f"{tool.parent}{os.pathsep}{os.environ['PATH']}")
    seen: list[list[str]] = []
    monkeypatch.setattr(
        commit_gate.subprocess, "run",
        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )  # fmt: skip
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW
    assert seen == [[str(tool), "check", "."]]


# --- ADR 0081's field case, seen from a linked worktree -----------------------------------------


def test_the_main_checkouts_ignored_node_bin_resolves_from_a_linked_worktree(
    repo: Path, tmp_path: Path
) -> None:
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _commit_all(repo)
    node = _tool(repo / "node_modules" / ".bin" / "eslint").parent
    linked = tmp_path.resolve() / "linked"
    _git(repo, "worktree", "add", "-q", str(linked))
    assert guardrails.gate_bin_dirs(linked) == [node]
    assert guardrails.resolve_gate(["eslint", "."], linked) == [str(node / "eslint"), "."]
    path = guardrails.gate_env(linked, {"PATH": "/usr/bin"})["PATH"]
    assert path == os.pathsep.join([str(node), "/usr/bin"])


def test_bin_dirs_reads_every_parents_node_bin_only_for_a_package_script(
    js: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root's `node_modules/.bin` is both a root directory and a parent of `web`: it is asked
    once, and listed in both places; a script gate reads parents only when asked to."""
    tracked = _tool(js / "node_modules" / ".bin" / "eslint").parent
    _commit_all(js, "node_modules/.bin/eslint")
    web = js / "web"
    own = _tool(web / "node_modules" / ".bin" / "eslint").parent  # untracked
    asked: list[str] = []
    real = guardrails._bin_dir_doubt
    monkeypatch.setattr(
        guardrails, "_bin_dir_doubt",
        lambda root, name, deadline, tops=None: (
            asked.append(str(root / name)) or real(root, name, deadline, tops)
        ),
    )  # fmt: skip
    dirs = guardrails.bin_dirs(web, package_script=True)
    assert dirs.trusted == (own,)
    assert dirs.skipped == dirs.script_skipped == ((tracked, guardrails.BIN_DIR_TRACKED),)
    assert sorted(asked) == sorted({str(own), str(tracked)})
    assert guardrails.bin_dirs(web).script_skipped == ()


def test_the_hook_skips_a_package_script_gate_and_says_so_once_per_session(
    js: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    _tool(js / "node_modules" / ".bin" / "eslint")
    _commit_all(js, "node_modules/.bin/eslint")
    ran = _fake_gate(monkeypatch, rc=1)
    assert _main(monkeypatch, _js_commit(js, js)) == 0
    first = capsys.readouterr()
    assert "`npm run lint` was NOT run" in json.loads(first.out)["systemMessage"]
    js.joinpath("a.js").write_text("y\n", encoding="utf-8")
    _git(js, "add", "a.js")
    assert _main(monkeypatch, _js_commit(js, js)) == 0
    again = capsys.readouterr()
    assert again.out == "" and "`npm run lint` was NOT run" in again.err
    assert ran == []  # neither npm nor anything else ran


# --- the model's credential hint: only when the output reads like a refused credential ----------


@pytest.mark.parametrize(
    "output",
    [
        "npm ERR! code E401", "npm error code E403", "npm ERR! code ENEEDAUTH",
        "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
        "git@github.com: Permission denied (publickey).", "Authentication failed for repo",
        "401 Unauthorized", "npm ERR! 403 Forbidden - GET https://r/x", "HTTP 401",
        "remote: HTTP/1.1 401", "Authentication required",
    ],
)  # fmt: skip
def test_an_auth_failure_is_recognised(output: str) -> None:
    assert guardrails.looks_like_auth_failure(output)


@pytest.mark.parametrize(
    "output",
    [
        "a.py:401:1: F401 `os` imported but unused", "E501 Line too long (120 > 100)",
        "Found 403 errors.", "x.go:12: undefined: y", "", "permission denied: ./script",
        "a.py:1:1: E401 [*] Multiple imports on one line", "E401 Multiple imports on one line",
        "app/authentication/views.py:3:1: F401 `os` imported but unused",
        "src/unauthorized_handler.py:9:5: E722 Do not use bare `except`", "code: 401",
        "api/http/401.py:3:1: F401 `os` imported but unused",
    ],
)  # fmt: skip
def test_an_ordinary_finding_is_not_an_auth_failure(output: str) -> None:
    assert not guardrails.looks_like_auth_failure(output)


@pytest.mark.parametrize(
    ("output", "hinted"), [("npm ERR! code E401", True), ("a.py:1:1: F401 unused", False)]
)
def test_the_model_hears_of_withheld_names_only_on_an_auth_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    output: str,
    hinted: bool,
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setenv("NPM_TOKEN", "npm-secret")
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    tool = _tool(tmp_path.resolve() / "bin" / "ruff")
    monkeypatch.setenv("PATH", f"{tool.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(
        commit_gate.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, output, ""),
    )  # fmt: skip
    payload = {
        "tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path),
        "session_id": "s",
    }  # fmt: skip
    assert _main(monkeypatch, payload) == 2
    captured = capsys.readouterr()
    model = captured.err.split("The gate ran without ", 1)
    assert (len(model) == 2 and "NPM_TOKEN" in model[1]) is hinted
    operator = json.loads(captured.out)["systemMessage"].split("The gate ran without ", 1)
    assert "NPM_TOKEN" in operator[1]  # the operator always hears the names
    assert "npm-secret" not in captured.err + captured.out


# --- the exact spelling, from the repository top ------------------------------------------------


def _respelled(monkeypatch: pytest.MonkeyPatch, parent: Path, name: str) -> None:
    """`os.listdir(parent)` lists ``name`` upper-cased, as a case-insensitive filesystem holding
    the upper-cased directory would while the lower-cased path still opens it."""
    real = os.listdir

    def listdir(path: str) -> list[str]:
        names = real(path)
        return [n.upper() if n == name else n for n in names] if Path(path) == parent else names

    monkeypatch.setattr(guardrails.os, "listdir", listdir)


def test_a_directory_above_the_bin_spelled_otherwise_is_not_trusted(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`svc/.venv/bin` opened through a tracked `SVC/`: the components from the repository top
    down are checked, not only those of the bin directory's own name."""
    local = _tool(repo / "svc" / ".venv" / "bin" / "ruff").parent
    assert guardrails.gate_bin_dirs(repo / "svc") == [local]
    _respelled(monkeypatch, repo, "svc")
    assert guardrails.bin_dirs(repo / "svc").skipped == ((local, guardrails.BIN_DIR_UNCHECKED),)


def test_a_parent_node_bin_spelled_otherwise_stops_a_package_script(
    js: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_bin = _tool(js / "web" / "node_modules" / ".bin" / "eslint").parent  # untracked
    app = js / "web" / "app"
    app.mkdir()
    assert guardrails.bin_dirs(app, package_script=True).script_skipped == ()
    _respelled(monkeypatch, js, "web")
    assert guardrails.bin_dirs(app, package_script=True).script_skipped == (
        (parent_bin, guardrails.BIN_DIR_UNCHECKED),
    )


def test_no_work_tree_top_means_unchecked(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local = _tool(repo / ".venv" / "bin" / "ruff").parent
    monkeypatch.setattr(guardrails, "_git_read", lambda *args: (128, []))
    assert guardrails.bin_dirs(repo).skipped == ((local, guardrails.BIN_DIR_UNCHECKED),)


# --- one notice key per kind --------------------------------------------------------------------


def test_the_notices_file_holds_one_key_per_kind(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_forge import diagnostics

    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    _fake_gate(monkeypatch)
    for name in (".venv", "venv"):  # two sets, each announced
        _tool(repo / name / "bin" / "ruff")
        _commit_all(repo)
        assert _main(monkeypatch, _staged_commit(repo)) == 0
        assert "ignored the project tool" in json.loads(capsys.readouterr().out)["systemMessage"]
    state, _ = diagnostics._state_location(repo)
    seen = json.loads((state / diagnostics.NOTICES_FILE).read_text(encoding="utf-8"))
    assert [k for k in seen if k.startswith("commit-gate:untrusted-tools")] == [
        "commit-gate:untrusted-tools:dirs"
    ]
    assert seen["commit-gate:untrusted-tools:dirs"].startswith("s:")


# --- git's work-tree top against the hook's root, compared as paths -----------------------------


@pytest.mark.parametrize(
    ("top", "root", "below"),
    [
        ("C:/work/repo", "C:\\work\\repo\\svc", ("svc",)),  # git prints forward slashes
        ("C:/Work/Repo", "c:\\work\\repo\\svc\\api", ("svc", "api")),  # Windows ignores case
        ("C:/work/repo", "C:\\work\\repo", ()),
        ("C:/work/repo", "C:\\work\\other", None),
        ("C:/work/repo", "D:\\work\\repo", None),
    ],
)
def test_the_top_and_the_root_are_compared_as_windows_paths(
    top: str, root: str, below: tuple[str, ...] | None
) -> None:
    assert guardrails._parts_below(top, root, PureWindowsPath) == below


def test_a_root_reached_through_a_link_is_below_its_real_top(tmp_path: Path) -> None:
    """git prints the real top; a root spelled through a linked component still lies under it."""
    real = tmp_path.resolve() / "real"
    real.mkdir()
    _git(real, "init", "-q")
    (real / "svc").mkdir()
    (tmp_path / "link").symlink_to(real)
    assert guardrails._parts_below(str(real), str(tmp_path / "link" / "svc")) == ("svc",)
    assert guardrails._parts_below(str(tmp_path / "link"), str(real / "svc")) == ("svc",)
    local = _tool(real / "svc" / ".venv" / "bin" / "ruff").parent
    assert guardrails.gate_bin_dirs(tmp_path / "link" / "svc") == [local]
