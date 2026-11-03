"""``plugin/bin/af.py``: what the skills run instead of inline Python (ADR 0104).

Real processes: the ``python3 -E`` a skill would use, nothing installed for it, and a working
directory holding what a hostile checkout would plant. A test reads a documented call from the skill
wherever it can, so it cannot go on passing for a call the skill no longer makes.
"""

from __future__ import annotations

import ast
import http.server
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agentic_forge import (
    doc_delivery,
    guardrails,
    handoff,
    ops,
    pr_watch,
    release,
    stacks,
    validation,
    vault,
)

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
_AF = _PLUGIN / "bin" / "af.py"
_PREFIX = 'python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" '
_OID = "a" * 40
_SAFE_GIT = ["git", "-c", "safe.bareRepository=explicit"]
_PLANTED = ("re", "json", "yaml", "jsonschema", "argparse", "subprocess", "shlex")


def _python3() -> str:
    found = shutil.which("python3")
    assert found, "no python3 on PATH"
    return found


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN)
    env.update(extra)
    return env


def _run(
    *args: str, cwd: Path, stdin: str | None = None, env: dict[str, str] | None = None,
    interpreter: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_python3(), "-E", *interpreter, str(_AF), *args], cwd=cwd, input=stdin,
        capture_output=True, text=True, check=False, env=_env() if env is None else env,
        timeout=60,
    )


def _ok(
    *args: str, cwd: Path, stdin: str | None = None, env: dict[str, str] | None = None
) -> Any:
    done = _run(*args, cwd=cwd, stdin=stdin, env=env)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    return json.loads(done.stdout)


def _refused(
    *args: str, cwd: Path, stdin: str | None = None, env: dict[str, str] | None = None
) -> str:
    """Exit 1, nothing on stdout, one readable line on stderr. Returns that line."""
    done = _run(*args, cwd=cwd, stdin=stdin, env=env)
    assert done.returncode == 1, (done.stdout, done.stderr)
    assert done.stdout == ""
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith("af.py: ")
    assert done.stderr.count("\n") == 1
    return done.stderr


def _plant(repo: Path, marker: Path) -> None:
    """What a checkout would commit: each module, once imported, leaves a marker and stops."""
    code = f"import os\nos.write(os.open({str(marker)!r}, os.O_CREAT | os.O_WRONLY, 0o600), b'x')\n"
    for name in _PLANTED:
        (repo / f"{name}.py").write_text(code, encoding="utf-8")
    package = repo / "agentic_forge"
    package.mkdir()
    (package / "__init__.py").write_text(code, encoding="utf-8")
    (package / "vault.py").write_text(code, encoding="utf-8")


@pytest.fixture
def hostile(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "marker"
    _plant(repo, marker)
    return repo, marker


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, input=stdin,
        env={**os.environ, **_GIT_ENV},
    ).stdout


def _fake_gh(
    tmp_path: Path, answer: object, *, code: int = 0, permissions: dict[str, Any] | None = None
) -> dict[str, str]:
    """A ``gh`` on PATH that logs its argv and prints ``answer``. A permission question is answered
    from ``permissions``, and one it has no answer for fails, as an unknown login does."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    log = tmp_path / "gh.log"
    gh.write_text(
        f"#!{_python3()} -S\nimport json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"permissions = {json.dumps(permissions or {})!r}\n"
        "for arg in sys.argv[1:]:\n"
        "    if '/collaborators/' in arg:\n"
        "        known = json.loads(permissions)\n"
        "        login = arg.split('/')[-2]\n"
        "        if login not in known:\n"
        "            sys.exit(1)\n"
        "        print(json.dumps({'permission': known[login]}))\n"
        "        sys.exit(0)\n"
        f"print({json.dumps(answer)!r})\nsys.exit({code})\n",
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return _env(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _gh_calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "gh.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _user_config(tmp_path: Path, env: dict[str, str], config: dict[str, Any]) -> dict[str, str]:
    home = tmp_path / "home"
    (home / ".agentic-forge").mkdir(parents=True, exist_ok=True)
    (home / ".agentic-forge" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return {**env, "HOME": str(home)}


# --- what the skills document -------------------------------------------------------------------


def _documents() -> list[Path]:
    return sorted(
        [*(_PLUGIN / "skills").rglob("*.md"), *(_PLUGIN / "patterns").rglob("*.md")]
    )


def _documented_calls() -> list[tuple[str, str]]:
    """Every ``af.py`` call in a skill, reference or pattern: (file, the call, on one line)."""
    calls: list[tuple[str, str]] = []
    for path in _documents():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            for start in re.finditer(re.escape(_PREFIX), line):
                rest = line[start.end():]
                # In prose the call ends at its closing backtick, in a block at the end of the line.
                # A pipe, a redirect or a heredoc is not the command's.
                call = re.split(r"`| <<| > | \| ", rest)[0].strip()
                calls.append((str(path.relative_to(_PLUGIN)), call))
    return calls


def _as_argv(call: str) -> list[str]:
    """A documented call with its placeholders filled in, split the way a shell would."""
    filled = re.sub(r"--gate-green <[^>]*>", "--gate-green yes", call)
    filled = re.sub(r"--(iteration|number) <[^>]*>", r"--\1 1", filled)
    filled = re.sub(r"<[^>]*>", "x", filled)
    return shlex.split(filled)


def _load_af() -> Any:
    spec = importlib.util.spec_from_file_location("_af_under_test", _AF)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def _subcommands() -> dict[str, Any]:
    parser = _load_af().build_parser()
    action = next(a for a in parser._actions if a.dest == "command")
    return dict(action.choices)


def test_there_are_documented_calls_to_check() -> None:
    assert len(_documented_calls()) > 30


@pytest.mark.parametrize(("where", "call"), _documented_calls())
def test_every_documented_call_parses_as_written(where: str, call: str) -> None:
    argv = _as_argv(call)
    commands = _subcommands()
    assert argv[0] in commands, f"{where}: no command {argv[0]!r}"
    try:
        commands[argv[0]].parse_args(argv[1:])
    except SystemExit as exc:  # argparse's way of saying the documented flags are wrong
        raise AssertionError(f"{where}: {call!r} does not parse") from exc


def test_every_command_is_one_a_skill_or_pattern_uses() -> None:
    """A command nobody documents is surface nobody asked for: the script stays narrow."""
    used = {call.split()[0] for _, call in _documented_calls()}
    assert set(_subcommands()) == used


def test_every_flag_is_one_a_skill_or_pattern_uses() -> None:
    """The same for flags. A flag nobody documents is an untested path into the library."""
    documented: dict[str, set[str]] = {}
    for _, call in _documented_calls():
        documented.setdefault(call.split()[0], set()).update(re.findall(r"(?<!\S)--[a-z-]+", call))
    for name, parser in _subcommands().items():
        flags = {s for a in parser._actions for s in a.option_strings if s.startswith("--")}
        assert flags - {"--help"} == documented[name], name


def test_no_generic_way_to_call_the_library() -> None:
    words = {word for name in _subcommands() for word in name.split("-")}
    assert not words & {"call", "exec", "run", "eval", "python", "invoke"}
    source = _AF.read_text(encoding="utf-8")
    assert "getattr(os," in source  # only for the optional open flags
    assert source.count("getattr(") == 2
    assert not re.search(r"\b(eval|exec|__import__)\(", source)
    assert "shell=True" not in source


def test_the_documented_calls_are_command_lines_the_guardrails_allow() -> None:
    for _, call in _documented_calls():
        decision = guardrails.classify_command(_PREFIX + call.replace("<", "x").replace(">", "x"))
        assert not decision.block, (call, decision.message)


@pytest.mark.parametrize("hook", ["security.py", "commit_gate.py", "merge_preflight.py"])
def test_the_real_hooks_let_the_documented_forms_through(tmp_path: Path, hook: str) -> None:
    """Each way a skill writes it: a call, a pipe into another, and a quoted heredoc whose text
    would be blocked as a command (a note can quote anything)."""
    commands = [
        f"{_PREFIX}vault-validate --repo .",
        f"{_PREFIX}release-commits --repo . | {_PREFIX}release-summarize --current 1.0.0 "
        "--messages-json -",
        f"{_PREFIX}vault-add-note --repo . --json - <<'NOTE'\n"
        '{"name": "a", "title": "A", "body": "We never run rm -rf / or git push --force."}\nNOTE',
    ]
    for command in commands:
        payload = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path),
            "session_id": "af", "tool_input": {"command": command},
        }
        done = subprocess.run(
            [_python3(), "-E", str(_PLUGIN / "hooks" / "scripts" / hook)],
            input=json.dumps(payload), capture_output=True, text=True, cwd=tmp_path, env=_env(),
            check=False, timeout=60,
        )
        assert done.returncode == 0, (command, done.stderr)


def test_what_it_hands_back_is_still_seen_by_the_guards(tmp_path: Path) -> None:
    """Why it prints a commit or a merge rather than doing it: the hooks read the Bash command."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    proceed = _ok(
        "doc-proceed", "--worktree", str(repo), "--phase", "plan", "--slug", "x",
        "--artifact", "a.md", cwd=repo,
    )
    assert guardrails.is_commit_or_push(proceed["steps"][1]["shell"])


# --- literal lines a skill keeps instead of a command --------------------------------------------


def test_the_resolve_line_in_the_skill_is_the_librarys() -> None:
    text = (_PLUGIN / "skills" / "pr-watch" / "SKILL.md").read_text(encoding="utf-8")
    line = re.search(r"`(gh api graphql -f 'query=mutation\S+ -f threadId=<id>)`", text)
    assert line
    assert shlex.split(line.group(1).replace("<id>", "T1")) == pr_watch.resolve_argv("T1")


def test_the_draft_line_in_the_pattern_is_the_librarys() -> None:
    text = (_PLUGIN / "patterns" / "doc-delivery.md").read_text(encoding="utf-8")
    line = re.search(r"`(gh pr ready <n> -R <owner/repo> --undo)`", text)
    assert line
    filled = line.group(1).replace("<n>", "7").replace("<owner/repo>", "o/n")
    assert shlex.split(filled) == doc_delivery.pr_draft_argv("o/n", 7)


# --- a checkout cannot supply a module, and nothing has to be installed --------------------------


_EVERY_COMMAND_ON_A_PLANTED_REPO: list[tuple[list[str], str | None]] = [
    (["--help"], None),
    (["vault-validate", "--repo", "."], None),
    (["vault-recall", "--repo", ".", "--query", "x"], None),
    (["vault-add-note", "--repo", ".", "--json", "-"], '{"name":"a","title":"A","body":"b"}'),
    (["stack-detect", "--repo", "."], None),
    (["incident-classify", "--outage"], None),
    (["review-decision", "--verdict", "changes", "--iteration", "1", "--gate-green", "no"], None),
    (["review-blocks", "--findings-json", "-"], "[]"),
    (["release-summarize", "--current", "1.0.0", "--messages-json", "-"], '["fix: a"]'),
    (["deploy-status", "--environment", "e", "--snapshot", "-"], '{"deploys":[],"alerts":[]}'),
]


@pytest.mark.parametrize(("args", "stdin"), _EVERY_COMMAND_ON_A_PLANTED_REPO)
def test_nothing_planted_runs(
    hostile: tuple[Path, Path], args: list[str], stdin: str | None
) -> None:
    repo, marker = hostile
    done = _run(*args, cwd=repo, stdin=stdin)
    assert done.returncode in (0, 1), done.stderr  # vault-validate: no vault yet
    assert "Traceback" not in done.stderr
    assert done.stdout
    assert not marker.exists()


