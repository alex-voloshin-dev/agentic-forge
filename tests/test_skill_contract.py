from __future__ import annotations

from pathlib import Path

from agentic_forge.skill_contract import (
    SKILL_HANDOFF,
    handoff_contract_problems,
    required_fields,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


def _make_skill(plugin: Path, name: str, body: str) -> None:
    d = plugin / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: x\n---\n{body}\n", encoding="utf-8"
    )


# --- live plugin --------------------------------------------------------------


def test_live_plugin_contracts_clean() -> None:
    assert handoff_contract_problems(PLUGIN) == []


def test_mapping_skills_exist_and_types_known() -> None:
    from agentic_forge import handoff

    for skill, artifact_type in SKILL_HANDOFF.items():
        assert (PLUGIN / "skills" / skill / "SKILL.md").is_file(), skill
        assert artifact_type in handoff.SCHEMAS, artifact_type


def test_required_fields_excludes_type() -> None:
    fields = required_fields("prd")
    assert "type" not in fields
    assert "feature" in fields and "goals" in fields and "acceptance" in fields


# --- synthetic skills (the matcher's behaviour) -------------------------------


def test_flags_missing_required_fields(tmp_path: Path) -> None:
    _make_skill(tmp_path, "s", "Produce prd.md (frontmatter `goals`, `acceptance`).")
    problems = handoff_contract_problems(tmp_path, {"s": "prd"})
    assert problems and "status" in problems[0] and "feature" in problems[0]


def test_clean_when_all_documented(tmp_path: Path) -> None:
    _make_skill(
        tmp_path, "s", "frontmatter `type`, `feature`, `status`, `goals`, `acceptance`"
    )
    assert handoff_contract_problems(tmp_path, {"s": "prd"}) == []


def test_accepts_comma_list_and_bracket_forms(tmp_path: Path) -> None:
    # plan requires feature, status, tasks — all inside one backtick span, tasks as tasks[]
    _make_skill(tmp_path, "s", "frontmatter `type, feature, status, tasks[]`")
    assert handoff_contract_problems(tmp_path, {"s": "plan"}) == []


def test_accepts_colon_form(tmp_path: Path) -> None:
    _make_skill(
        tmp_path, "s", "`type`, `feature`, `status`; then goals: ... and acceptance: ..."
    )
    assert handoff_contract_problems(tmp_path, {"s": "prd"}) == []


def test_prose_mention_is_not_enough(tmp_path: Path) -> None:
    # plain prose naming the fields (no backticks / no `field:`) does not satisfy the contract
    _make_skill(tmp_path, "s", "Write a prd for the feature with a status, goals and acceptance.")
    assert handoff_contract_problems(tmp_path, {"s": "prd"})


def test_missing_skill_md(tmp_path: Path) -> None:
    assert any("SKILL.md not found" in p for p in handoff_contract_problems(tmp_path, {"x": "prd"}))


def test_unknown_handoff_type(tmp_path: Path) -> None:
    _make_skill(tmp_path, "s", "body")
    problems = handoff_contract_problems(tmp_path, {"s": "nope"})
    assert any("unknown handoff type" in p for p in problems)


def test_malformed_frontmatter_reported(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "s"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("no frontmatter at all", encoding="utf-8")
    assert handoff_contract_problems(tmp_path, {"s": "prd"})  # FrontmatterError surfaced
