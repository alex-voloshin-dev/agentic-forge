from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentic_forge.agent_eval import (
    ROLES,
    RoleReport,
    build_grading_prompt,
    build_role_prompt,
    check_wiring,
    grade_output,
    load_fixtures,
    parse_grading,
    run_role,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


# --- stub seams ----------------------------------------------------------------------


def _assertions_in(prompt: str) -> list[str]:
    return re.findall(r"^\d+\.\s+(.*)$", prompt, re.MULTILINE)


def make_grader(passed: bool):
    def grader(system: str, prompt: str, workdir: Path) -> str:
        items = _assertions_in(prompt)
        results = [{"text": a, "passed": passed, "evidence": "stub"} for a in items]
        return "```json\n" + json.dumps({"assertion_results": results}) + "\n```"

    return grader


def stub_role(system: str, prompt: str, workdir: Path) -> str:
    return "STUB ROLE OUTPUT for: " + prompt[:40]


# --- prompt builders -----------------------------------------------------------------


def test_build_role_prompt_with_and_without_fixture() -> None:
    case = {"prompt": "Do the thing."}
    assert build_role_prompt(case, "") == "Do the thing."
    withfix = build_role_prompt(case, "--- FILE: x ---\nbody")
    assert "Context files:" in withfix and "body" in withfix


def test_build_grading_prompt_numbers_assertions() -> None:
    prompt = build_grading_prompt(["first", "second"], "the output")
    assert "1. first" in prompt and "2. second" in prompt
    assert "the output" in prompt
    assert "JSON object" in prompt


# --- parse_grading -------------------------------------------------------------------


def test_parse_grading_plain() -> None:
    assert parse_grading('{"a": 1}') == {"a": 1}


def test_parse_grading_prose_wrapped() -> None:
    assert parse_grading('Here is the grading: {"a": 1} done') == {"a": 1}


def test_parse_grading_fenced() -> None:
    assert parse_grading('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_grading_no_json_raises() -> None:
    with pytest.raises(ValueError, match="no JSON object"):
        parse_grading("no json here")


# --- load_fixtures -------------------------------------------------------------------


def test_load_fixtures_empty() -> None:
    assert load_fixtures(PLUGIN, []) == ""


def test_load_fixtures_reads_and_labels(tmp_path: Path) -> None:
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "f.txt").write_text("hello", encoding="utf-8")
    out = load_fixtures(tmp_path, ["eval/f.txt"])
    assert "--- FILE: eval/f.txt ---" in out and "hello" in out


# --- grade_output --------------------------------------------------------------------


def test_grade_output_recomputes_summary() -> None:
    graded = grade_output(["a", "b"], "out", "grader-body", make_grader(True), Path("."))
    assert graded["summary"] == {"total": 2, "passed": 2, "pass_rate": 1.0}


def test_grade_output_strict_bool_no_string_inflation() -> None:
    # A string "false" must NOT count as passed — only a real boolean True does.
    def stringy_grader(system: str, prompt: str, workdir: Path) -> str:
        return json.dumps(
            {
                "assertion_results": [
                    {"text": "a", "passed": "false", "evidence": "x"},
                    {"text": "b", "passed": True, "evidence": "y"},
                ]
            }
        )

    graded = grade_output(["a", "b"], "out", "g", stringy_grader, Path("."))
    assert graded["summary"] == {"total": 2, "passed": 1, "pass_rate": 0.5}


def test_grade_output_missing_results_key() -> None:
    def empty_grader(system: str, prompt: str, workdir: Path) -> str:
        return "{}"

    graded = grade_output(["a", "b"], "out", "g", empty_grader, Path("."))
    assert graded["summary"] == {"total": 2, "passed": 0, "pass_rate": 0.0}


# --- check_wiring --------------------------------------------------------------------


def test_check_wiring_real_roles_ready() -> None:
    for role in ROLES:
        assert check_wiring(role, PLUGIN) == [], role


def test_check_wiring_missing_files(tmp_path: Path) -> None:
    assert any("missing contract" in p for p in check_wiring("ghost", tmp_path))


def _make_tmp_role(
    tmp_path: Path, *, files: list[str], assertions: list[str]
) -> Path:
    agents = tmp_path / "agents"
    (agents / "evals").mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: x\ndescription: d\n---\nBody\n", encoding="utf-8")
    contract = {
        "skill_name": "x",
        "evals": [{"id": 1, "prompt": "p", "files": files, "assertions": assertions}],
        "component": {"id": "x", "type": "agent", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    }
    (agents / "evals" / "x.evals.json").write_text(json.dumps(contract), encoding="utf-8")
    return tmp_path


def test_check_wiring_missing_fixture(tmp_path: Path) -> None:
    _make_tmp_role(tmp_path, files=["eval/fixtures/nope.txt"], assertions=["a"])
    problems = check_wiring("x", tmp_path)
    assert any("missing fixture" in p for p in problems)


def test_check_wiring_no_assertions(tmp_path: Path) -> None:
    _make_tmp_role(tmp_path, files=[], assertions=[])
    problems = check_wiring("x", tmp_path)
    assert any("no assertions" in p for p in problems)


def test_check_wiring_no_cases(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    (agents / "evals").mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: x\ndescription: d\n---\nBody\n", encoding="utf-8")
    contract = {
        "skill_name": "x",
        "evals": [],
        "component": {"id": "x", "type": "agent", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    }
    (agents / "evals" / "x.evals.json").write_text(json.dumps(contract), encoding="utf-8")
    assert any("no eval cases" in p for p in check_wiring("x", tmp_path))


# --- run_role (integration against real contracts/fixtures) --------------------------


def test_run_role_all_pass_gate_passes() -> None:
    # Default runs (5, from the contract) so the gate's n>=5 requirement is met.
    report = run_role(
        "reviewer",
        PLUGIN,
        run_role_fn=stub_role,
        run_grader_fn=make_grader(True),
    )
    assert isinstance(report, RoleReport)
    assert report.runs == 5
    assert report.passed
    assert "reviewer: PASS" in report.summary_line()


def test_run_role_all_fail_gate_fails() -> None:
    report = run_role(
        "grader",
        PLUGIN,
        run_role_fn=stub_role,
        run_grader_fn=make_grader(False),
    )
    assert not report.passed
    assert "FAIL" in report.summary_line()


def test_run_role_too_few_runs_fails_gate() -> None:
    # Fewer runs than the contract requires (5) must fail the gate even if every run passes.
    report = run_role(
        "reviewer",
        PLUGIN,
        run_role_fn=stub_role,
        run_grader_fn=make_grader(True),
        runs=2,
    )
    assert report.runs == 2
    assert not report.passed
    assert any("run" in r for r in report.gate.reasons)


def test_run_role_isolate_uses_fresh_workdir() -> None:
    # Exercises the per-case temp-workdir isolation path (mkdtemp/rmtree) end to end.
    report = run_role(
        "reviewer",
        PLUGIN,
        run_role_fn=stub_role,
        run_grader_fn=make_grader(True),
        runs=1,
        isolate=True,
    )
    assert report.runs == 1
    assert report.gradings[0]["summary"]["pass_rate"] == 1.0


def test_run_role_uses_contract_runs_by_default() -> None:
    report = run_role(
        "architect",
        PLUGIN,
        run_role_fn=stub_role,
        run_grader_fn=make_grader(True),
    )
    assert report.runs == 5  # from the contract's tier2_quality.runs