def test_the_skills_vault_call_as_written_runs_nothing_planted(
    hostile: tuple[Path, Path],
) -> None:
    """The line itself, through a real shell, as the Bash tool would run it."""
    repo, marker = hostile
    text = (_PLUGIN / "skills" / "knowledge" / "SKILL.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith(_PREFIX + "vault-validate"))
    done = subprocess.run(
        ["bash", "-c", line], cwd=repo, env=_env(), capture_output=True, text=True, check=False
    )
    assert json.loads(done.stdout)["exists"] is False
    assert not marker.exists()


def test_the_inline_form_it_replaces_does_run_what_is_planted(hostile: tuple[Path, Path]) -> None:
    """The contrast that keeps the tests above honest: this is a hostile repo, and the old call,
    with the library on its path, does run it."""
    repo, marker = hostile
    env = _env(PYTHONPATH=str(_PLUGIN / "lib"))
    subprocess.run(
        [_python3(), "-c", "from agentic_forge import vault"], cwd=repo, env=env,
        capture_output=True, check=False,
    )
    assert marker.exists()


@pytest.mark.parametrize("pythonpath", [".", "x:", ":x", "sub"])
def test_e_keeps_a_pythonpath_out_of_the_interpreter(tmp_path: Path, pythonpath: str) -> None:
    """What a project's settings could set. `sitecustomize` and `encodings` run before a script's
    first line, so nothing inside the script could have stopped them: only -E does."""
    marker = tmp_path / "marker"
    code = f"open({str(marker)!r}, 'w').close()\n"
    for directory in (tmp_path, tmp_path / "sub"):
        directory.mkdir(exist_ok=True)
        (directory / "sitecustomize.py").write_text(code, encoding="utf-8")
        (directory / "__future__.py").write_text(code, encoding="utf-8")
        (directory / "encodings").mkdir(exist_ok=True)
        (directory / "encodings" / "__init__.py").write_text(code, encoding="utf-8")
    env = _env(PYTHONPATH=pythonpath)
    done = _run("incident-classify", "--outage", cwd=tmp_path, env=env)
    assert done.returncode == 0, done.stderr
    assert not marker.exists()
    # And without -E it does reach them, before any line of the script. A planted `encodings`
    # stops the interpreter starting at all, and with that gone, `sitecustomize` runs.
    without_e = [_python3(), str(_AF), "incident-classify", "--outage"]
    probe = subprocess.run(without_e, cwd=tmp_path, env=env, capture_output=True, check=False)
    assert probe.returncode != 0
    for directory in (tmp_path, tmp_path / "sub"):
        shutil.rmtree(directory / "encodings")
    subprocess.run(without_e, cwd=tmp_path, env=env, capture_output=True, check=False)
    assert marker.exists()


def test_the_library_is_the_plugins_own_with_no_package_installed(tmp_path: Path) -> None:
    """A copy of the plugin alone, as a plugin-only install is, and an interpreter that cannot see
    any site-packages: the commands that need no package work from it."""
    root = tmp_path / "cache" / "plugin"
    shutil.copytree(_PLUGIN / "lib", root / "lib", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "bin").mkdir()
    shutil.copy(_AF, root / "bin" / "af.py")
    repo = tmp_path / "repo"
    repo.mkdir()
    done = subprocess.run(
        [_python3(), "-E", "-S", str(root / "bin" / "af.py"), "incident-classify", "--outage"],
        cwd=repo, env=_env(), capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"severity": "sev1"}
    stack = subprocess.run(
        [_python3(), "-E", "-S", str(root / "bin" / "af.py"), "stack-detect", "--repo", "."],
        cwd=repo, env=_env(), capture_output=True, text=True, check=False,
    )
    assert json.loads(stack.stdout)["pack_paths"] == [
        str(root / "skills" / "engineering-standards" / "SKILL.md")
    ]


def test_it_and_what_it_imports_parse_for_python_3_9() -> None:
    """The syntax half of the floor, here on any interpreter. CI runs the import half under a real
    3.9 through dev/hook_smoke.py."""
    sys.path.insert(0, str(_REPO / "dev"))
    try:
        import hook_smoke
    finally:
        sys.path.pop(0)
    lib = _PLUGIN / "lib" / "agentic_forge"
    modules = [lib / f"{m}.py" for m in hook_smoke.hook_reachable_modules()]
    assert {"pr_watch", "connectors", "release", "stacks", "planning"} <= {p.stem for p in modules}
    for path in (_AF, _PLUGIN / "bin" / "external_review.py", *modules):
        source = path.read_text(encoding="utf-8")
        assert "from __future__ import annotations" in source, path
        ast.parse(source, feature_version=(3, 9))


def test_usage_lists_the_commands(tmp_path: Path) -> None:
    done = _run("--help", cwd=tmp_path)
    assert done.returncode == 0
    assert "vault-add-note" in done.stdout and "pr-state" in done.stdout


# --- a repo-shaped directory does not get to configure git ---------------------------------------


def _repo_shaped_subdir(tmp_path: Path) -> tuple[Path, Path]:
    """A real clone of a repo that commits a directory shaped like a bare repository: its own
    config naming a program, and a signed commit for `log.showSignature` to check. Returns the
    clone's subdirectory and the marker that program would leave."""
    marker = tmp_path / "gpg-ran"
    program = tmp_path / "evil-gpg"
    program.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 1\n", encoding="utf-8")
    program.chmod(0o755)

    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    shaped = origin / "shaped"
    shaped.mkdir()
    _git(shaped, "init", "-q", "--bare", ".")
    (shaped / "config").write_text(
        f"[core]\n\tbare = true\n\trepositoryformatversion = 0\n"
        f"[log]\n\tshowSignature = true\n[gpg]\n\tprogram = {program}\n",
        encoding="utf-8",
    )
    tree = _git(shaped, "--git-dir", str(shaped), "hash-object", "-t", "tree", "-w",
                "--stdin", stdin="").strip()
    signed = (
        f"tree {tree}\nauthor t <t@e> 1 +0000\ncommitter t <t@e> 1 +0000\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n x\n -----END PGP SIGNATURE-----\n\nfix: signed\n"
    )
    commit = _git(shaped, "--git-dir", str(shaped), "hash-object", "-t", "commit", "-w",
                  "--stdin", stdin=signed).strip()
    (shaped / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (shaped / "refs" / "heads" / "master").write_text(commit + "\n", encoding="utf-8")
    (shaped / "refs" / "heads" / "main").write_text(commit + "\n", encoding="utf-8")
    (shaped / "refs" / ".keep").write_text("", encoding="utf-8")
    (shaped / "objects" / ".keep").write_text("", encoding="utf-8")
    shutil.rmtree(shaped / "hooks", ignore_errors=True)
    _git(origin, "add", "-A", "-f")
    _git(origin, "commit", "-q", "-m", "feat: the tree")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    assert (clone / "shaped" / "config").is_file()
    return clone / "shaped", marker


def test_the_shaped_directory_does_fire_without_the_setting(tmp_path: Path) -> None:
    """The contrast: plain `git log` from inside it runs the program its config names."""
    shaped, marker = _repo_shaped_subdir(tmp_path)
    subprocess.run(["git", "-C", str(shaped), "log"], capture_output=True, check=False)
    assert marker.exists()


@pytest.mark.parametrize("repo_flag", [".", "shaped"])
def test_release_commits_does_not_read_a_repo_shaped_directorys_config(
    tmp_path: Path, repo_flag: str
) -> None:
    shaped, marker = _repo_shaped_subdir(tmp_path)
    cwd = shaped if repo_flag == "." else shaped.parent
    message = _refused("release-commits", "--repo", repo_flag, cwd=cwd)
    assert "bare" in message  # git says it will not use one found by looking
    assert not marker.exists()


def test_an_existing_git_config_count_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "tag.sort")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "refname")
    _load_af()._refuse_bare_discovery()
    assert os.environ["GIT_CONFIG_COUNT"] == "2"
    assert os.environ["GIT_CONFIG_KEY_0"] == "tag.sort"
    assert os.environ["GIT_CONFIG_VALUE_0"] == "refname"
    assert os.environ["GIT_CONFIG_KEY_1"] == "safe.bareRepository"
    assert os.environ["GIT_CONFIG_VALUE_1"] == "explicit"
    # and git honours it from that position, in a real process
    shaped, marker = _repo_shaped_subdir(tmp_path)
    env = _env(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="tag.sort", GIT_CONFIG_VALUE_0="refname")
    _refused("release-commits", cwd=shaped, env=env)
    assert not marker.exists()


@pytest.mark.parametrize("count", ["", "junk", "-3"])
def test_a_bad_git_config_count_does_not_stop_the_setting(tmp_path: Path, count: str) -> None:
    shaped, marker = _repo_shaped_subdir(tmp_path)
    done = _run("release-commits", cwd=shaped, env=_env(GIT_CONFIG_COUNT=count))
    assert done.returncode == 1
    assert not marker.exists()


