from __future__ import annotations

from agentic_forge.validation import validate_skill


def test_anchor_link_resolves(make_skill) -> None:
    # A link with a #anchor / ?query must not be flagged when the target file exists.
    skill = make_skill(
        body="See [g](references/g.md#section).\n",
        extra_files={"references/g.md": "# G\n"},
    )
    report = validate_skill(skill)
    assert report.ok, report.render()


def test_missing_eval_fixture_reported(make_skill) -> None:
    case = {"id": 1, "prompt": "p", "files": ["eval/fixtures/nope.txt"], "assertions": ["x"]}
    evals = {
        "skill_name": "demo",
        "evals": [case],
        "component": {"id": "demo", "type": "skill", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    }
    report = validate_skill(make_skill(evals=evals))
    assert any("missing fixture file" in i.message for i in report.errors)


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


def test_empty_or_whitespace_description_errors(make_skill) -> None:
    # an empty/whitespace description must fail — guards the `not desc or not strip()` check (a
    # `desc is None` mutant would pass it, and a blank description defeats router triggering).
    for fm in ('name: demo\ndescription: ""', 'name: demo\ndescription: "   "'):
        report = validate_skill(make_skill(frontmatter=fm))
        assert any("description is required" in i.message for i in report.errors), fm


def test_name_dir_mismatch(make_skill) -> None:
    skill = make_skill(name="demo", frontmatter="name: other\ndescription: d")
    report = validate_skill(skill)
    assert any("must match parent directory" in i.message for i in report.errors)


def test_missing_evals(make_skill) -> None:
    skill = make_skill(evals=None)
    report = validate_skill(skill)
    assert any(
        "evals/evals.json" in i.location and "eval contract" in i.message
        for i in report.errors
    )


def test_body_too_long(make_skill) -> None:
    skill = make_skill(body="line\n" * 600)
    report = validate_skill(skill)
    assert any("body is" in i.message for i in report.errors)


def test_body_length_cap_boundary(make_skill) -> None:
    # exactly 500 lines passes; 501 fails — guards the `>` vs `>=` boundary on the most-cited rule
    # (a `>=` mutant would wrongly reject a legitimate 500-line body).
    ok = validate_skill(make_skill(body="\n".join("x" for _ in range(500))))
    assert not any("body is" in i.message for i in ok.errors)
    over = validate_skill(make_skill(body="\n".join("x" for _ in range(501))))
    assert any("body is 501 lines" in i.message for i in over.errors)


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


def test_bad_dir_name(make_skill) -> None:
    skill = make_skill(name="Bad", frontmatter="description: d")
    report = validate_skill(skill)
    assert any("directory name" in i.message for i in report.errors)


def test_description_too_long(make_skill) -> None:
    long_desc = "x" * 1100
    skill = make_skill(frontmatter=f"name: demo\ndescription: {long_desc}")
    report = validate_skill(skill)
    assert any("description exceeds" in i.message for i in report.errors)


def test_compatibility_too_long(make_skill) -> None:
    skill = make_skill(
        frontmatter="name: demo\ndescription: d\ncompatibility: " + "y" * 600
    )
    report = validate_skill(skill)
    assert any("compatibility exceeds" in i.message for i in report.errors)


def test_metadata_not_mapping(make_skill) -> None:
    skill = make_skill(frontmatter="name: demo\ndescription: d\nmetadata: notamap")
    report = validate_skill(skill)
    assert any("metadata must be a mapping" in i.message for i in report.errors)


def test_metadata_nonstring_value_warns(make_skill) -> None:
    skill = make_skill(frontmatter="name: demo\ndescription: d\nmetadata:\n  version: 1")
    report = validate_skill(skill)
    assert any("should be a string" in i.message for i in report.warnings)


def test_skill_wrong_component_type(make_skill) -> None:
    bad = {
        "skill_name": "demo",
        "evals": [{"id": 1, "prompt": "do", "assertions": ["ok"]}],
        "component": {"id": "demo", "type": "agent", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    }
    skill = make_skill(evals=bad)
    report = validate_skill(skill)
    assert any("component.type must be 'skill'" in i.message for i in report.errors)
