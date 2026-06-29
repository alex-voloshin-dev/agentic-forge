from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentic_forge.agent_eval import (
    ROLES,
    RoleReport,
    RunOutput,
    api_runner,
    build_grading_prompt,
    build_role_prompt,
    check_wiring,
    claude_cli_runner,
    grade_output,
    is_write_role,
    load_fixtures,
    materialize_fixtures,
    parse_grading,
    run_role,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


# --- judge transports (mocked; H2: the real runners were previously never executed) --


def test_api_runner_builds_request_and_joins_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    calls: dict = {}

    class _Block:
        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text

    class _Msg:
        content = [_Block("hello "), _Block("world"), types.SimpleNamespace(type="tool_use")]

    class _Messages:
        def create(self, **kw: object) -> _Msg:
            calls.update(kw)
            return _Msg()

    class _Client:
        messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: _Client()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    run = api_runner("claude-x", max_tokens=128)
    out = run("SYS", "PROMPT", Path("."))
    assert out == "hello world"  # only text blocks joined; the tool_use block is ignored
    assert calls["model"] == "claude-x" and calls["max_tokens"] == 128
    assert calls["system"] == "SYS"
    assert calls["messages"] == [{"role": "user", "content": "PROMPT"}]


def test_claude_cli_runner_argv_and_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    captured: dict = {}

    class _Done:
        stdout = '{"result": "VERDICT-OK", "usage": {"input_tokens": 30, "output_tokens": 12}}'

    def fake_run(cmd: list[str], **kw: object) -> _Done:
        captured["cmd"] = cmd
        captured["kw"] = kw
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = claude_cli_runner(allowed_tools="Read,Grep", model="claude-x", max_turns=7)
    out = run("SYS", "PROMPT", Path("/tmp"))
    assert out == "VERDICT-OK"  # the JSON `result` field is the reply text
    usage = out.usage  # type: ignore[attr-defined]
    assert usage == {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42}
    cmd = captured["cmd"]
    assert cmd[:6] == ["claude", "-p", "PROMPT", "--append-system-prompt", "SYS", "--output-format"]
    assert cmd[6] == "json"  # JSON output so usage is parseable
    assert "--allowedTools" in cmd and "Read,Grep" in cmd
    assert "--model" in cmd and "claude-x" in cmd
    assert "--max-turns" in cmd and "7" in cmd
    assert captured["kw"]["cwd"] == "/tmp" and captured["kw"]["timeout"] == 900


def test_claude_cli_runner_omits_optional_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    captured: dict = {}

    class _Done:
        stdout = '{"result": "x"}'

    def fake_run(cmd: list[str], **kw: object) -> _Done:
        captured["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = claude_cli_runner(allowed_tools=None, model=None, max_turns=None)
    run("S", "P", Path("."))
    cmd = captured["cmd"]
    assert "--allowedTools" not in cmd and "--model" not in cmd and "--max-turns" not in cmd


def test_claude_cli_runner_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    import time

    calls = {"n": 0}

    class _Done:
        stdout = '{"result": "ok"}'

    def flaky(cmd: list[str], **kw: object) -> _Done:
        calls["n"] += 1
        if calls["n"] < 3:
            raise subprocess.CalledProcessError(1, cmd)
        return _Done()

    monkeypatch.setattr(subprocess, "run", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert claude_cli_runner(retries=3)("S", "P", Path(".")) == "ok"
    assert calls["n"] == 3  # two failures, third succeeds


def test_claude_cli_runner_raises_after_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    import time

    def always_timeout(cmd: list[str], **kw: object) -> object:
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", always_timeout)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="claude call failed after 3 attempts"):
        claude_cli_runner(retries=2)("S", "P", Path("."))


def test_run_output_is_str_and_carries_usage() -> None:
    out = RunOutput("hi", {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5})
    assert isinstance(out, str) and out == "hi"  # behaves as the reply text everywhere
    assert out.usage == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
    assert RunOutput("plain").usage is None  # no usage reported -> None


def test_api_runner_captures_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    class _Block:
        type = "text"

        def __init__(self, text: str) -> None:
            self.text = text

    class _Msg:
        content = [_Block("answer")]
        usage = types.SimpleNamespace(input_tokens=40, output_tokens=8)

    class _Client:
        messages = types.SimpleNamespace(create=lambda **kw: _Msg())

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: _Client()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    out = api_runner("m")("S", "P", Path("."))
    assert out == "answer"
    usage = out.usage  # type: ignore[attr-defined]
    assert usage == {"input_tokens": 40, "output_tokens": 8, "total_tokens": 48}


def test_claude_cli_runner_degrades_on_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    class _Done:
        stdout = "not json at all"  # an unexpected/old CLI output must not crash the sweep

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Done())
    out = claude_cli_runner()("S", "P", Path("."))
    assert out == "not json at all" and out.usage is None  # type: ignore[attr-defined]


def test_claude_cli_runner_json_without_result_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    class _Done:
        stdout = '{"unexpected": "shape"}'  # valid JSON but no `result` field

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Done())
    out = claude_cli_runner()("S", "P", Path("."))
    assert out == '{"unexpected": "shape"}' and out.usage is None  # type: ignore[attr-defined]


def test_json_objects_returns_all_objects() -> None:
    from agentic_forge.agent_eval import json_objects

    assert json_objects('{"a": 1} prose {"b": 2}') == [{"a": 1}, {"b": 2}]  # all, outer-first
    assert json_objects("no json here") == []


def test_json_candidates_linear_on_brace_heavy_input() -> None:
    import time

    from agentic_forge.agent_eval import _json_candidates

    # the old per-'{' rescan was O(n^2) (~13s on 50k braces); the brace-stack version is linear.
    start = time.perf_counter()
    _json_candidates("{" * 20000)
    assert time.perf_counter() - start < 1.0


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
    with pytest.raises(ValueError, match="no valid JSON object"):
        parse_grading("no json here")


def test_parse_grading_brace_and_escape_in_string() -> None:
    # Braces inside a JSON string (and an escaped quote) must not break extraction.
    obj = parse_grading('{"evidence": "a \\" } { quote", "passed": true}')
    assert obj["passed"] is True
    assert "}" in obj["evidence"]


def test_parse_grading_skips_unbalanced_leading_brace() -> None:
    # A stray unbalanced '{' before the real object must be skipped, not corrupt parsing.
    obj = parse_grading('noise {oops not json\n\n{"passed": true}')
    assert obj["passed"] is True


def test_parse_grading_skips_invalid_then_takes_valid() -> None:
    # A balanced-but-invalid object is skipped (json.loads fails); the next valid one is used.
    obj = parse_grading('{not: valid json} {"passed": true}')
    assert obj["passed"] is True


def test_grade_output_retries_on_unparseable_then_succeeds() -> None:
    calls = {"n": 0}

    def flaky_grader(system: str, prompt: str, workdir: Path) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "sorry — here is prose, not json"
        return json.dumps({"assertion_results": [{"text": "a", "passed": True, "evidence": "x"}]})

    graded = grade_output(["a"], "out", "g", flaky_grader, Path("."))
    assert calls["n"] == 2
    assert graded["summary"] == {"total": 1, "passed": 1, "pass_rate": 1.0}


# --- load_fixtures -------------------------------------------------------------------


def test_load_fixtures_empty() -> None:
    assert load_fixtures(PLUGIN, []) == ""


def test_load_fixtures_reads_and_labels(tmp_path: Path) -> None:
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "f.txt").write_text("hello", encoding="utf-8")
    out = load_fixtures(tmp_path, ["eval/f.txt"])
    assert "--- FILE: f.txt ---" in out and "hello" in out
    assert "eval/f.txt" not in out  # repo-relative path must not leak into the prompt