def test_a_linked_worktree_of_a_bare_clone_still_works(tmp_path: Path) -> None:
    """A `.git` file is not a bare repository found by looking, so this layout is unaffected."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    _git(origin, "commit", "-q", "--allow-empty", "-m", "fix: a")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(bare)], check=True)
    worktree = tmp_path / "wt"
    _git(bare, "worktree", "add", "-q", str(worktree))
    assert _ok("release-commits", cwd=worktree)["commits"] == ["fix: a"]
    steps = _ok(
        "doc-proceed", "--worktree", ".", "--phase", "plan", "--slug", "x", "--artifact", "a.md",
        cwd=worktree,
    )["steps"]
    assert steps[0]["argv"][:3] == _SAFE_GIT
    (worktree / "a.md").write_text("x\n", encoding="utf-8")
    subprocess.run(steps[0]["argv"], cwd=worktree, check=True, capture_output=True)
    # What does break, and says so: running from the bare repository's own directory.
    assert "bare" in _refused("release-commits", cwd=bare)


def test_printed_git_lines_carry_the_setting(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    added = _ok("doc-worktree", "--repo", str(repo), "--slug", "x", cwd=tmp_path)["add"]
    assert added["argv"][:3] == _SAFE_GIT
    assert added["shell"].startswith("git -c safe.bareRepository=explicit -C ")
    answer = json.dumps(_pr_answer())
    assert _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=answer)["push"]["argv"][:3] == (
        _SAFE_GIT
    )


# --- without PyYAML or jsonschema (-S hides the site-packages that hold them) ---------------------


_ARTIFACT = (
    "---\ntype: prd\nfeature: search\nstatus: approved\ngoals: [a]\nacceptance: [b]\n---\nBody\n"
)


def test_handoff_load_says_it_checked_nothing_without_the_packages(tmp_path: Path) -> None:
    (tmp_path / "prd.md").write_text(_ARTIFACT, encoding="utf-8")
    done = _run(
        "handoff-load", "--path", "prd.md", "--type", "prd", cwd=tmp_path, interpreter=("-S",)
    )
    assert done.returncode == 3
    assert done.stdout == ""
    assert "needs yaml, jsonschema" in done.stderr
    assert "nothing was checked" in done.stderr
    assert "do not treat the artifact as valid" in done.stderr
    assert "--gate-green unknown" in done.stderr


def test_plan_batches_says_the_same(tmp_path: Path) -> None:
    done = _run("plan-batches", "--plan", "plan.md", cwd=tmp_path, interpreter=("-S",))
    assert done.returncode == 3


def test_recall_works_without_pyyaml_and_says_what_it_lost(tmp_path: Path) -> None:
    note = '{"name":"use-sqlite","title":"Use SQLite","body":"One file.","tags":["db"]}'
    assert _run("vault-add-note", "--json", "-", cwd=tmp_path, stdin=note).returncode == 0
    done = _run("vault-recall", "--query", "sqlite", cwd=tmp_path, interpreter=("-S",))
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert "use-sqlite" in [n["name"] for n in result["notes"]]
    assert "PyYAML is not installed" in result["warnings"][0]
    assert "warnings" not in _ok("vault-recall", "--query", "sqlite", cwd=tmp_path)


@pytest.mark.parametrize(
    ("args", "stdin"),
    [
        (["vault-validate"], None),
        (["vault-scaffold"], None),
        (["vault-add-note", "--json", "-"], '{"name":"a","title":"A","body":"b"}'),
        (["stack-detect"], None),
        (["incident-classify", "--degraded"], None),
        (
            ["review-decision", "--verdict", "approve", "--iteration", "2", "--gate-green", "yes"],
            None,
        ),
        (["review-blocks", "--findings-json", "-"], '[{"severity": "major"}]'),
        (["release-summarize", "--current", "1.0.0", "--messages-json", "-"], '["feat: a"]'),
        (["deploy-status", "--environment", "e", "--snapshot", "-"], '{"deploys":[],"alerts":[]}'),
    ],
)
def test_the_rest_need_neither_package(tmp_path: Path, args: list[str], stdin: str | None) -> None:
    done = _run(*args, cwd=tmp_path, stdin=stdin, interpreter=("-S",))
    assert done.returncode in (0, 1), done.stderr  # vault-validate reports an absent vault
    assert done.stdout.startswith("{"), done.stderr


# --- the vault -----------------------------------------------------------------------------------


def _note(**fields: object) -> str:
    return json.dumps({"name": "a-note", "title": "A note", "body": "Body.", **fields})


def test_a_note_round_trips_and_validates(tmp_path: Path) -> None:
    assert _run("vault-validate", cwd=tmp_path).returncode == 1
    result = _ok(
        "vault-add-note", "--repo", ".", "--json", "-", cwd=tmp_path,
        stdin=_note(tags=["decision", "db/sqlite"], moc="decisions"),
    )
    path = tmp_path / "docs" / "knowledge" / "a-note.md"
    assert result == {"path": "docs/knowledge/a-note.md", "replaced": False}
    assert path.read_text(encoding="utf-8").startswith(
        '---\ntitle: "A note"\ntype: note\ntags: ["decision", "db/sqlite"]\n---\n'
    )
    assert _ok("vault-validate", cwd=tmp_path) == {"ok": True, "exists": True, "problems": []}
    recalled = _ok("vault-recall", "--query", "note", cwd=tmp_path)["notes"]
    assert recalled[0]["name"] == "a-note"
    assert recalled[0]["path"] == "docs/knowledge/a-note.md"
    assert recalled[0]["score"] > 0


def test_a_note_can_come_from_a_file(tmp_path: Path) -> None:
    (tmp_path / "n.json").write_text(_note(), encoding="utf-8")
    assert _ok("vault-add-note", "--json", "n.json", cwd=tmp_path)["replaced"] is False


def test_the_same_name_replaces_and_says_so(tmp_path: Path) -> None:
    _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note())
    assert _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note())["replaced"] is True


def test_a_body_the_shell_would_read_is_left_alone(tmp_path: Path) -> None:
    body = "It costs $(touch pwned) and `touch pwned2`; see [[MOC]]."
    _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note(body=body))
    assert body in (tmp_path / "docs" / "knowledge" / "a-note.md").read_text(encoding="utf-8")
    assert not (tmp_path / "pwned").exists()


@pytest.mark.parametrize(
    ("stdin", "says"),
    [
        ("[]", "must be a JSON object"),
        ("not json", "not JSON"),
        ('{"name": "a", "title": "A"}', "'body'"),
        ('{"title": "A", "body": "b"}', "'name'"),
        (_note(name="../escape"), "invalid note name"),
        (_note(name="sub/dir"), "invalid note name"),
        (_note(name=""), "invalid note name"),
        (_note(name="MOC"), "invalid note name"),  # upper case is not a note name at all
        (_note(name="moc"), "reserved"),  # the root map, on a filesystem that folds case
        (_note(name="readme"), "reserved"),
        (_note(name="a", moc="moc"), "reserved"),
        (_note(name="a", moc="readme"), "reserved"),
        (_note(name=7), "'name'"),
        (_note(title=""), "'title'"),
        (_note(title="x" * 201), "'title'"),
        (_note(title="two\nlines"), "line break"),
        (_note(body=""), "'body'"),
        (_note(body=7), "'body'"),
        # An id of its own: pytest before 9.2 puts a long string param in the test's id, the id in
        # PYTEST_CURRENT_TEST, and a child process cannot start with one that long (E2BIG).
        pytest.param(_note(body="x" * (1024 * 1024 + 1)), "'body'", id="body-over-cap"),
        (_note(tags="decision"), "'tags'"),
        (_note(tags=["a b"]), "'tags'"),
        (_note(tags=["a]"]), "'tags'"),
        (_note(tags=["t"] * 33), "'tags'"),
        (_note(moc="../up"), "invalid MOC name"),
        (_note(moc=None), "'moc' must be a string"),
        (_note(type="moc"), "unknown note field"),
    ],
)
def test_a_bad_note_is_refused_before_anything_is_written(
    tmp_path: Path, stdin: str, says: str
) -> None:
    assert says in _refused("vault-add-note", "--json", "-", cwd=tmp_path, stdin=stdin)
    assert not (tmp_path / "docs").exists()


@pytest.mark.parametrize(
    "title",
    ["a: b", "*x", "true", "123", "2026-01-01", " x", "# heading", "a # b", "it's", '"q"', "null",
     "Use SQLite", "C#", "Заметка: выбор", "x: y: z"],
)
def test_every_title_reads_back_as_the_string_it_was(tmp_path: Path, title: str) -> None:
    """A title with `: ` used to save with frontmatter nothing could read, and lose its tags."""
    _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note(title=title, tags=["t"]))
    note = vault.load_vault(tmp_path).notes["a-note"]
    assert note.title == title
    assert note.type == "note"
    assert note.tags == ("t",)


@pytest.mark.parametrize("tag", ["123", "true", "null", "2026-01-01", "a/b"])
def test_every_tag_reads_back_as_the_string_it_was(tmp_path: Path, tag: str) -> None:
    _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note(tags=[tag, "other"]))
    assert vault.load_vault(tmp_path).notes["a-note"].tags == (tag, "other")


def test_a_note_from_before_quoting_still_loads(tmp_path: Path) -> None:
    (tmp_path / "docs" / "knowledge").mkdir(parents=True)
    (tmp_path / "docs" / "knowledge" / "old.md").write_text(
        "---\ntitle: Plain Old\ntype: note\ntags: [x, y]\n---\n# Plain Old\nBody\n",
        encoding="utf-8",
    )
    note = vault.load_vault(tmp_path).notes["old"]
    assert (note.title, note.tags) == ("Plain Old", ("x", "y"))


def test_a_map_of_content_cannot_be_replaced_by_a_note(tmp_path: Path) -> None:
    _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note(moc="decisions"))
    moc = tmp_path / "docs" / "knowledge" / "decisions.md"
    before = moc.read_text(encoding="utf-8")
    message = _refused("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note(name="decisions"))
    assert "map-of-content" in message
    assert moc.read_text(encoding="utf-8") == before


def test_a_refused_note_is_reported_and_nothing_written_elsewhere(tmp_path: Path) -> None:
    repo, elsewhere = tmp_path / "repo", tmp_path / "elsewhere"
    (repo / "docs").mkdir(parents=True)
    elsewhere.mkdir()
    (repo / "docs" / "knowledge").symlink_to(elsewhere, target_is_directory=True)
    message = _refused("vault-add-note", "--json", "-", cwd=repo, stdin=_note())
    assert "knowledge.allow_external_vault" in message
    assert list(elsewhere.iterdir()) == []
    message = _refused("vault-scaffold", cwd=repo)
    assert "knowledge.allow_external_vault" in message


def test_a_linked_note_is_refused(tmp_path: Path) -> None:
    _ok("vault-scaffold", cwd=tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("keep me", encoding="utf-8")
    (tmp_path / "docs" / "knowledge" / "a-note.md").symlink_to(victim)
    _refused("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note())
    assert victim.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize(
    "args", [["vault-validate"], ["vault-scaffold"], ["vault-recall", "--query", "x"]]
)
def test_a_missing_repo_directory_is_refused(tmp_path: Path, args: list[str]) -> None:
    assert "no such directory" in _refused(*args, "--repo", "nope", cwd=tmp_path)
    assert not (tmp_path / "nope").exists()


def test_recall_refuses_what_it_cannot_search_on(tmp_path: Path) -> None:
    assert "--query" in _refused("vault-recall", "--query", " ", cwd=tmp_path)
    assert _ok("vault-recall", "--query", "x", cwd=tmp_path) == {"notes": []}


def test_input_past_the_cap_is_refused(tmp_path: Path) -> None:
    big = '"' + "x" * (8 * 1024 * 1024) + '"'
    message = _refused("review-blocks", "--findings-json", "-", cwd=tmp_path, stdin=big)
    assert "larger than" in message


def test_input_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_bytes(b'{"name": "\xff"}')
    _refused("vault-add-note", "--json", "bad.json", cwd=tmp_path)


def test_an_unreadable_input_file_is_refused(tmp_path: Path) -> None:
    _refused("vault-add-note", "--json", "absent.json", cwd=tmp_path)


def test_input_nested_too_deep_is_refused(tmp_path: Path) -> None:
    deep = "[" * 200_000
    message = _refused("review-blocks", "--findings-json", "-", cwd=tmp_path, stdin=deep)
    assert "nested" in message or "not JSON" in message


# --- handoff ------------------------------------------------------------------------------------


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return path.name


def test_handoff_load_reports_the_header_and_readiness(tmp_path: Path) -> None:
    name = _write(tmp_path / "prd.md", _ARTIFACT)
    result = _ok("handoff-load", "--path", name, "--type", "prd", cwd=tmp_path)
    assert result["ready"] is True
    assert result["type"] == "prd"
    assert result["header"]["goals"] == ["a"]
    assert "body" not in result  # the model reads the file; the report stays small


def test_an_escalated_artifact_is_valid_and_not_ready(tmp_path: Path) -> None:
    name = _write(tmp_path / "prd.md", _ARTIFACT.replace("approved", "in-review"))
    assert _ok("handoff-load", "--path", name, "--type", "prd", cwd=tmp_path)["ready"] is False


@pytest.mark.parametrize(
    ("text", "artifact_type", "says"),
    [
        (_ARTIFACT, "plan", "'plan' was expected"),
        (_ARTIFACT, "nonsense", "unknown artifact type"),
        ("no frontmatter", "prd", "frontmatter"),
        ("---\ntype: prd\nthen: [a] b\n---\n", "prd", "invalid YAML"),
        ("---\ntype: prd\nfeature: x\nstatus: draft\n---\n", "prd", "goals"),
    ],
)
def test_handoff_load_refuses_what_is_wrong(
    tmp_path: Path, text: str, artifact_type: str, says: str
) -> None:
    name = _write(tmp_path / "a.md", text)
    assert says in _refused("handoff-load", "--path", name, "--type", artifact_type, cwd=tmp_path)


def test_handoff_load_on_a_missing_file_is_refused(tmp_path: Path) -> None:
    message = _refused("handoff-load", "--path", "a.md", "--type", "prd", cwd=tmp_path)
    assert "No such file" in message


def test_a_header_with_a_date_comes_out_as_json(tmp_path: Path) -> None:
    text = _ARTIFACT.replace("goals: [a]", "date: 2026-11-03\nratio: .nan\ngoals: [a]")
    name = _write(tmp_path / "prd.md", text)
    header = _ok("handoff-load", "--path", name, "--type", "prd", cwd=tmp_path)["header"]
    assert header["date"] == "2026-11-03"
    assert header["ratio"] == "nan"


def test_a_yaml_alias_is_refused_before_it_can_expand(tmp_path: Path) -> None:
    levels = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for i in range(1, 12):
        previous = f"*a{i - 1}"
        levels.append(f"a{i}: &a{i} [{', '.join([previous] * 10)}]")
    text = _ARTIFACT.replace("goals: [a]", "\n".join(levels) + "\ngoals: [a]")
    name = _write(tmp_path / "prd.md", text)
    started = time.monotonic()
    message = _refused("handoff-load", "--path", name, "--type", "prd", cwd=tmp_path)
    assert "alias" in message
    assert time.monotonic() - started < 10


def test_an_artifact_must_be_a_regular_file_and_not_a_link(tmp_path: Path) -> None:
    (tmp_path / "zero.md").symlink_to("/dev/zero")
    (tmp_path / "real.md").write_text(_ARTIFACT, encoding="utf-8")
    (tmp_path / "linked.md").symlink_to(tmp_path / "real.md")
    started = time.monotonic()
    assert "symlink" in _refused("handoff-load", "--path", "zero.md", "--type", "prd", cwd=tmp_path)
    assert time.monotonic() - started < 10
    assert "symlink" in _refused(
        "handoff-load", "--path", "linked.md", "--type", "prd", cwd=tmp_path
    )
    assert "regular file" in _refused(
        "handoff-load", "--path", "/dev/zero", "--type", "prd", cwd=tmp_path
    )
    os.mkfifo(tmp_path / "pipe.md")
    assert "regular file" in _refused(
        "handoff-load", "--path", "pipe.md", "--type", "prd", cwd=tmp_path
    )
    assert "regular file" in _refused("plan-batches", "--plan", "/dev/zero", cwd=tmp_path)


def test_an_artifact_past_its_cap_is_refused_unparsed(tmp_path: Path) -> None:
    name = _write(tmp_path / "big.md", _ARTIFACT + "x" * (2 * 1024 * 1024))
    assert "larger than" in _refused("handoff-load", "--path", name, "--type", "prd", cwd=tmp_path)


def test_a_huge_string_counts_against_the_report(tmp_path: Path) -> None:
    """A wide value uses the budget as a deep one does: strings are charged by length."""
    comment = {"body": "b" * (5 * 1024 * 1024), "path": "a.py", "line": 1,
               "author": {"login": "ann"}, "authorAssociation": "MEMBER"}
    thread = {"id": "T1", "isResolved": False, "comments": {"nodes": [comment]}}
    answer = _pr_answer(reviewThreads={"nodes": [thread]})
    message = _refused("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=json.dumps(answer))
    assert "too large" in message


def test_a_message_from_a_file_cannot_write_to_the_terminal(tmp_path: Path) -> None:
    name = _write(tmp_path / "a.md", "---\ntitle: a: \x1b[31mred\n---\n")
    message = _refused("handoff-load", "--path", name, "--type", "prd", cwd=tmp_path)
    assert "\x1b" not in message


def test_a_long_message_is_cut(tmp_path: Path) -> None:
    message = _refused("handoff-load", "--path", "x" * 100_000, "--type", "prd", cwd=tmp_path)
    assert len(message) < 2100


# --- the review loop and the plan ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdict", "iteration", "green", "decision"),
    [
        ("approve", 1, "yes", "proceed"),
        ("approve", 1, "no", "revise"),
        ("changes", 2, "yes", "revise"),
        ("changes", 3, "yes", "escalate"),
        ("approve", 2, "no", "revise"),
        ("approve", 3, "no", "escalate"),  # a gate that stays red cannot revise for ever
        ("garbled", 3, "yes", "escalate"),
        # The gate could not run. `no` would revise for ever on a machine that cannot turn it green.
        ("approve", 1, "unknown", "escalate"),
        ("changes", 1, "unknown", "escalate"),
    ],
)
def test_review_decision(
    tmp_path: Path, verdict: str, iteration: int, green: str, decision: str
) -> None:
    result = _ok(
        "review-decision", "--verdict", verdict, "--iteration", str(iteration),
        "--gate-green", green, cwd=tmp_path,
    )
    assert result == {"decision": decision}


def test_the_handoff_pattern_says_exit_3_stops_the_loop() -> None:
    text = " ".join((_PLUGIN / "patterns" / "handoff.md").read_text(encoding="utf-8").split())
    assert "That means stop" in text
    assert "`in-review`" in text and "commit nothing" in text and "--gate-green unknown" in text


def test_review_decision_refuses_a_count_from_zero(tmp_path: Path) -> None:
    _refused(
        "review-decision", "--verdict", "approve", "--iteration", "0", "--gate-green", "yes",
        cwd=tmp_path,
    )


def test_gate_green_is_not_free_text(tmp_path: Path) -> None:
    done = _run(
        "review-decision", "--verdict", "approve", "--iteration", "1", "--gate-green", "maybe",
        cwd=tmp_path,
    )
    assert done.returncode == 2


@pytest.mark.parametrize(
    ("findings", "blocks"),
    [
        ('[{"severity": "major"}]', True),
        ('{"findings": [{"severity": "blocker"}]}', True),
        ('[{"severity": "minor"}]', False),
        ("[]", False),
    ],
)
def test_review_blocks(tmp_path: Path, findings: str, blocks: bool) -> None:
    result = _ok("review-blocks", "--findings-json", "-", cwd=tmp_path, stdin=findings)
    assert result == {"blocks_approve": blocks}


def test_review_blocks_refuses_what_is_not_a_list(tmp_path: Path) -> None:
    assert "JSON array" in _refused(
        "review-blocks", "--findings-json", "-", cwd=tmp_path, stdin='{"x": 1}'
    )


def _plan(tasks: str) -> str:
    return f"---\ntype: plan\nfeature: x\nstatus: draft\ntasks:\n{tasks}---\n"


def test_plan_batches_from_a_plan_file(tmp_path: Path) -> None:
    name = _write(tmp_path / "plan.md", _plan("  - id: a\n  - {id: b, deps: [a]}\n  - {id: c}\n"))
    assert _ok("plan-batches", "--plan", name, cwd=tmp_path) == {"levels": [["a", "c"], ["b"]]}


@pytest.mark.parametrize(
    ("tasks", "says"),
    [
        ("  - {id: 1, deps: [2]}\n  - {id: 2, deps: [1]}\n", "cycle"),
        ("  - {id: 1, deps: [9]}\n", "unknown task"),
        ("  - {id: 1}\n  - {id: 1}\n", "duplicate"),
        ("  - 1\n", "tasks/0"),
    ],
)
def test_plan_batches_refuses_a_bad_graph(tmp_path: Path, tasks: str, says: str) -> None:
    name = _write(tmp_path / "plan.md", _plan(tasks))
    assert says in _refused("plan-batches", "--plan", name, cwd=tmp_path)


def test_plan_batches_needs_a_plan(tmp_path: Path) -> None:
    assert _run("plan-batches", cwd=tmp_path).returncode == 2


# --- stack ---------------------------------------------------------------------------------------


def test_stack_detect(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    result = _ok("stack-detect", "--repo", ".", cwd=tmp_path)
    assert result["primary"]["stack_id"] == "python"
    assert result["profiles"][0] == result["primary"]
    assert result["pack_paths"] == [
        str(_PLUGIN / "skills" / "engineering-standards" / "SKILL.md"),
        str(_PLUGIN / "skills" / "python-patterns" / "SKILL.md"),
    ]
    assert all(Path(p).is_file() for p in result["pack_paths"])
    assert "python" in result["summary"]


def test_stack_detect_on_an_unknown_repo_reads_the_standards_only(tmp_path: Path) -> None:
    result = _ok("stack-detect", cwd=tmp_path)
    assert result["primary"]["stack_id"] == "unknown"
    assert len(result["pack_paths"]) == 1


def test_a_file_of_newlines_does_not_stall_the_hint(tmp_path: Path) -> None:
    """Quadratic before, 100 KB took over a minute, and the commit gate comes through here."""
    (tmp_path / "CLAUDE.md").write_text("\n" * 200_000, encoding="utf-8")
    started = time.monotonic()
    assert stacks.detect(tmp_path)[0].stack_id == "unknown"
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("stack: python\n", "python"),
        ("# Title\n\n  - **stack**: rust\n", "rust"),
        ("> stack = go\n", "go"),
        ("\r\n\r\nstack: python\r\n", "python"),
        ("a stack: python\n", "unknown"),  # not at the start of a line
        ("stack:\npython\n", "unknown"),  # never bridges to the next line
    ],
)
def test_the_hint_is_read_one_line_at_a_time(tmp_path: Path, text: str, found: str) -> None:
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    assert stacks.detect(tmp_path)[0].stack_id == found


def test_a_hint_past_the_cap_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("x\n" * 200_000 + "stack: python\n", encoding="utf-8")
    assert stacks.detect(tmp_path)[0].stack_id == "unknown"


# --- release -------------------------------------------------------------------------------------


@pytest.fixture
def tagged(tmp_path: Path) -> Path:
    repo = tmp_path / "tagged"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "chore: first")
    _git(repo, "tag", "v1.0.0")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "feat: a\n\nBody line.")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fix: b")
    return repo


def test_release_commits_since_the_latest_tag(tagged: Path) -> None:
    commits = _ok("release-commits", "--repo", ".", cwd=tagged)["commits"]
    assert commits == ["fix: b", "feat: a\n\nBody line."]


def test_a_repo_with_no_tags_gives_all_of_head(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "fix: a")
    assert _ok("release-commits", cwd=tmp_path)["commits"] == ["fix: a"]


def test_release_commits_says_so_outside_a_repo(tmp_path: Path) -> None:
    """The library used to answer [], which reads as nothing to release."""
    assert "git log exited" in _refused("release-commits", "--repo", ".", cwd=tmp_path)


def test_a_described_tag_cannot_be_a_flag_for_git(tagged: Path) -> None:
    target = tagged / "pwned"
    _git(tagged, "update-ref", f"refs/tags/--output={target}", "HEAD")
    message = _refused("release-commits", cwd=tagged)
    assert "reads as an option" in message
    assert not target.exists()


def test_the_library_refuses_a_tag_it_cannot_resolve(tagged: Path) -> None:
    with pytest.raises(ValueError, match="no such tag"):
        release.commits_since(tagged, "v9.9.9")
    with pytest.raises(ValueError, match="reads as an option"):
        release.commits_since(tagged, "--output=x")
    assert release.commits_since(tagged, "v1.0.0") == ["fix: b", "feat: a\n\nBody line."]


def test_a_git_log_failure_reaches_the_caller(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")  # no commits: HEAD does not resolve
    with pytest.raises(ValueError, match="git log exited"):
        release.commits_since(tmp_path)


def test_the_two_release_commands_pipe_together(tagged: Path) -> None:
    commits = _run("release-commits", cwd=tagged).stdout
    result = _ok(
        "release-summarize", "--current", "1.0.0", "--messages-json", "-", cwd=tagged, stdin=commits
    )
    assert result["version"] == "1.1.0"
    assert result["bump"] == "minor"
    assert result["scheme"] == "semver"
    assert result["groups"] == {"Added": ["a"], "Fixed": ["b"]}


def _this_month() -> str:
    now = time.gmtime()
    return f"{now.tm_year}.{now.tm_mon}"


def test_release_takes_calver_from_the_current_version(tmp_path: Path) -> None:
    result = _ok(
        "release-summarize", "--current", f"{_this_month()}.3", "--messages-json", "-",
        cwd=tmp_path, stdin='["fix: a"]',
    )
    assert result["scheme"] == "calver"
    assert result["version"] == f"{_this_month()}.4"


def test_release_calver_uses_todays_utc_month(tmp_path: Path) -> None:
    result = _ok(
        "release-summarize", "--current", "1.2.3", "--scheme", "calver", "--messages-json", "-",
        cwd=tmp_path, stdin='["fix: a"]',
    )
    assert result["version"] == f"{_this_month()}.1"


def test_release_scheme_can_be_forced_to_semver(tmp_path: Path) -> None:
    result = _ok(
        "release-summarize", "--current", "2026.7.3", "--scheme", "semver", "--messages-json", "-",
        cwd=tmp_path, stdin='["fix: a"]',
    )
    assert result["version"] == "2026.7.4"
    assert result["scheme"] == "semver"


def test_release_breaking_is_called_out(tmp_path: Path) -> None:
    result = _ok(
        "release-summarize", "--current", "1.0.0", "--messages-json", "-", cwd=tmp_path,
        stdin='["feat!: gone"]',
    )
    assert result["version"] == "2.0.0"
    assert result["breaking"] == ["gone"]


def test_a_repo_with_no_conventional_commits_still_has_something_to_list(tmp_path: Path) -> None:
    commits = ["Release 1.2.3\n\nBody line.", "PR watcher: a fix", "chore: x"]
    stdin = json.dumps({"commits": commits})
    result = _ok("release-summarize", "--current", "1.0.0", "--messages-json", "-", cwd=tmp_path,
                 stdin=stdin)
    assert result["groups"] == {}
    assert "PR watcher: a fix" in result["uncategorised"]
    assert "Release 1.2.3" in result["uncategorised"]
    empty = _ok("release-summarize", "--current", "1.0.0", "--messages-json", "-", cwd=tmp_path,
                stdin="[]")
    assert (empty["uncategorised"], empty["groups"]) == ([], {})


def test_the_release_skill_says_what_to_do_with_them() -> None:
    text = " ".join((_PLUGIN / "skills" / "release" / "SKILL.md").read_text("utf-8").split())
    assert "When `groups` is empty, list those subjects under Changed, unedited" in text
    assert "say there is nothing to release and stop" in text


def test_a_long_subject_does_not_stall_the_classifier() -> None:
    started = time.monotonic()
    change = release.classify("feat: a" + " " * 80_000 + "b")
    assert time.monotonic() - started < 2
    assert change.type == "feat"


def test_a_tag_named_head_counts_as_no_tag(tagged: Path) -> None:
    # A newer git refuses `git tag HEAD`, but a ref of that name can still arrive by a fetch.
    head = subprocess.run(
        ["git", "-C", str(tagged), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _git(tagged, "update-ref", "refs/tags/HEAD", head)
    commits = _ok("release-commits", cwd=tagged)["commits"]
    assert "fix: b" in commits
    assert release.commits_since(tagged, "HEAD") == release.commits_since(tagged)


@pytest.mark.parametrize(
    ("args", "stdin", "says"),
    [
        (["--current", "nope"], "[]", "not a MAJOR.MINOR.PATCH"),
        (["--current", "1.0.0"], "[1]", "must be a string"),
        (["--current", "1.0.0"], "{}", "JSON array"),
    ],
)
def test_release_summarize_refuses(
    tmp_path: Path, args: list[str], stdin: str, says: str
) -> None:
    message = _refused(
        "release-summarize", *args, "--messages-json", "-", cwd=tmp_path, stdin=stdin
    )
    assert says in message


# --- deploys and incidents -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "severity"),
    [
        (["--outage"], "sev1"),
        (["--data-loss"], "sev1"),
        (["--degraded"], "sev2"),
        (["--degraded", "--workaround"], "sev3"),
        ([], "sev4"),
    ],
)
def test_incident_classify(tmp_path: Path, flags: list[str], severity: str) -> None:
    assert _ok("incident-classify", *flags, cwd=tmp_path) == {"severity": severity}


def _fixture(name: str) -> Path:
    return _PLUGIN / "eval" / "fixtures" / "deploy-watch" / name


@pytest.mark.parametrize(
    ("name", "health"), [("prod-failing.json", "failing"), ("prod-healthy.json", "healthy")]
)
def test_deploy_status_reads_the_eval_fixtures(tmp_path: Path, name: str, health: str) -> None:
    result = _ok(
        "deploy-status", "--environment", "production", "--snapshot", str(_fixture(name)),
        cwd=tmp_path,
    )
    assert result["pipeline"] == health
    assert result["environment"] == "production"


def test_deploy_status_leaves_out_another_environments_records(tmp_path: Path) -> None:
    snapshot = {
        "deploys": [
            {"sha": "a", "status": "failing", "environment": "staging"},
            {"sha": "b", "status": "passing"},
        ],
        "alerts": [
            {"severity": "critical", "summary": "theirs", "environment": "staging"},
            {"severity": "info", "summary": "ours"},
        ],
    }
    result = _ok(
        "deploy-status", "--environment", "production", "--snapshot", "-", cwd=tmp_path,
        stdin=json.dumps(snapshot),
    )
    assert result["pipeline"] == "healthy"
    assert [d["sha"] for d in result["deploys"]] == ["b"]
    assert result["alerts"] == {"info": 1}


def test_a_snapshot_all_for_another_environment_is_not_healthy(tmp_path: Path) -> None:
    """A failing deploy under a wrong --environment used to read as healthy."""
    snapshot = {"deploys": [
        {"sha": "a", "status": "failing", "environment": "prod"},
        {"sha": "b", "status": "passing", "environment": "prod-eu"},
    ], "alerts": []}
    message = _refused(
        "deploy-status", "--environment", "production", "--snapshot", "-", cwd=tmp_path,
        stdin=json.dumps(snapshot),
    )
    assert "another environment" in message and "prod, prod-eu" in message


def test_alerts_all_for_another_environment_are_refused_too(tmp_path: Path) -> None:
    snapshot = {"deploys": [], "alerts": [
        {"severity": "critical", "summary": "x", "environment": "prod"},
    ]}
    message = _refused(
        "deploy-status", "--environment", "production", "--snapshot", "-", cwd=tmp_path,
        stdin=json.dumps(snapshot),
    )
    assert "another environment" in message and "prod" in message


@pytest.mark.parametrize(
    ("snapshot", "says"),
    [
        ("[]", "must be a JSON object"),
        ('{"alerts": []}', "deploys"),
        ('{"deploys": []}', "alerts"),
        ('{"deploys": [1], "alerts": []}', "must be an object"),
        # Both would otherwise read as healthy.
        ('{"deploys": [{"sha": "a", "status": "success"}], "alerts": []}', "status must be one of"),
        ('{"deploys": [], "alerts": [{"severity": "page"}]}', "severity must be one of"),
    ],
)
def test_deploy_status_refuses_a_snapshot_it_would_misread(
    tmp_path: Path, snapshot: str, says: str
) -> None:
    message = _refused(
        "deploy-status", "--environment", "e", "--snapshot", "-", cwd=tmp_path, stdin=snapshot
    )
    assert says in message


def _github_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    if repo.exists():
        return repo
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "https://github.com/o/n.git")
    return repo


_PASSING_RUN = [{
    "headSha": "abcdef1234", "status": "completed", "conclusion": "success",
    "createdAt": "2026-11-03T00:00:00Z", "workflowName": "ci",
}]


def test_alerts_from_elsewhere_go_with_the_live_pipeline(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    env = _fake_gh(tmp_path, _PASSING_RUN)
    env.pop("GRAFANA_URL", None)
    alerts = json.dumps([{"severity": "critical", "summary": "down", "source": "mcp"}])
    done = _run(
        "deploy-status", "--environment", "e", "--alerts-json", "-", "--repo", ".", cwd=repo,
        env=env, stdin=alerts,
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["pipeline"] == "failing"
    assert result["alerts"] == {"critical": 1}
    assert result["deploys"][0]["sha"] == "abcdef1"  # and the deploys did come from gh
    assert _gh_calls(tmp_path)[0][:2] == ["run", "list"]
    # the same, under the object shape
    wrapped = json.dumps({"alerts": json.loads(alerts)})
    assert json.loads(_run(
        "deploy-status", "--environment", "e", "--alerts-json", "-", cwd=repo, env=env,
        stdin=wrapped,
    ).stdout)["pipeline"] == "failing"


@pytest.mark.parametrize(
    "args",
    [
        ["--snapshot", "-", "--repo", "."],
        ["--snapshot", "-", "--alerts-json", "a.json"],
    ],
)
def test_a_snapshot_does_not_combine_with_a_live_source(tmp_path: Path, args: list[str]) -> None:
    """An alerts-only snapshot with --repo used to report `healthy`, having ignored --repo."""
    done = _run(
        "deploy-status", "--environment", "e", *args, cwd=tmp_path,
        stdin='{"deploys":[],"alerts":[{"severity":"critical","summary":"x"}]}',
    )
    assert done.returncode == 2
    assert done.stdout == ""


def test_no_source_is_not_healthy(tmp_path: Path) -> None:
    """No gh and no Grafana used to read `healthy` from empty lists. Not read is not none."""
    env = _env(PATH=str(tmp_path))  # no gh, no git
    env.pop("GRAFANA_URL", None)
    result = _ok("deploy-status", "--environment", "e", cwd=tmp_path, env=env)
    assert result["pipeline"] == "unknown"
    assert "gh is not on PATH" in result["unavailable"]["pipeline"]
    assert "no alert source" in result["unavailable"]["alerts"]


def test_a_green_pipeline_with_no_alert_source_says_what_it_did_not_read(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    env = _fake_gh(tmp_path, _PASSING_RUN)
    env.pop("GRAFANA_URL", None)
    result = _ok("deploy-status", "--environment", "e", "--repo", ".", cwd=repo, env=env)
    assert result["pipeline"] == "healthy"
    assert list(result["unavailable"]) == ["alerts"]
    assert result["deploys"][0]["sha"] == "abcdef1"


def test_a_failing_run_is_still_failing_with_alerts_unread(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    env = _fake_gh(tmp_path, [{**_PASSING_RUN[0], "conclusion": "failure"}])
    env.pop("GRAFANA_URL", None)
    result = _ok("deploy-status", "--environment", "e", "--repo", ".", cwd=repo, env=env)
    assert result["pipeline"] == "failing"
    assert "alerts" in result["unavailable"]


def _run_of(workflow: str, conclusion: str, at: str) -> dict[str, str]:
    return {"headSha": "abcdef1234", "status": "completed", "conclusion": conclusion,
            "createdAt": at, "workflowName": workflow}


def _assess_runs(tmp_path: Path, runs: list[dict[str, str]]) -> Any:
    repo = _github_repo(tmp_path)
    env = _fake_gh(tmp_path, runs)
    return _ok("deploy-status", "--environment", "e", "--alerts-json", "-", "--repo", ".",
               cwd=repo, env=env, stdin="[]")


def test_a_green_lint_does_not_hide_a_failed_deploy(tmp_path: Path) -> None:
    result = _assess_runs(tmp_path, [
        _run_of("Lint", "success", "2026-11-03T11:00:00Z"),
        _run_of("Deploy production", "failure", "2026-11-03T10:00:00Z"),
    ])
    assert result["pipeline"] == "failing"
    assert [d["workflow"] for d in result["deploys"]] == ["Lint", "Deploy production"]


def test_a_later_green_run_of_the_same_workflow_is_the_answer(tmp_path: Path) -> None:
    result = _assess_runs(tmp_path, [
        _run_of("Deploy production", "success", "2026-11-03T11:00:00Z"),
        _run_of("Deploy production", "failure", "2026-11-03T10:00:00Z"),
    ])
    assert result["pipeline"] == "healthy"


def test_a_cancelled_latest_run_is_not_a_pass(tmp_path: Path) -> None:
    runs = [_run_of("Deploy production", "cancelled", "2026-11-03T12:00:00Z")]
    assert _assess_runs(tmp_path, runs)["pipeline"] == "degraded"


def test_the_librarys_health_is_per_workflow_for_the_digest_too() -> None:
    deploys = [ops.Deploy("a", "passing", "e", workflow="Lint"),
               ops.Deploy("b", "failing", "e", workflow="Deploy")]
    assert ops.rollout_health(deploys, []) == "failing"
    unnamed = [ops.Deploy("a", "passing", "e"), ops.Deploy("b", "failing", "e")]
    assert ops.rollout_health(unnamed, []) == "healthy"  # no names: the newest speaks for all


@pytest.mark.parametrize(
    ("first", "second", "health"),
    [
        (("a", "passing", "10:00"), ("b", "failing", "11:00"), "failing"),
        (("b", "failing", "11:00"), ("a", "passing", "10:00"), "failing"),
        (("a", "failing", "10:00"), ("b", "passing", "11:00"), "healthy"),
    ],
)
def test_a_snapshots_order_is_by_time_not_by_position(
    tmp_path: Path, first: tuple[str, str, str], second: tuple[str, str, str], health: str
) -> None:
    deploys = [{"sha": s, "status": st, "at": at} for s, st, at in (first, second)]
    stdin = json.dumps({"deploys": deploys, "alerts": []})
    args = ("deploy-status", "--environment", "e", "--snapshot", "-")
    result = _ok(*args, cwd=tmp_path, stdin=stdin)
    assert result["pipeline"] == health


def test_an_undated_snapshot_cannot_say_which_is_latest(tmp_path: Path) -> None:
    two = {"deploys": [{"sha": "a", "status": "failing"}, {"sha": "b", "status": "passing"}],
           "alerts": []}
    args = ("deploy-status", "--environment", "e", "--snapshot", "-")
    assert "'at'" in _refused(*args, cwd=tmp_path, stdin=json.dumps(two))
    one = {"deploys": [{"sha": "a", "status": "cancelled"}], "alerts": []}
    assert _ok(*args, cwd=tmp_path, stdin=json.dumps(one))["pipeline"] == "degraded"


def test_deploy_status_says_unknown_when_gh_cannot_answer(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    env = _fake_gh(tmp_path, "rate limited", code=1)
    env.pop("GRAFANA_URL", None)
    done = _run("deploy-status", "--environment", "e", "--repo", ".", cwd=repo, env=env)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["pipeline"] == "unknown"
    assert "pipeline" in result["unavailable"]


def test_alerts_active_with_no_provider_does_not_say_none(tmp_path: Path) -> None:
    env = _env()
    env.pop("GRAFANA_URL", None)
    message = _refused("alerts-active", "--environment", "e", cwd=tmp_path, env=env)
    assert "no alert source" in message and "report them as unknown" in message


def test_alerts_active_refuses_to_call_an_outage_no_alerts(tmp_path: Path) -> None:
    """A source that cannot answer is not an empty one (ADR 0094). Port 9: nothing listens there."""
    done = _run(
        "alerts-active", "--environment", "e", cwd=tmp_path,
        env=_env(GRAFANA_URL="http://127.0.0.1:9", GRAFANA_TOKEN="t"),
    )
    assert done.returncode == 1
    assert done.stdout == ""
    assert "report them as unknown" in done.stderr


@pytest.fixture
def grafana() -> Iterator[str]:
    alerts = [
        {
            "labels": {"severity": "critical", "alertname": "Down"},
            "annotations": {"summary": "the site is down"}, "status": {"state": "active"},
        },
        {
            "labels": {"severity": "warning", "alertname": "Slow"},
            "annotations": {"summary": "p95 high"}, "status": {"state": "active"},
        },
    ]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- the stdlib's name
            body = json.dumps(alerts).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join()


def test_alerts_active_reports_real_alerts_and_their_counts(tmp_path: Path, grafana: str) -> None:
    result = _ok(
        "alerts-active", "--environment", "production", cwd=tmp_path,
        env=_env(
            GRAFANA_URL=grafana, GRAFANA_TOKEN="t", NO_PROXY="127.0.0.1", no_proxy="127.0.0.1"
        ),
    )
    assert result["environment"] == "production"
    assert result["triage"] == {"critical": 1, "warning": 1}
    assert [a["summary"] for a in result["alerts"]] == ["the site is down", "p95 high"]
    assert result["alerts"][0]["severity"] == "critical"


# --- pull requests -------------------------------------------------------------------------------


def _pr_answer(**over: object) -> dict[str, object]:
    pull_request = {
        "number": 7, "headRefName": "feat-x", "headRefOid": _OID, "baseRefName": "main",
        "isCrossRepository": False, "mergeable": "MERGEABLE", "isDraft": False, "state": "OPEN",
        "reviewThreads": {"nodes": []}, "reviews": {"nodes": []},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        **over,
    }
    return {"data": {"repository": {"pullRequest": pull_request}}}


def _thread(
    thread_id: str, author: str, association: str = "MEMBER", kind: str = "User"
) -> dict[str, object]:
    comment = {
        "body": "Please fix", "path": "a.py", "line": 3, "authorAssociation": association,
        "author": {"login": author, "__typename": kind},
    }
    return {"id": thread_id, "isResolved": False, "comments": {"nodes": [comment]}}


_LIVE = ("pr-state", "--owner", "o", "--name", "n", "--number", "7")


def test_pr_state_from_gh(tmp_path: Path) -> None:
    env = _fake_gh(tmp_path, _pr_answer())
    result = _ok(*_LIVE, cwd=_github_repo(tmp_path), env=env)
    assert result["source"] == "live"
    assert result["number"] == 7
    assert result["head_oid"] == _OID
    assert result["merge_gate"] == {"ready": True, "reasons": []}
    assert result["settings"]["merges_here"] is False  # off by default
    assert result["merge"] is None
    logged = _gh_calls(tmp_path)[0]
    assert logged[:2] == ["api", "graphql"]
    assert "owner=o" in logged and "number=7" in logged


def test_a_person_needs_write_permission_not_just_an_association(tmp_path: Path) -> None:
    """ADR 0103: MEMBER and COLLABORATOR are where the question starts, not what answers it."""
    threads = [
        _thread("T1", "writer"), _thread("T2", "reader"), _thread("T3", "unknown"),
        _thread("T4", "writer"), _thread("T5", "stranger", "NONE"),
    ]
    env = _fake_gh(
        tmp_path, _pr_answer(reviewThreads={"nodes": threads}),
        permissions={"writer": "write", "reader": "read"},
    )
    result = _ok(*_LIVE, cwd=_github_repo(tmp_path), env=env)
    assert result["plan"] == {"threads": ["T1", "T4"], "untrusted": ["T2", "T3", "T5"]}
    assert {t["id"]: t["trusted"] for t in result["actionable_threads"]} == {
        "T1": True, "T2": False, "T3": False, "T4": True, "T5": False,
    }
    asked = [call for call in _gh_calls(tmp_path) if "collaborators" in " ".join(call)]
    # Once per login, and nobody is asked about someone the PR's own data already rules out.
    assert sorted(call[1].split("/")[-2] for call in asked) == ["reader", "unknown", "writer"]


def test_a_login_that_is_not_one_fails_closed(tmp_path: Path) -> None:
    threads = [_thread("T1", "not a login")]
    env = _fake_gh(tmp_path, _pr_answer(reviewThreads={"nodes": threads}))
    result = _ok(*_LIVE, cwd=_github_repo(tmp_path), env=env)
    assert result["plan"] == {"threads": [], "untrusted": ["T1"]}


def test_a_snapshot_says_so_and_never_opens_a_merge(tmp_path: Path) -> None:
    env = _user_config(tmp_path, _env(), {"pr_watcher": {"auto_merge": True}})
    result = _ok(
        "pr-state", "--snapshot", "-", cwd=tmp_path, env=env, stdin=json.dumps(_pr_answer())
    )
    assert result["source"] == "snapshot"
    assert result["settings"]["merges_here"] is False
    assert result["merge"] is None
    assert result["merge_gate"]["ready"] is True  # the gate is what it reads; the merge is not


def test_pr_state_triages_the_threads(tmp_path: Path) -> None:
    threads = [_thread("T1", "ann"), _thread("T2", "drive-by", "NONE")]
    answer = _pr_answer(reviewThreads={"nodes": threads})
    result = _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=json.dumps(answer))
    assert result["plan"] == {"threads": ["T1"], "untrusted": ["T2"]}
    assert [t["trusted"] for t in result["actionable_threads"]] == [True, False]
    assert result["actionable_threads"][0]["path"] == "a.py"
    assert result["merge_gate"]["ready"] is False
    assert "2 unresolved review thread(s)" in result["merge_gate"]["reasons"]


def test_the_plan_is_capped_at_the_operators_max_threads(tmp_path: Path) -> None:
    threads = [_thread(f"T{i}", "ann") for i in range(4)]
    answer = _pr_answer(reviewThreads={"nodes": threads})
    env = _user_config(tmp_path, _env(), {"pr_watcher": {"max_threads": 2}})
    result = _ok("pr-state", "--snapshot", "-", cwd=tmp_path, env=env, stdin=json.dumps(answer))
    assert result["plan"]["threads"] == ["T0", "T1"]
    assert len(result["actionable_threads"]) == 4
    assert result["settings"]["max_threads"] == 2


def test_a_listed_reviewer_app_reaches_the_plan(tmp_path: Path) -> None:
    threads = [_thread("T1", "codex", "NONE", "Bot"), _thread("T2", "other", "NONE", "Bot")]
    answer = json.dumps(_pr_answer(reviewThreads={"nodes": threads}))
    assert _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=answer)["plan"]["threads"] == []
    env = _user_config(tmp_path, _env(), {"pr_watcher": {"trusted_reviewers": ["codex"]}})
    result = _ok("pr-state", "--snapshot", "-", cwd=tmp_path, env=env, stdin=answer)
    assert result["plan"] == {"threads": ["T1"], "untrusted": ["T2"]}


def test_pr_state_reads_the_eval_fixture(tmp_path: Path) -> None:
    fixture = _PLUGIN / "eval" / "fixtures" / "pr-watch" / "pr42-snapshot.json"
    result = _ok("pr-state", "--snapshot", str(fixture), cwd=tmp_path)
    assert result["number"] == 42
    assert result["push"]["argv"][-1] == "HEAD:refs/heads/feat/search-index"


def test_the_merge_command_is_pinned_and_comes_only_with_the_gate_and_the_setting(
    tmp_path: Path,
) -> None:
    env = _fake_gh(tmp_path, _pr_answer())
    config = {"pr_watcher": {"auto_merge": ["O/N"], "merge_method": "squash"}}
    env = _user_config(tmp_path, env, config)
    result = _ok(*_LIVE, cwd=_github_repo(tmp_path), env=env)
    assert result["settings"]["merges_here"] is True
    assert result["merge"]["argv"] == [
        "gh", "pr", "merge", "7", "-R", "o/n", "--squash", "--delete-branch",
        "--match-head-commit", _OID,
    ]
    shut = _fake_gh(tmp_path, _pr_answer(isDraft=True))
    shut = _user_config(tmp_path, shut, {"pr_watcher": {"auto_merge": True}})
    assert _ok(*_LIVE, cwd=_github_repo(tmp_path), env=shut)["merge"] is None


def test_no_head_commit_means_no_merge_and_the_gate_says_why(tmp_path: Path) -> None:
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=""))
    env = _user_config(tmp_path, env, {"pr_watcher": {"auto_merge": True}})
    result = _ok(*_LIVE, cwd=_github_repo(tmp_path), env=env)
    assert result["merge"] is None
    assert result["merge_gate"]["ready"] is False
    assert "not a commit id" in result["merge_gate"]["reasons"][0]


def test_a_repos_own_config_cannot_turn_on_merging(tmp_path: Path) -> None:
    (tmp_path / ".agentic-forge").mkdir()
    (tmp_path / ".agentic-forge" / "config.json").write_text(
        json.dumps({"pr_watcher": {"auto_merge": True}}), encoding="utf-8"
    )
    env = _fake_gh(tmp_path, _pr_answer())
    # stderr: the settings' warning about that key
    done = _run(*_LIVE, cwd=_github_repo(tmp_path), env=env)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["settings"]["merges_here"] is False


def test_pr_state_reads_settings_and_pushes_from_its_repo_flag(tmp_path: Path) -> None:
    """A repo can switch merging off for itself, and it is --repo's config that says so, not the
    working directory's; the push runs there too."""
    checkout, head = _pr_checkout(tmp_path)
    (checkout / "a.txt").write_text("fix\n", encoding="utf-8")
    _git(checkout, "commit", "-qam", "fix: the thread")
    other = tmp_path / "other"
    (other / ".agentic-forge").mkdir(parents=True)
    (other / ".agentic-forge" / "config.json").write_text(
        json.dumps({"pr_watcher": {"auto_merge": False}}), encoding="utf-8"
    )
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=head))
    env = _user_config(tmp_path, env, {"pr_watcher": {"auto_merge": True}})
    assert _ok(*_LIVE, cwd=checkout, env=env)["settings"]["merges_here"] is True
    result = _ok(*_LIVE, "--repo", "other", cwd=tmp_path, env=env)
    assert result["settings"]["merges_here"] is False
    result = _ok(*_LIVE, "--repo", str(checkout), cwd=tmp_path, env=env)
    assert result["push"]["argv"] == [
        *_SAFE_GIT, "-C", str(checkout), "push", "origin", "HEAD:refs/heads/feat-x",
    ]
    assert "--force" not in result["push"]["shell"]
    assert " -f" not in result["push"]["shell"]


