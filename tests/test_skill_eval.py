from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forge import skill_eval
from agentic_forge.skill_eval import (
    SkillReport,
    build_skill_system,
    check_wiring,
    discover_skills_with_tier2,
    is_off_listing,
    is_write_skill,
    run_skill,
    skill_tools,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

TIER2_SKILLS = {
    "deep-review",
    "skill-factory",
    "engineering-standards",
    "python-patterns",
    "typescript-patterns",
    "javascript-patterns",
    "go-patterns",
    "rust-patterns",
    "jvm-patterns",
    "dotnet-patterns",
    "ruby-patterns",
    "php-patterns",
}


# --- stub runners ------------------------------------------------------------


def _runner(output: str) -> skill_eval.agent_eval.Runner:
    def run(system: str, prompt: str, workdir: Path) -> str:
        return output

    return run


def _grader(passed: bool) -> skill_eval.agent_eval.Runner:
    # 8 results; grade_output caps at the assertion count, so this fully passes/fails any case.
    one = '{"passed":true}' if passed else '{"passed":false}'
    body = '{"assertion_results":[' + ",".join([one] * 8) + "]}"

    def run(system: str, prompt: str, workdir: Path) -> str:
        return body

    return run


# --- discovery / classification ----------------------------------------------


def test_discover_skills_with_tier2() -> None:
    assert set(discover_skills_with_tier2(PLUGIN)) == TIER2_SKILLS


def test_discover_missing_skills_dir(tmp_path: Path) -> None:
    assert discover_skills_with_tier2(tmp_path) == []


def test_is_off_listing() -> None:
    assert is_off_listing(PLUGIN, "python-patterns") is True
    assert is_off_listing(PLUGIN, "engineering-standards") is True
    assert is_off_listing(PLUGIN, "deep-review") is False


def test_is_write_skill() -> None:
    assert is_write_skill(PLUGIN, "python-patterns") is True  # runs the software-engineer
    assert is_write_skill(PLUGIN, "skill-factory") is True  # has Write/Edit
    assert is_write_skill(PLUGIN, "deep-review") is True  # deep-review grants Write/Edit too


def test_is_write_skill_false_for_readonly_on_listing(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "skills/ro/SKILL.md",
        "---\nname: ro\ndescription: d\nallowed-tools: Read, Grep, Glob\n---\n# ro\n",
    )
    assert is_write_skill(tmp_path, "ro") is False


def test_skill_tools() -> None:
    pack_tools = skill_tools(PLUGIN, "python-patterns")
    # the software-engineer's tools (roles have no Task tool)
    assert "Write" in pack_tools and "Bash" in pack_tools and "Task" not in pack_tools
    assert "Task" in skill_tools(PLUGIN, "deep-review")  # the skill's own allowed-tools


# --- build_skill_system ------------------------------------------------------


def test_build_system_for_pack_layers_role_standards_pack() -> None:
    system = build_skill_system(PLUGIN, "python-patterns")
    assert "base engineering role" in system  # software-engineer body
    assert "Engineering standards" in system  # engineering-standards body
    assert "Python patterns" in system  # the pack body
    assert "ruff" in system  # pack toolchain detail present


def test_build_system_for_standards_has_role_and_standards_only() -> None:
    system = build_skill_system(PLUGIN, "engineering-standards")
    assert "base engineering role" in system and "Engineering standards" in system
    assert "Python patterns" not in system  # no stack pack layered for standards itself


def test_build_system_for_on_listing_skill_is_its_own_body() -> None:
    system = build_skill_system(PLUGIN, "deep-review")
    assert "Deep review" in system or "deep" in system.lower()
    assert "base engineering role" not in system  # not wrapped in the software-engineer


# --- run_skill (stubbed) -----------------------------------------------------


def test_run_skill_passes_with_perfect_grader(tmp_path: Path) -> None:
    rep = run_skill(
        "python-patterns",
        PLUGIN,
        run_skill_fn=_runner("done"),
        run_grader_fn=_grader(True),
        workdir=tmp_path,  # honored only for read skills; pack run is force-isolated anyway
    )
    assert isinstance(rep, SkillReport) and rep.passed
    assert rep.runs == 5  # the contract's runs
    assert "PASS" in rep.summary_line()


def test_run_skill_fails_with_failing_grader(tmp_path: Path) -> None:
    rep = run_skill(
        "deep-review",
        PLUGIN,
        run_skill_fn=_runner("did nothing useful"),
        run_grader_fn=_grader(False),
        runs=5,
        workdir=tmp_path,
    )
    assert not rep.passed
    assert "FAIL" in rep.summary_line()


def test_run_skill_rejects_nonpositive_runs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="runs must be"):
        run_skill(
            "deep-review",
            PLUGIN,
            run_skill_fn=_runner("x"),
            run_grader_fn=_grader(True),
            runs=0,
            workdir=tmp_path,
        )


# --- check_wiring ------------------------------------------------------------


def test_check_wiring_clean_on_real_skills() -> None:
    assert check_wiring("python-patterns", PLUGIN) == []
    assert check_wiring("deep-review", PLUGIN) == []


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_check_wiring_reports_missing_files(tmp_path: Path) -> None:
    problems = check_wiring("ghost", tmp_path)
    assert any("missing SKILL.md" in p for p in problems)
    assert any("missing contract" in p for p in problems)
    assert any("grader" in p for p in problems)


