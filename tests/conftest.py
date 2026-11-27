from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from agentic_forge import guardrails, settings

VALID_EVALS = {
    "skill_name": "demo",
    "evals": [
        {
            "id": 1,
            "prompt": "Run the demo task on my project.",
            "expected_output": "The demo task completes and reports a summary.",
            "assertions": ["The output reports a summary"],
        }
    ],
    "component": {"id": "demo", "type": "skill", "purpose": "Demo skill for tests."},
    "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    "triggers": {"should_trigger": ["do the demo"], "should_not_trigger": ["unrelated"]},
}


@pytest.fixture(autouse=True)
def _isolate_user_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hermeticity: no test may read the developer's real ``~/.agentic-forge/config.json`` (the
    user-level config layer, ADR 0049). Point HOME at a fresh empty dir for every test, so
    ``settings.resolve`` sees no user-level config unless a test sets one explicitly."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    settings._printed.clear()  # a warning prints once per process, and a test is a process here


@pytest.fixture
def make_skill(tmp_path: Path):
    """Factory that writes a skill directory and returns its path."""

    def _make(
        name: str = "demo",
        *,
        frontmatter: str | None = None,
        body: str = "Do the demo task.\n",
        evals: dict | None = VALID_EVALS,
        extra_files: dict[str, str] | None = None,
    ) -> Path:
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        if frontmatter is None:
            frontmatter = f"name: {name}\ndescription: A demo skill used in tests."
        (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
        if evals is not None:
            evals_dir = skill_dir / "evals"
            evals_dir.mkdir(exist_ok=True)
            (evals_dir / "evals.json").write_text(json.dumps(evals), encoding="utf-8")
        for rel, content in (extra_files or {}).items():
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return skill_dir

    return _make


@pytest.fixture(autouse=True)
def _isolated_state_home(tmp_path_factory, monkeypatch):
    """Keep generated plugin state out of the developer's real home (ADR 0072).

    `state_root` defaults to `~/.agentic-forge`; without this every test run would write there and
    leak between tests — the same class of pollution the ADR removes from repositories."""
    monkeypatch.setenv("AGENTIC_FORGE_STATE_HOME", str(tmp_path_factory.mktemp("state-home")))


class WindowsPath:
    """The PATH entries of :func:`windows_programs`: ``shims`` holds `gh.cmd` and `git.cmd`,
    ``binaries`` holds `gh.EXE` and `git.EXE`; :meth:`use` sets the process PATH."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.shims, self.binaries = root / "win-cmd", root / "win-exe"
        self._monkeypatch = monkeypatch
        for directory, ext in ((self.shims, ".cmd"), (self.binaries, ".EXE")):
            directory.mkdir()
            for name in ("gh", "git"):
                (directory / f"{name}{ext}").write_text("")  # no execute bit: Windows has none

    def use(self, *directories: Path) -> None:
        self._monkeypatch.setenv("PATH", os.pathsep.join(str(d) for d in directories))

    def binary(self, name: str) -> str:
        return str(self.binaries / f"{name}.EXE")


@pytest.fixture
def windows_programs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WindowsPath:
    """The program lookup as on Windows (ADR 0115): `guardrails._WINDOWS` set and the usual
    `PATHEXT`, so only an `.exe`/`.com` on an absolute PATH entry may be chosen."""
    monkeypatch.setattr(guardrails, "_WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    return WindowsPath(tmp_path.resolve(), monkeypatch)


def _plant(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / name
    program.write_text(f"#!/bin/sh\ntouch '{directory / (name + '-ran')}'\n", encoding="utf-8")
    program.chmod(0o755)
    return program


@pytest.fixture
def plant_program() -> Callable[[Path, str], Path]:
    """``plant(directory, name)``: an executable ``directory/name`` that, if it is ever run, leaves
    ``directory/<name>-ran`` behind. For a repository's own `git`/`gh` a lookup must not choose."""
    return _plant

