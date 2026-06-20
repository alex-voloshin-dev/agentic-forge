from __future__ import annotations

import json
from pathlib import Path

import pytest

VALID_EVALS = {
    "component": {"id": "demo", "type": "skill", "purpose": "Demo skill for tests."},
    "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    "triggers": {"should_trigger": ["do the demo"], "should_not_trigger": ["unrelated"]},
}


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