def test_a_fork_is_read_only(tmp_path: Path) -> None:
    """A fork's snapshot used to give `ready: true`, and a printed push to its branch name, which
    is a branch in OUR origin, and a merge."""
    threads = [_thread("T1", "ann")]
    answer = _pr_answer(
        isCrossRepository=True, headRefName="main", reviewThreads={"nodes": []},
    )
    result = _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=json.dumps(answer))
    assert result["cross_repo"] is True
    assert result["merge_gate"] == {"ready": False, "reasons": ["from a fork"]}
    assert result["push"] is None
    assert result["merge"] is None
    with_threads = _pr_answer(isCrossRepository=True, reviewThreads={"nodes": threads})
    result = _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=json.dumps(with_threads))
    assert result["plan"]["threads"] == []
    live = _fake_gh(tmp_path, answer, permissions={"ann": "write"})
    live = _user_config(tmp_path, live, {"pr_watcher": {"auto_merge": True}})
    result = _ok(*_LIVE, cwd=_github_repo(tmp_path), env=live)
    assert (result["merge"], result["push"]) == (None, None)


@pytest.mark.parametrize("branch", ["a..b", "a b", "a;b", "a~1", "a:b", "--force", ""])
def test_no_push_for_a_branch_that_is_not_one(tmp_path: Path, branch: str) -> None:
    answer = json.dumps(_pr_answer(headRefName=branch))
    assert _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=answer)["push"] is None


