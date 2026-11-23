from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_forge import pre_router
from agentic_forge.validation import validate_agent, validate_skill

_REPO = Path(__file__).resolve().parents[1]


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


# --- the title-first form stays a handoff-only opt-in (ADR 0112) ---------------------------------

_STRICT = "missing or malformed YAML frontmatter (expected leading '---' block)"
_TITLE = "# Demo\n\n"


def test_a_title_first_skill_md_is_refused_with_the_strict_message(make_skill) -> None:
    skill = make_skill()
    md = skill / "SKILL.md"
    md.write_text(_TITLE + md.read_text(encoding="utf-8"), encoding="utf-8")
    report = validate_skill(skill)
    assert [i.message for i in report.errors] == [_STRICT]  # not the handoff's two-form message


def test_a_title_first_agent_is_refused_with_the_strict_message(tmp_path: Path) -> None:
    agent = tmp_path / "demo-agent.md"
    agent.write_text(_TITLE + "---\nname: demo-agent\ndescription: d\n---\nDo.\n", "utf-8")
    assert [i.message for i in validate_agent(agent).errors] == [_STRICT]


def _standalone_plugin(root: Path, skill: Path) -> Path:
    """A plugin holding only ``skill`` (a ``make_skill`` directory), moved into its skills/."""
    plugin = root / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "p", "version": "1"}', encoding="utf-8"
    )
    (plugin / "skills").mkdir()
    skill.rename(plugin / "skills" / skill.name)
    return plugin


@pytest.mark.parametrize("title", ["", _TITLE], ids=["header-first", "title-first"])
def test_dev_validate_refuses_a_title_first_skill_md(
    make_skill, tmp_path: Path, title: str
) -> None:
    """`dev/validate.py` as CI runs it, on a one-skill plugin: the same SKILL.md passes header-first
    and fails title-first, so the failure is the title and nothing else."""
    skill = make_skill()
    md = skill / "SKILL.md"
    md.write_text(title + md.read_text(encoding="utf-8"), encoding="utf-8")
    plugin = _standalone_plugin(tmp_path, skill)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, str(_REPO / "dev" / "validate.py"), str(plugin)], capture_output=True,
        text=True, cwd=tmp_path, env=env, timeout=120, check=False,
    )
    if not title:
        assert done.returncode == 0, done.stdout + done.stderr
        return
    assert done.returncode == 1, done.stdout + done.stderr
    assert f"demo/SKILL.md: {_STRICT}" in done.stdout


def test_the_pre_router_skips_a_title_first_skill(tmp_path: Path) -> None:
    sk = tmp_path / "skills" / "titled"
    (sk / "evals").mkdir(parents=True)
    (sk / "SKILL.md").write_text(_TITLE + "---\nname: titled\ndescription: x\n---\n", "utf-8")
    (sk / "evals" / "evals.json").write_text(
        json.dumps({"triggers": {"should_trigger": ["do titled"]}}), encoding="utf-8"
    )
    index = pre_router.build_index(tmp_path)
    assert index.skills == []
    (reason,) = index.skipped
    assert reason == f"titled: FrontmatterError: {_STRICT}"


def _calls_with(keyword: str | None, name: str) -> set[str]:
    """Every ``module:function`` under plugin/ and dev/ that calls ``name`` (with ``keyword``)."""
    found: set[str] = set()
    for path in sorted([*(_REPO / "plugin").rglob("*.py"), *(_REPO / "dev").rglob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                called = callee.attr if isinstance(callee, ast.Attribute) else getattr(
                    callee, "id", None
                )
                if keyword is not None and any(k.arg == keyword for k in node.keywords):
                    found.add(f"{path.relative_to(_REPO)}:{func.name}")
                elif keyword is None and called == name:
                    found.add(f"{path.relative_to(_REPO)}:{func.name}")
    return found


def test_only_the_handoff_parser_opts_into_the_title() -> None:
    """The opt-in did not leak: one call passes ``allow_title`` and one probe calls
    ``split_title``; every other frontmatter reader stays strict."""
    assert _calls_with("allow_title", "parse") == {
        "plugin/lib/agentic_forge/handoff.py:parse_artifact"
    }
    assert _calls_with(None, "split_title") == {
        "plugin/lib/agentic_forge/frontmatter.py:parse",
        "plugin/lib/agentic_forge/artifact_home.py:artifact_format",
    }
