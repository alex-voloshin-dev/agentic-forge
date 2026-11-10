"""The harness says what it measured (ADR 0098): the session variables a skill body may use are
a contract the harness pins; every run prints its provenance; a Tier-2 FAIL keeps one failing
case's own words."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "lib"))
sys.path.insert(0, str(_REPO / "dev"))

import _eval_cli  # noqa: E402

PLUGIN = _REPO / "plugin"
_VAR = re.compile(r"\$\{([A-Z_]+)\}")


def _body_vars(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return set(_VAR.findall(body))


def test_every_session_variable_a_body_uses_is_pinned_or_declared_inherited() -> None:
    """Ten skill bodies invoked scripts as `${CLAUDE_PLUGIN_ROOT}/...` and nothing set it, so
    Tier-2 graded the installed plugin (ADR 0097). This holds every `${VAR}` in a SKILL.md or
    agent body to the harness's contract, so the next variable cannot fall into the same hole.
    The maintainer skills (`.claude/skills`, ADR 0105) run under the same harness, so they too."""
    used: dict[str, set[str]] = {}
    bodies = [
        *PLUGIN.glob("skills/*/SKILL.md"),
        *PLUGIN.glob("agents/*.md"),
        *(_REPO / ".claude" / "skills").glob("*/SKILL.md"),
    ]
    assert any(".claude" in md.parts for md in bodies)  # the maintainer root is walked
    for md in bodies:
        for var in _body_vars(md):
            used.setdefault(var, set()).add(md.relative_to(_REPO).as_posix())
    allowed = _eval_cli.SESSION_VARS_PINNED | _eval_cli.SESSION_VARS_INHERITED
    stray = {v: sorted(where) for v, where in used.items() if v not in allowed}
    assert not stray, f"body variables the harness neither pins nor declares inherited: {stray}"
    assert "CLAUDE_PLUGIN_ROOT" in used  # the contract is exercised, not vacuous


def test_session_env_pins_every_declared_variable(tmp_path: Path) -> None:
    env = _eval_cli.session_env(tmp_path, skill_dir=tmp_path / "skills" / "plan")
    assert set(env) == set(_eval_cli.SESSION_VARS_PINNED)  # the two sets cannot drift
    assert env["CLAUDE_PLUGIN_ROOT"] == str(tmp_path.resolve())
    assert env["CLAUDE_SKILL_DIR"] == str((tmp_path / "skills" / "plan").resolve())
    assert _eval_cli.session_env(tmp_path)["CLAUDE_SKILL_DIR"] == str(tmp_path.resolve())


def test_build_runners_pins_the_skill_dir_too(monkeypatch, tmp_path: Path) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(
        _eval_cli.agent_eval, "claude_cli_runner",
        lambda **kw: seen.append(kw) or (lambda s, p, w: "out"),
    )
    _eval_cli.build_runners(
        "claude", allowed_tools="Bash", model="m", plugin_dir=tmp_path,
        skill_dir=tmp_path / "skills" / "x",
    )
    assert all(kw["env"]["CLAUDE_SKILL_DIR"].endswith("/skills/x") for kw in seen)


def test_provenance_names_the_tree_and_its_version(tmp_path: Path) -> None:
    """The seventh "measured something else" (ADR 0097) would have been visible on its first run
    had the run said which plugin it ran. Now it does — and a tree with no git or manifest still
    yields a line rather than an exception."""
    prov = _eval_cli.provenance(PLUGIN, "claude-opus-4-8")
    assert prov["plugin_root"] == str(PLUGIN.resolve()) and prov["model"] == "claude-opus-4-8"
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", prov["plugin_version"])  # the CalVer manifest
    assert prov["git"] != "?" and prov["python"].count(".") == 2
    line = _eval_cli.provenance_line(prov)
    assert line.startswith("measuring: plugin=") and f"version={prov['plugin_version']}" in line
    bare = _eval_cli.provenance(tmp_path, "m")  # no manifest, no git: best-effort, never raises
    assert bare["plugin_version"] == "?" and bare["git"] == "?"
    assert "skill_roots=none" in _eval_cli.provenance_line(bare)


def _committed_repo(path: Path) -> Path:
    """A git repo at ``path`` with one committed file, so its status is clean."""
    path.mkdir(parents=True)
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    git += ["-C", str(path)]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
        subprocess.run([*git, *args], check=True, capture_output=True)
    return path


def test_provenance_names_the_skill_roots_and_checks_each_in_its_own_repo(tmp_path: Path) -> None:
    """The maintainer skills are part of what a run measures (ADR 0105): named on the line, and
    each judged by its OWN repository — an edit in one marks the run `+dirty`."""
    plugin = _committed_repo(tmp_path / "plugin")
    root = _committed_repo(tmp_path / "other-repo")
    prov = _eval_cli.provenance(plugin, "m", [root])
    assert prov["skill_roots"] == str(root.resolve())
    assert prov["git"] != "?" and "+" not in prov["git"]  # both clean
    assert f"skill_roots={root.resolve()} " in _eval_cli.provenance_line(prov)
    (root / "a.txt").write_text("edited\n", encoding="utf-8")
    assert _eval_cli.provenance(plugin, "m", [root])["git"].endswith("+dirty")


@pytest.fixture
def _no_enclosing_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """"Not a repository" must not depend on where pytest puts tmp_path: stop git's search there."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


@pytest.mark.usefixtures("_no_enclosing_repo")
def test_provenance_never_reads_an_external_root_as_clean(tmp_path: Path) -> None:
    """A --skill-root outside any git repo: the old combined `status -- <plugin> <roots>` failed
    as a whole, `_git` turned that into "", and the run read as clean."""
    plugin = _committed_repo(tmp_path / "plugin")
    external = tmp_path / "external"
    external.mkdir()
    sha = _eval_cli.provenance(plugin, "m", [external])["git"]
    assert sha.endswith("+status-unknown") and "+dirty" not in sha


@pytest.mark.usefixtures("_no_enclosing_repo")
def test_provenance_keeps_a_dirty_plugin_dirty_beside_an_external_root(tmp_path: Path) -> None:
    plugin = _committed_repo(tmp_path / "plugin")
    (plugin / "a.txt").write_text("edited\n", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    sha = _eval_cli.provenance(plugin, "m", [external])["git"]
    assert "+dirty" in sha and "+status-unknown" in sha


@pytest.mark.usefixtures("_no_enclosing_repo")
def test_git_dirty_reports_a_failed_check_as_unknown(tmp_path: Path, monkeypatch) -> None:
    assert _eval_cli._git_dirty(tmp_path) is None  # not a repository
    assert _eval_cli._git_dirty(_committed_repo(tmp_path / "r")) is False

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("no git")

    monkeypatch.setattr(_eval_cli.subprocess, "run", boom)
    assert _eval_cli._git_dirty(tmp_path / "r") is None