def test_no_push_for_a_pr_that_is_closed(tmp_path: Path) -> None:
    answer = json.dumps(_pr_answer(state="MERGED"))
    assert _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=answer)["push"] is None


@pytest.mark.parametrize(
    ("args", "stdin", "says"),
    [
        ([], None, "--snapshot"),
        (["--owner", "o"], None, "--snapshot"),
        (["--owner", "o", "--snapshot", "-"], "{}", "not both"),
        (["--owner", "o;x", "--name", "n", "--number", "1"], None, "invalid owner"),
        (["--owner", "o", "--name", "../n", "--number", "1"], None, "invalid repository name"),
        (["--snapshot", "-"], "[]", "must be a JSON object"),
        (["--snapshot", "-"], "{}", "no pull request"),
    ],
)
def test_pr_state_refuses(
    tmp_path: Path, args: list[str], stdin: str | None, says: str
) -> None:
    assert says in _refused("pr-state", *args, cwd=tmp_path, stdin=stdin)


def test_pr_state_reports_a_failing_gh(tmp_path: Path) -> None:
    env = _fake_gh(tmp_path, "boom", code=4)
    assert "gh exited 4" in _refused(*_LIVE, cwd=_github_repo(tmp_path), env=env)


def test_pr_state_with_no_gh_says_so(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    assert "gh is not on PATH" in _refused(*_LIVE, cwd=repo, env=_env(PATH=str(tmp_path)))


@pytest.mark.parametrize(
    ("answer", "merged"),
    [
        ({"state": "MERGED", "mergedAt": "2026-11-03T00:00:00Z"}, True),
        ({"state": "OPEN", "mergedAt": None}, False),
        ({"state": "CLOSED", "mergedAt": "2026-11-03T00:00:00Z"}, False),
    ],
)
def test_pr_merged(tmp_path: Path, answer: dict[str, object], merged: bool) -> None:
    env = _fake_gh(tmp_path, answer)
    assert _ok("pr-merged", "--repo-slug", "o/n", "--number", "7", cwd=tmp_path, env=env) == {
        "merged": merged
    }


def test_pr_merged_on_a_failing_read_is_not_a_no(tmp_path: Path) -> None:
    env = _fake_gh(tmp_path, "boom", code=1)
    _refused("pr-merged", "--repo-slug", "o/n", "--number", "7", cwd=tmp_path, env=env)


def test_argv_commands_run_nothing(tmp_path: Path) -> None:
    env = _fake_gh(tmp_path, {})
    (tmp_path / "body.md").write_text("Thanks", encoding="utf-8")
    for args, stdin in [
        (["pr-reply-argv", "--thread-id", "T1", "--body-file", "body.md"], None),
        (
            ["pr-conflict-notice", "--repo-slug", "o/n", "--number", "7", "--comments-json", "-"],
            "[]",
        ),
        (
            ["doc-pr-argv", "--repo-slug", "o/n", "--slug", "x", "--title", "T",
             "--body-file", "body.md"],
            None,
        ),
    ]:
        done = _run(*args, cwd=tmp_path, env=env, stdin=stdin)
        assert done.returncode == 0, (args, done.stderr)
    assert _gh_calls(tmp_path) == []


def test_a_reply_stays_in_its_file_and_off_the_command_line(tmp_path: Path) -> None:
    """A JSON-escaped apostrophe, taken literally by whoever copied the line, created a file in
    four shells. So there is no reviewer's text on the line to escape."""
    body = "It's $(touch pwned); `touch pwned2`\nsecond line"
    (tmp_path / "it's a body.md").write_text(body, encoding="utf-8")
    result = _ok(
        "pr-reply-argv", "--thread-id", "T_abc=", "--body-file", "it's a body.md", cwd=tmp_path
    )
    assert "threadId=T_abc=" in result["argv"]
    assert "pwned" not in result["shell"]
    assert result["argv"][-2:] == ["-F", f"body=@{tmp_path / chr(105)}t's a body.md"]
    assert shlex.split(result["shell"]) == result["argv"]
    # Run what the skill says to run: `shell`, decoded from JSON.
    env = _fake_gh(tmp_path, {})
    done = subprocess.run(
        ["bash", "-c", result["shell"]], cwd=tmp_path, env=env, capture_output=True, check=False
    )
    assert done.returncode == 0
    assert _gh_calls(tmp_path) == [result["argv"][1:]]
    assert not (tmp_path / "pwned").exists() and not (tmp_path / "pwned2").exists()


def test_a_reply_needs_a_real_file_with_something_in_it(tmp_path: Path) -> None:
    args = ("pr-reply-argv", "--thread-id", "T1", "--body-file")
    (tmp_path / "blank.md").write_text("  \n", encoding="utf-8")
    assert "empty" in _refused(*args, "blank.md", cwd=tmp_path)
    _refused(*args, "absent.md", cwd=tmp_path)
    _refused(*args, "-", cwd=tmp_path, stdin="from stdin")  # the printed line runs later
    (tmp_path / "linked.md").symlink_to("blank.md")
    assert "symlink" in _refused(*args, "linked.md", cwd=tmp_path)


def test_a_thread_id_must_be_one(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("x", encoding="utf-8")
    args = ("pr-reply-argv", "--thread-id", "a b", "--body-file", "b.md")
    assert "invalid thread id" in _refused(*args, cwd=tmp_path)


@pytest.mark.parametrize("number", ["0", "-1", "x"])
def test_a_pr_number_must_be_one(tmp_path: Path, number: str) -> None:
    args = ("pr-merged", "--repo-slug", "o/n", f"--number={number}")
    assert _run(*args, cwd=tmp_path).returncode == 2


def test_the_conflict_notice_goes_up_once(tmp_path: Path) -> None:
    args = ("pr-conflict-notice", "--repo-slug", "o/n", "--number", "7", "--comments-json", "-")
    first = _ok(*args, cwd=tmp_path, stdin='{"comments": [{"body": "hello"}]}')
    assert first["present"] is False
    notice = first["post"]["argv"][-1]
    assert first["post"]["argv"][:3] == ["gh", "pr", "comment"]
    second = _ok(*args, cwd=tmp_path, stdin=json.dumps({"comments": [{"body": notice}]}))
    assert second == {"present": True, "post": None}
    assert _ok(*args, cwd=tmp_path, stdin=json.dumps([notice]))["present"] is True


# --- a push is a fix on this PR's branch, in this PR's repo (ADR 0104) ----------------------------


def _pr_checkout(tmp_path: Path) -> tuple[Path, str]:
    """A clone of github.com/o/n on the PR's branch, at the PR's head. Pushes go to a real bare
    repository, and reads of `origin` still say GitHub. Returns it and the head commit."""
    bare = tmp_path / "pushed.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    _git(checkout, "remote", "add", "origin", "https://github.com/o/n.git")
    _git(checkout, "remote", "set-url", "--push", "origin", str(bare))
    (checkout / "a.txt").write_text("base\n", encoding="utf-8")
    _git(checkout, "add", "a.txt")
    _git(checkout, "commit", "-qm", "base")
    _git(checkout, "checkout", "-q", "-b", "feat-x")
    return checkout, _git(checkout, "rev-parse", "HEAD").strip()


def _commit_fix(checkout: Path) -> str:
    (checkout / "a.txt").write_text("fix\n", encoding="utf-8")
    _git(checkout, "commit", "-qam", "fix: the thread")
    return _git(checkout, "rev-parse", "HEAD").strip()


def test_a_commit_on_the_prs_branch_gets_a_push_that_does_push(tmp_path: Path) -> None:
    checkout, head = _pr_checkout(tmp_path)
    fixed = _commit_fix(checkout)
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=head))
    result = _ok(*_LIVE, cwd=checkout, env=env)
    assert result["no_push"] is None
    subprocess.run(["bash", "-c", result["push"]["shell"]], cwd=checkout, check=True,
                   capture_output=True)
    bare = tmp_path / "pushed.git"
    assert _git(bare, "rev-parse", "refs/heads/feat-x").strip() == fixed


