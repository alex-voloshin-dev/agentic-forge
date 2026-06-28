from __future__ import annotations

from pathlib import Path

from agentic_forge.skill_contract import SPINE_SKILLS, recall_problems

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


def test_spine_skills_constant() -> None:
    assert SPINE_SKILLS == ("research", "product", "architecture", "plan", "develop", "code-review")


def test_live_spine_phases_reference_recall() -> None:
    assert recall_problems(PLUGIN) == []


def test_flags_missing_recall(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "research"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: research\ndescription: x\n---\n## Process\n1. do stuff\n", encoding="utf-8"
    )
    problems = recall_problems(tmp_path, ("research",))
    assert problems and "knowledge-recall step" in problems[0]


def test_missing_skill_md(tmp_path: Path) -> None:
    assert any("SKILL.md not found" in p for p in recall_problems(tmp_path, ("ghost",)))