def test_materialize_fixtures_copies_by_basename(tmp_path: Path) -> None:
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "f.txt").write_text("hello", encoding="utf-8")
    wd = tmp_path / "wd"
    wd.mkdir()
    materialize_fixtures(tmp_path, ["eval/f.txt"], wd)
    assert (wd / "f.txt").read_text(encoding="utf-8") == "hello"
    assert not (wd / "eval").exists()  # flattened to basename, no repo structure


def test_build_role_prompt_in_workdir_wording() -> None:
    p = build_role_prompt({"prompt": "do"}, "--- FILE: x ---\nbody", in_workdir=True)
    assert "working directory" in p


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


def test_is_write_role() -> None:
    assert is_write_role(PLUGIN, "software-engineer")
    assert is_write_role(PLUGIN, "qa-engineer")
    assert is_write_role(PLUGIN, "architect")
    assert not is_write_role(PLUGIN, "reviewer")
    assert not is_write_role(PLUGIN, "security-engineer")
    assert not is_write_role(PLUGIN, "grader")


def test_run_role_forces_isolation_for_write_roles() -> None:
    # software-engineer has Write/Edit → run_role isolates even when isolate=False is passed.
    report = run_role(
        "software-engineer",
        PLUGIN,
        run_role_fn=stub_role,
        run_grader_fn=make_grader(True),
        runs=1,
        isolate=False,
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


# --- gate-integrity regressions (from the deep review) -------------------------------


def test_grade_output_caps_passed_at_total() -> None:
    # A grader returning MORE results than assertions must not push passed > total (no >1.0).
    def over_grader(system: str, prompt: str, workdir: Path) -> str:
        items = [{"text": str(i), "passed": True, "evidence": "x"} for i in range(3)]
        return json.dumps({"assertion_results": items})

    graded = grade_output(["a"], "out", "g", over_grader, Path("."))
    assert graded["summary"] == {"total": 1, "passed": 1, "pass_rate": 1.0}


def test_grade_output_missing_results_count_as_failed() -> None:
    # Fewer results than assertions -> the missing ones are failures (total = assertion count).
    def under_grader(system: str, prompt: str, workdir: Path) -> str:
        return json.dumps({"assertion_results": [{"text": "a", "passed": True, "evidence": "x"}]})

    graded = grade_output(["a", "b", "c"], "out", "g", under_grader, Path("."))
    assert graded["summary"] == {"total": 3, "passed": 1, "pass_rate": 1 / 3}


def test_grade_output_raises_when_both_attempts_unparseable() -> None:
    def bad_grader(system: str, prompt: str, workdir: Path) -> str:
        return "no json at all"

    with pytest.raises(ValueError, match="no valid JSON"):
        grade_output(["a"], "out", "g", bad_grader, Path("."))


def test_run_role_rejects_nonpositive_runs() -> None:
    for bad in (0, -3):
        with pytest.raises(ValueError, match="runs must be"):
            run_role(
                "reviewer", PLUGIN, run_role_fn=stub_role, run_grader_fn=make_grader(True), runs=bad
            )


def test_check_wiring_duplicate_basenames(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    (agents / "evals").mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: x\ndescription: d\n---\nBody\n", encoding="utf-8")
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "f.py").write_text("1", encoding="utf-8")
    contract = {
        "skill_name": "x",
        "evals": [{"id": 1, "prompt": "p", "files": ["a/f.py", "b/f.py"], "assertions": ["x"]}],
        "component": {"id": "x", "type": "agent", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    }
    (agents / "evals" / "x.evals.json").write_text(json.dumps(contract), encoding="utf-8")
    assert any("duplicate fixture basenames" in p for p in check_wiring("x", tmp_path))