def test_no_new_commit_means_no_push(tmp_path: Path) -> None:
    """`git push` would say "Everything up-to-date", and that must not read as a pushed fix."""
    checkout, head = _pr_checkout(tmp_path)
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=head))
    result = _ok(*_LIVE, cwd=checkout, env=env)
    assert result["push"] is None
    assert "nothing to push" in result["no_push"]


def test_another_branch_gets_no_push(tmp_path: Path) -> None:
    checkout, head = _pr_checkout(tmp_path)
    _commit_fix(checkout)
    _git(checkout, "checkout", "-q", "-b", "local-work")
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=head))
    result = _ok(*_LIVE, cwd=checkout, env=env)
    assert result["push"] is None
    assert "feat-x" in result["no_push"] and "local-work" in result["no_push"]


def test_a_detached_head_gets_no_push(tmp_path: Path) -> None:
    checkout, head = _pr_checkout(tmp_path)
    _commit_fix(checkout)
    _git(checkout, "checkout", "-q", "--detach")
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=head))
    assert "no branch" in _ok(*_LIVE, cwd=checkout, env=env)["no_push"]


def test_a_head_that_has_moved_on_gets_no_push(tmp_path: Path) -> None:
    """Behind or beside the PR's head: the push would be refused, or would drop commits."""
    checkout, head = _pr_checkout(tmp_path)
    unknown = _pr_answer(headRefOid=_OID)
    env = _fake_gh(tmp_path, unknown)
    assert "does not hold" in _ok(*_LIVE, cwd=checkout, env=env)["no_push"]
    ahead = _commit_fix(checkout)
    _git(checkout, "reset", "-q", "--hard", head)
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=ahead))
    assert "does not hold" in _ok(*_LIVE, cwd=checkout, env=env)["no_push"]


