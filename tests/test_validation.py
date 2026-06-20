from __future__ import annotations

from agentic_forge.validation import validate_skill


def test_valid_skill_passes(make_skill) -> None:
    skill = make_skill()
    report = validate_skill(skill)
    assert report.ok, report.render()


def test_missing_skill_md(make_skill, tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    report = validate_skill(empty)
    assert not report.ok
    assert any("missing SKILL.md" in i.message for i in report.errors)


def test_missing_description(make_skill) -> None:
    skill = make_skill(frontmatter="name: demo")
    report = validate_skill(skill)
    assert any("description" in i.message for i in report.errors)


def test_name_dir_mismatch(make_skill) -> None:
    skill = make_skill(name="demo", frontmatter="name: other\ndescription: d")
    report = validate_skill(skill)
    assert any("must match parent directory" in i.message for i in report.errors)


def test_missing_evals(make_skill) -> None:
    skill = make_skill(evals=None)
    report = validate_skill(skill)
    assert any("evals/evals.json" in i.message for i in report.errors)


def test_body_too_long(make_skill) -> None:
    skill = make_skill(body="line\n" * 600)
    report = validate_skill(skill)
    assert any("body is" in i.message for i in report.errors)


def test_unknown_field_warns(make_skill) -> None:
    skill = make_skill(frontmatter="name: demo\ndescription: d\nbogus: 1")
    report = validate_skill(skill)
    assert any("unknown frontmatter field" in i.message for i in report.warnings)
    assert report.ok  # warnings do not fail the gate


def test_broken_reference(make_skill) -> None:
    skill = make_skill(body="See [guide](references/missing.md).\n")
    report = validate_skill(skill)
    assert any("referenced file does not exist" in i.message for i in report.errors)


def test_valid_reference(make_skill) -> None:
    skill = make_skill(
        body="See [guide](references/guide.md).\n",
        extra_files={"references/guide.md": "# Guide\n"},
    )
    report = validate_skill(skill)
    assert report.ok, report.render()


def test_invalid_evals_content(make_skill) -> None:
    skill = make_skill(evals={"component": {"id": "x"}})  # missing type/purpose + thresholds
    report = validate_skill(skill)
    assert any("evals/evals.json" in i.location for i in report.errors)
