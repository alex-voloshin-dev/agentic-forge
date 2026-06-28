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
    assert problems and "knowledge-recall" in problems[0]


def test_bare_mention_without_link_is_flagged(tmp_path: Path) -> None:
    # the token in a comment (not the pattern link) must NOT satisfy the guard
    d = tmp_path / "skills" / "research"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: research\ndescription: x\n---\n"
        "## Process\n<!-- knowledge-recall TODO -->\n1. go\n",
        encoding="utf-8",
    )
    assert recall_problems(tmp_path, ("research",))


def test_missing_skill_md(tmp_path: Path) -> None:
    assert any("SKILL.md not found" in p for p in recall_problems(tmp_path, ("ghost",)))


def test_malformed_frontmatter_reported(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "research"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
    assert recall_problems(tmp_path, ("research",))  # FrontmatterError surfaced