@pytest.mark.parametrize(
    "origin", ["https://github.com/someone/else.git", "https://gitlab.com/o/n.git", None]
)
def test_a_pr_of_another_repo_gets_no_push_and_no_plan(tmp_path: Path, origin: str | None) -> None:
    checkout, head = _pr_checkout(tmp_path)
    _commit_fix(checkout)
    _git(checkout, "remote", "remove", "origin")
    if origin:
        _git(checkout, "remote", "add", "origin", origin)
    threads = [_thread("T1", "owner", "OWNER")]
    answer = _pr_answer(headRefOid=head, reviewThreads={"nodes": threads})
    env = _fake_gh(tmp_path, answer, permissions={"owner": "admin"})
    env = _user_config(tmp_path, env, {"pr_watcher": {"auto_merge": True}})
    result = _ok(*_LIVE, cwd=checkout, env=env)
    assert result["push"] is None
    assert "o/n" in result["no_push"]
    assert result["plan"]["threads"] == []
    assert result["plan"]["reason"] == result["no_push"]
    assert result["actionable_threads"][0]["trusted"] is False
    assert "body" not in result["actionable_threads"][0]
    assert not [c for c in _gh_calls(tmp_path) if "collaborators" in " ".join(c)]


def test_merge_goes_by_slug_from_another_repos_checkout(tmp_path: Path) -> None:
    checkout, head = _pr_checkout(tmp_path)
    _git(checkout, "remote", "set-url", "origin", "https://github.com/someone/else.git")
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=_OID))
    env = _user_config(tmp_path, env, {"pr_watcher": {"auto_merge": True}})
    result = _ok(*_LIVE, cwd=checkout, env=env)
    assert result["push"] is None
    assert result["merge"]["argv"][:6] == ["gh", "pr", "merge", "7", "-R", "o/n"]


def test_the_slug_comparison_ignores_case(tmp_path: Path) -> None:
    checkout, head = _pr_checkout(tmp_path)
    _git(checkout, "remote", "set-url", "origin", "https://github.com/O/N.git")
    _commit_fix(checkout)
    env = _fake_gh(tmp_path, _pr_answer(headRefOid=head))
    assert _ok(*_LIVE, cwd=checkout, env=env)["push"] is not None


def test_strangers_cannot_fill_the_report_and_hide_a_trusted_thread(tmp_path: Path) -> None:
    """64 large threads from nobody used to fail the whole read as too large."""
    def stranger(i: int) -> dict[str, object]:
        thread = _thread(f"S{i}", "drive-by", "NONE")
        comment = dict(thread["comments"]["nodes"][0])  # type: ignore[index]
        comment["body"] = "x" * 65_536
        return {**thread, "comments": {"nodes": [comment]}}

    threads = [*(stranger(i) for i in range(64)), _thread("T1", "ann")]
    answer = json.dumps(_pr_answer(reviewThreads={"nodes": threads}))
    result = _ok("pr-state", "--snapshot", "-", cwd=tmp_path, stdin=answer)
    assert result["plan"]["threads"] == ["T1"]
    by_id = {t["id"]: t for t in result["actionable_threads"]}
    assert by_id["T1"]["body"] == "Please fix"
    assert "body" not in by_id["S0"]
    assert by_id["S0"]["author"] == "drive-by"


# --- the skill keeps run_watch's order (ADR 0104) -------------------------------------------------


def test_the_skills_order_is_run_watchs() -> None:
    """Fix, commit, push, then reply, then resolve, in both modes: a reply saying a fix landed has
    to be true, and a failed push posts nothing. The library is what decides that order."""
    order: list[str] = []
    def gh_exec(argv: list[str]) -> None:
        order.append("resolve" if "resolveReviewThread" in " ".join(argv) else "reply")

    thread = pr_watch.ReviewThread("T1", False, "ann", "fix", "a.py", 1, "MEMBER", "User")
    state = pr_watch.PrState(
        number=7, branch="f", base="main", cross_repo=False, mergeable="MERGEABLE",
        threads=[thread], checks="SUCCESS",
    )
    pr_watch.run_watch(
        state, bot="b", max_threads=5, fixer=lambda t: ("fixed", "Done."),
        gh_exec=gh_exec, push=lambda: order.append("push"),
    )
    assert order == ["push", "reply", "resolve"]

    text = (_PLUGIN / "skills" / "pr-watch" / "SKILL.md").read_text(encoding="utf-8")
    fix_mode = text[text.index("### Fix mode"):text.index("## Autonomous mode")]
    autonomous = text[text.index("## Autonomous mode"):text.index("## Safety invariants")]
    for section in (fix_mode, autonomous):
        flat = " ".join(section.split())
        assert "fix, commit, push, then reply, then resolve" in flat
        assert "post nothing for those threads, do not merge in this pass, and report it" in flat
    # And the steps themselves run in that order, not only a sentence about them.
    assert fix_mode.index("`pr-state` again") < fix_mode.index("resolveReviewThread")
    assert fix_mode.index("**The order is") < fix_mode.index("4. Then, for each fixed thread")
    assert autonomous.index("Commit it on the PR's branch") < autonomous.index("5. **Push once**")
    reply_and_resolve = autonomous.index("(`pr-reply-argv`) and **resolve**")
    assert autonomous.index("5. **Push once**") < reply_and_resolve
    assert reply_and_resolve < autonomous.index("6. **Merge gate.**")


# --- a loop can exit, and a phase can hand off (ADR 0104) -----------------------------------------


def test_approve_with_a_red_gate_escalates_at_the_cap() -> None:
    assert handoff.review_loop_decision("approve", 2, cap=3, gate_green=False) == "revise"
    assert handoff.review_loop_decision("approve", 3, cap=3, gate_green=False) == "escalate"
    assert handoff.review_loop_decision("approve", 4, cap=3, gate_green=False) == "escalate"
    assert handoff.review_loop_decision("approve", 3, cap=3, gate_green=True) == "proceed"


def test_the_loop_and_develop_say_the_same() -> None:
    loop = " ".join((_PLUGIN / "patterns" / "review-loop.md").read_text("utf-8").split())
    assert "or a gate still red after N" in loop
    develop = " ".join((_PLUGIN / "skills" / "develop" / "SKILL.md").read_text("utf-8").split())
    assert "or QA still red, at iteration 3" in develop


@pytest.mark.parametrize("pattern", ["review-loop", "doc-delivery"])
def test_a_phase_that_proceeds_marks_its_artifact_for_the_next(pattern: str) -> None:
    text = " ".join((_PLUGIN / "patterns" / f"{pattern}.md").read_text("utf-8").split())
    assert "`status` to `approved`" in text and "`handoff-load`" in text


def test_a_draft_that_proceeded_is_refused_until_marked_and_read_again(tmp_path: Path) -> None:
    path = tmp_path / "prd.md"
    path.write_text(_ARTIFACT.replace("approved", "draft"), encoding="utf-8")
    args = ("handoff-load", "--path", "prd.md", "--type", "prd")
    assert _ok(*args, cwd=tmp_path)["ready"] is False
    path.write_text(_ARTIFACT, encoding="utf-8")
    assert _ok(*args, cwd=tmp_path)["ready"] is True


# --- the small ones (ADR 0104) --------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["x\n", "x\ny"])
def test_a_slug_is_matched_whole(slug: str) -> None:
    with pytest.raises(ValueError, match="invalid feature slug"):
        doc_delivery.branch_name(slug)


