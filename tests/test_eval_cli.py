"""The harness says what it measured (ADR 0098): the session variables a skill body may use are
a contract the harness pins; every run prints its provenance; a Tier-2 FAIL keeps one failing
case's own words."""

from __future__ import annotations

import re
import sys
from pathlib import Path

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
    agent body to the harness's contract, so the next variable cannot fall into the same hole."""
    used: dict[str, set[str]] = {}
    for md in [*PLUGIN.glob("skills/*/SKILL.md"), *PLUGIN.glob("agents/*.md")]:
        for var in _body_vars(md):
            used.setdefault(var, set()).add(md.relative_to(PLUGIN).as_posix())
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