def test_check_wiring_reports_case_problems(tmp_path: Path) -> None:
    _write(tmp_path, "agents/grader.md", "---\nname: grader\ndescription: g\n---\n# g\n")
    _write(tmp_path, "skills/foo/SKILL.md", "---\nname: foo\ndescription: d\n---\n# foo\n")
    _write(
        tmp_path,
        "skills/foo/evals/evals.json",
        '{"skill_name":"foo","evals":[{"id":1,"prompt":"p","assertions":[]}],'
        '"component":{"id":"foo","type":"skill","purpose":"p"},'
        '"thresholds":{"tier2_quality":{"min_pass_rate":0.8,"runs":5}}}',
    )
    problems = check_wiring("foo", tmp_path)
    assert any("no assertions" in p for p in problems)


def test_check_wiring_off_listing_needs_base_role(tmp_path: Path) -> None:
    _write(tmp_path, "agents/grader.md", "---\nname: grader\ndescription: g\n---\n# g\n")
    _write(
        tmp_path,
        "skills/x-patterns/SKILL.md",
        "---\nname: x-patterns\ndescription: d\ndisable-model-invocation: true\n---\n# x\n",
    )
    _write(
        tmp_path,
        "skills/x-patterns/evals/evals.json",
        '{"skill_name":"x-patterns","evals":[{"id":1,"prompt":"p","assertions":["a"]}],'
        '"component":{"id":"x-patterns","type":"skill","purpose":"p"},'
        '"thresholds":{"tier2_quality":{"min_pass_rate":0.8,"runs":5}}}',
    )
    problems = check_wiring("x-patterns", tmp_path)
    assert any("base role" in p for p in problems)
    assert any("engineering-standards skill missing" in p for p in problems)


def test_is_off_listing_false_when_no_skill(tmp_path: Path) -> None:
    assert is_off_listing(tmp_path, "nope") is False


def test_discover_skips_noevals_and_unloadable(tmp_path: Path) -> None:
    _write(tmp_path, "skills/noevals/SKILL.md", "---\nname: noevals\ndescription: d\n---\n# x\n")
    _write(tmp_path, "skills/bad/evals/evals.json", "{ not valid json")
    _write(
        tmp_path,
        "skills/good/evals/evals.json",
        '{"skill_name":"good","evals":[{"id":1,"prompt":"p","assertions":["a"]}],'
        '"component":{"id":"good","type":"skill","purpose":"p"},'
        '"thresholds":{"tier2_quality":{"min_pass_rate":0.8,"runs":5}}}',
    )
    assert discover_skills_with_tier2(tmp_path) == ["good"]


def test_check_wiring_no_tier2_threshold(tmp_path: Path) -> None:
    _write(tmp_path, "agents/grader.md", "---\nname: grader\ndescription: g\n---\n# g\n")
    _write(tmp_path, "skills/foo/SKILL.md", "---\nname: foo\ndescription: d\n---\n# foo\n")
    _write(
        tmp_path,
        "skills/foo/evals/evals.json",
        '{"skill_name":"foo","evals":[{"id":1,"prompt":"p","assertions":["a"]}],'
        '"component":{"id":"foo","type":"skill","purpose":"p"},'
        '"thresholds":{"tier1_trigger":{"recall":0.9,"specificity":0.9}}}',
    )
    assert any("no tier2_quality" in p for p in check_wiring("foo", tmp_path))


def test_check_wiring_no_cases_and_fixture_problems(tmp_path: Path) -> None:
    _write(tmp_path, "agents/grader.md", "---\nname: grader\ndescription: g\n---\n# g\n")
    _write(tmp_path, "skills/empty/SKILL.md", "---\nname: empty\ndescription: d\n---\n# e\n")
    _write(
        tmp_path,
        "skills/empty/evals/evals.json",
        '{"skill_name":"empty","evals":[],'
        '"component":{"id":"empty","type":"skill","purpose":"p"},'
        '"thresholds":{"tier2_quality":{"min_pass_rate":0.8,"runs":5}}}',
    )
    assert any("no eval cases" in p for p in check_wiring("empty", tmp_path))

    _write(tmp_path, "sub/x.txt", "x")
    _write(tmp_path, "other/x.txt", "x")  # same basename as sub/x.txt -> collision
    _write(tmp_path, "skills/fix/SKILL.md", "---\nname: fix\ndescription: d\n---\n# f\n")
    _write(
        tmp_path,
        "skills/fix/evals/evals.json",
        '{"skill_name":"fix","evals":[{"id":1,"prompt":"p","assertions":["a"],'
        '"files":["sub/x.txt","other/x.txt","nope.txt"]}],'
        '"component":{"id":"fix","type":"skill","purpose":"p"},'
        '"thresholds":{"tier2_quality":{"min_pass_rate":0.8,"runs":5}}}',
    )
    probs = check_wiring("fix", tmp_path)
    assert any("duplicate fixture basenames" in p for p in probs)
    assert any("missing fixture" in p for p in probs)


def test_run_skill_respects_explicit_isolate(tmp_path: Path) -> None:
    rep = run_skill(
        "deep-review",
        PLUGIN,
        run_skill_fn=_runner("done"),
        run_grader_fn=_grader(True),
        runs=5,
        isolate=True,
        workdir=tmp_path,
    )
    assert rep.passed