def test_a_note_past_the_cap_is_skipped_unparsed(tmp_path: Path) -> None:
    _ok("vault-add-note", "--json", "-", cwd=tmp_path, stdin=_note())
    big = tmp_path / "docs" / "knowledge" / "big.md"
    big.write_text("---\ntitle: Big\n---\n" + "x" * (2 * 1024 * 1024), encoding="utf-8")
    notes = vault.load_vault(tmp_path).notes
    assert "big" not in notes and "a-note" in notes
    big.write_text("---\ntitle: Big\n---\nsmall\n", encoding="utf-8")
    assert "big" in vault.load_vault(tmp_path).notes


# --- the force-push rule knows the form this script prints ---------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin HEAD:refs/heads/main",
        "git push --force origin HEAD:heads/main",
        "git push origin +HEAD:heads/master",
        "git push origin +HEAD:refs/heads/main",
        "git push -f origin refs/heads/main",
        "git push origin +refs/heads/master",
        "git -c safe.bareRepository=explicit -C . push --force origin HEAD:refs/heads/release",
        "git push --force origin main",  # the forms it always caught
        "git push origin +main",
    ],
)
def test_a_force_push_to_a_full_ref_is_blocked(command: str) -> None:
    assert guardrails.classify_command(command).block, command


@pytest.mark.parametrize(
    "command",
    [
        "git push origin HEAD:refs/heads/main",  # not forced
        "git push --force origin HEAD:refs/heads/feat-x",  # not protected
        "git push origin +HEAD:refs/heads/mainline",
    ],
)
def test_the_same_forms_are_left_alone_otherwise(command: str) -> None:
    assert not guardrails.classify_command(command).block, command


# --- document delivery ---------------------------------------------------------------------------


def test_doc_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    result = _ok("doc-worktree", "--repo", ".", "--slug", "search", cwd=repo)
    assert result["branch"] == "docs/search"
    assert result["worktree"] == str(tmp_path / "wt-docs-search")
    assert result["exists"] is False
    assert result["add"]["argv"] == [
        *_SAFE_GIT, "-C", ".", "worktree", "add", "-b", "docs/search", "../wt-docs-search", "HEAD",
    ]
    (tmp_path / "wt-docs-search").mkdir()
    assert _ok("doc-worktree", "--slug", "search", cwd=repo)["exists"] is True


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (["--slug", "../x"], "invalid feature slug"),
        (["--slug", "x", "--base", "a b"], "invalid base"),
        (["--slug", "x", "--repo", "nope"], "no such directory"),
    ],
)
def test_doc_worktree_refuses(tmp_path: Path, args: list[str], says: str) -> None:
    assert says in _refused("doc-worktree", *args, cwd=tmp_path)


_PROCEED = ("doc-proceed", "--worktree", ".", "--phase", "plan", "--slug", "x")


def test_doc_proceed_with_no_remote_stages_and_commits(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    result = _ok(*_PROCEED, "--artifact", "docs/a.md", "--artifact", "docs/b.md", cwd=tmp_path)
    assert [s["argv"][5] for s in result["steps"]] == ["add", "commit"]
    assert result["steps"][0]["argv"][-3:] == ["--", "docs/a.md", "docs/b.md"]
    assert result["steps"][1]["argv"][-2:] == ["-m", "docs(plan): x"]
    assert result["open_pr"] is False
    assert result["note"] == "no remote: committed on docs/x, not pushed"


def test_what_doc_proceed_prints_does_commit_the_artifact(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("not this\n", encoding="utf-8")
    result = _ok(*_PROCEED, "--artifact", str(tmp_path / "docs" / "a.md"), cwd=tmp_path)
    for step in result["steps"]:
        subprocess.run(
            step["argv"], cwd=tmp_path, check=True, capture_output=True,
            env={**os.environ, **_GIT_ENV},
        )
    assert _git(tmp_path, "show", "--name-only", "--format=").split() == ["docs/a.md"]


@pytest.mark.parametrize("path", ["../out.md", "/etc/passwd", "."])
def test_doc_proceed_stages_only_inside_the_worktree(tmp_path: Path, path: str) -> None:
    _git(tmp_path, "init", "-q")
    assert "inside the worktree" in _refused(*_PROCEED, "--artifact", path, cwd=tmp_path)


def test_doc_proceed_needs_an_artifact(tmp_path: Path) -> None:
    assert _run(*_PROCEED, cwd=tmp_path).returncode == 2


def test_doc_proceed_with_a_remote_and_gh_pushes_and_opens(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    env = _fake_gh(tmp_path, {})
    result = _ok(
        "doc-proceed", "--worktree", ".", "--phase", "ux-design", "--slug", "x",
        "--artifact", "a.md", cwd=repo, env=env,
    )
    assert [s["argv"][5] for s in result["steps"]] == ["add", "commit", "push"]
    assert result["open_pr"] is True
    assert not any("--force" in s["shell"] for s in result["steps"])


def test_doc_proceed_with_a_remote_and_no_gh_pushes_and_says_so(tmp_path: Path) -> None:
    repo = _github_repo(tmp_path)
    only_git = tmp_path / "only-git"
    only_git.mkdir()
    git = shutil.which("git")
    assert git
    (only_git / "git").symlink_to(git)
    result = _ok(
        *_PROCEED, "--artifact", "a.md", cwd=repo, env=_env(PATH=str(only_git)),
    )
    assert [s["argv"][5] for s in result["steps"]] == ["add", "commit", "push"]
    assert result["open_pr"] is False
    assert result["note"] == "no gh: pushed docs/x; open its PR by hand"


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (["--worktree", "nope", "--phase", "plan", "--slug", "x"], "no such directory"),
        (["--worktree", ".", "--phase", "Bad Phase", "--slug", "x"], "invalid phase"),
    ],
)
def test_doc_proceed_refuses(tmp_path: Path, args: list[str], says: str) -> None:
    assert says in _refused("doc-proceed", *args, "--artifact", "a.md", cwd=tmp_path)


def test_doc_pr_argv_keeps_the_body_in_its_file(tmp_path: Path) -> None:
    (tmp_path / "body.md").write_text("Body $(touch pwned)", encoding="utf-8")
    result = _ok(
        "doc-pr-argv", "--repo-slug", "o/n", "--slug", "x", "--title", "Docs: x (plan)",
        "--body-file", "body.md", cwd=tmp_path,
    )
    assert result["view"]["argv"][:3] == ["gh", "pr", "list"]
    assert result["create"]["argv"][-4:] == [
        "--title", "Docs: x (plan)", "--body-file", str(tmp_path / "body.md"),
    ]
    assert "pwned" not in result["create"]["shell"]
    assert shlex.split(result["create"]["shell"]) == result["create"]["argv"]
    assert "--draft" not in result["create"]["argv"]


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (["--repo-slug", "x", "--slug", "s", "--title", "T"], "invalid repository"),
        (["--repo-slug", "o/n", "--slug", "s", "--title", " "], "--title"),
        (["--repo-slug", "o/n", "--slug", "s", "--title", "a\nb"], "--title"),
        (["--repo-slug", "o/n", "--slug", "s", "--title", "it's"], "--title"),
        (["--repo-slug", "o/n", "--slug", "s", "--title", "a$(b)"], "--title"),
        (["--repo-slug", "o/n", "--slug", "s", "--title", 'a"b'], "--title"),
        (["--repo-slug", "o/n", "--slug", "S!", "--title", "T"], "invalid feature slug"),
    ],
)
def test_doc_pr_argv_refuses(tmp_path: Path, args: list[str], says: str) -> None:
    (tmp_path / "b.md").write_text("B", encoding="utf-8")
    assert says in _refused("doc-pr-argv", *args, "--body-file", "b.md", cwd=tmp_path)


# --- the wording the coordinator's review pinned --------------------------------------------------


@pytest.mark.parametrize("skill", ["architecture", "plan", "product", "research", "ux-design"])
def test_a_doc_phase_reviews_the_file_in_its_worktree(skill: str) -> None:
    text = (_PLUGIN / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "--target <worktree>/docs/sdlc/<feature-slug>/" in text
    assert "--repo <worktree>" in text


@pytest.mark.parametrize(
    "pattern",
    ["doc-delivery", "knowledge-recall", "review-loop", "worktree-parallel", "adversarial-review",
     "multi-aspect-review", "handoff"],
)
def test_a_pattern_says_what_the_plugin_root_means(pattern: str) -> None:
    text = " ".join((_PLUGIN / "patterns" / f"{pattern}.md").read_text(encoding="utf-8").split())
    assert "is the plugin's directory" in text or "`${CLAUDE_PLUGIN_ROOT}` below is" in text


def test_no_documented_call_holds_a_regex_escape() -> None:
    for _, call in _documented_calls():
        assert "\\" not in call, call


def test_the_adversarial_pattern_explains_the_reviewers_exit_1() -> None:
    text = " ".join((_PLUGIN / "patterns" / "adversarial-review.md").read_text("utf-8").split())
    assert "**Exit 1 is not a crash:**" in text


# --- the reviewer CLI the skills now name ---------------------------------------------------------


def test_the_reviewer_cli_starts_without_pyyaml(tmp_path: Path) -> None:
    """It imported yaml at the top, so on a bare python3 it died before saying anything."""
    (tmp_path / "target.md").write_text("x\n", encoding="utf-8")
    done = subprocess.run(
        [_python3(), "-E", "-S", str(_PLUGIN / "bin" / "external_review.py"), "--target",
         "target.md", "--kind", "plan", "--command", "no-such-reviewer", "--force"],
        cwd=tmp_path, env=_env(), capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "not found on PATH" in done.stdout


# --- Tier-0: this cannot come back --------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        'python -c "from agentic_forge import vault"',
        "python3 -c 'print(1)'",
        "python3 -Ic 'print(1)'",
        "python3.12 -c x",
        "python3 -I -c x",
        "python3 -E -c x",
        "python3 -W x -c y",
        "python3 -Wx -c y",
        "python3 -X y -c z",
        "x=$(python3 -c \"y\")",
        "python3 - <<EOF",
        "python3 <<'PY'",
        "python3 <<EOF",
        "python3 < script.py",
        "python3 /dev/stdin",
        "python3 -E /dev/stdin",
        "python3 -",
        "cat x | python3",
        "python3 -m agentic_forge.vault",
        "from agentic_forge import vault",
        "from agentic_forge.handoff import load_artifact",
        "import agentic_forge",
        "__import__('agentic_forge')",
        '__import__("agentic_forge.vault")',
        "importlib.import_module('agentic_forge')",
        # A shipped script without -E: a project's settings can set PYTHONPATH.
        'python3 "${CLAUDE_PLUGIN_ROOT}/bin/af.py" vault-validate --repo .',
        'python3 "${CLAUDE_PLUGIN_ROOT}/bin/external_review.py" --target x',
        'python3 "${CLAUDE_PLUGIN_ROOT}/skills/x/scripts/y.py" --days 7',
        'python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/af.py" vault-validate',
        "python ${CLAUDE_SKILL_DIR}/scripts/x.py",
    ],
)
def test_tier0_refuses_inline_python(tmp_path: Path, line: str) -> None:
    for rel in ("skills/x/SKILL.md", "skills/x/references/r.md", "patterns/p.md", "agents/a.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Title\n\n{line}\n", encoding="utf-8")
        report = validation.validate_no_inline_python(tmp_path)
        assert [i.location for i in report.errors] == [f"{rel}:3"], (rel, line)
        path.unlink()


@pytest.mark.parametrize(
    "line",
    [
        'python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" vault-validate --repo .',
        'python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/external_review.py" --kind code',
        'python3 -E "${CLAUDE_SKILL_DIR}/scripts/x.py" -c 1',
        "python dev/validate.py",
        "python3 -m pytest",
        "`python-patterns` is a pack",
        "A script may import from `agentic_forge` through sys.path.",
        "the bounded fix loop from agentic_forge.pr_watch. Manual utility",
        "python 3.9 -- the floor",
        "`${CLAUDE_PLUGIN_ROOT}/bin/pr_watch.py` driven by the job registry",
    ],
)
def test_tier0_leaves_the_other_forms_alone(tmp_path: Path, line: str) -> None:
    path = tmp_path / "skills" / "x" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"{line}\n", encoding="utf-8")
    assert validation.validate_no_inline_python(tmp_path).errors == []


def test_tier0_is_clean_on_the_real_plugin_and_runs_in_the_gate(tmp_path: Path) -> None:
    assert validation.validate_no_inline_python(_PLUGIN).errors == []

    # The whole-plugin validator is what dev/validate.py runs: a planted line must fail that too.
    plugin = tmp_path / "plugin"
    (plugin / "patterns").mkdir(parents=True)
    (plugin / "patterns" / "p.md").write_text('python3 -c "print(1)"\n', encoding="utf-8")
    assert "patterns/p.md:1" in [i.location for i in validation.validate_plugin(plugin).errors]


def test_the_knowledge_skill_has_no_way_round_a_refusal() -> None:
    text = (_PLUGIN / "skills" / "knowledge" / "SKILL.md").read_text(encoding="utf-8")
    assert "by hand" not in text.replace("Do not write the note by hand", "")
    assert "genuinely unavailable" not in text
    assert "A refusal is the answer" in text
    assert "was NOT\nsaved" in text
