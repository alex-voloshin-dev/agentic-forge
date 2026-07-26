from __future__ import annotations

import json
from pathlib import Path

import pytest

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
