from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentic_forge.agent_eval import (
    ROLES,
    GradingUnparseable,
    RoleReport,
    RunOutput,
    SessionTimedOut,
    SessionUndetermined,
    TurnCapHit,
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
    run_eval_cases,
    run_role,
    session_outcome,
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
    # the operator's user-level settings/CLAUDE.md must NOT reach a graded run (ADR 0077)
    assert cmd[cmd.index("--setting-sources") + 1] == "project"
    assert "--model" in cmd and "claude-x" in cmd
    assert "--max-turns" in cmd and "7" in cmd
    assert captured["kw"]["cwd"] == "/tmp" and captured["kw"]["timeout"] == 900


def test_claude_cli_runner_replace_system_swaps_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # A classifier (Tier-1 routing) must not inherit Claude Code's default agent prompt — primed
    # as an agent, the model answers in prose instead of with one skill name (ADR 0064).
    import subprocess

    captured: dict = {}

    class _Done:
        stdout = '{"result": "research"}'

    def fake_run(cmd: list[str], **kw: object) -> _Done:
        captured["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    claude_cli_runner(replace_system=True)("SYS", "P", Path("."))
    cmd = captured["cmd"]
    assert "--system-prompt" in cmd and "--append-system-prompt" not in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"

    # …while the role path (Tier-2) keeps appending, so an agent still gets the agent prompt.
    claude_cli_runner()("SYS", "P", Path("."))
    assert "--append-system-prompt" in captured["cmd"] and "--system-prompt" not in captured["cmd"]


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
    # A TRANSPORT failure (non-zero exit, no envelope to read) keeps the backoff retries and ends
    # in a plain RuntimeError carrying the decoded output tails.
    import subprocess
    import time

    def always_crash(cmd: list[str], **kw: object) -> object:
        raise subprocess.CalledProcessError(2, cmd, output=b"boom \xe2\x80\x94 bytes", stderr="err")

    monkeypatch.setattr(subprocess, "run", always_crash)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    with pytest.raises(RuntimeError, match="claude call failed after 3 attempts") as info:
        claude_cli_runner(retries=2)("S", "P", Path("."))
    assert not isinstance(info.value, SessionUndetermined)  # not a session outcome: the CLI died
    assert "boom — bytes" in str(info.value) and "err" in str(info.value)  # decoded, kept
    assert sleeps == [15, 30]  # backoff between the three attempts


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
    assert parse_grading('{"assertion_results": [{"passed": true}]}') == {
        "assertion_results": [{"passed": True}]
    }


def test_parse_grading_prose_wrapped() -> None:
    got = parse_grading('Here is the grading: {"assertion_results": []} done')
    assert got == {"assertion_results": []}


def test_parse_grading_fenced() -> None:
    assert parse_grading('```json\n{"assertion_results": []}\n```') == {"assertion_results": []}


def test_parse_grading_no_json_raises() -> None:
    with pytest.raises(GradingUnparseable, match="no valid JSON grading object"):
        parse_grading("no json here")
    with pytest.raises(GradingUnparseable):  # JSON, but not a grading: no assertion_results list
        parse_grading('{"a": 1} and {"assertion_results": "not a list"}')


def test_parse_grading_brace_and_escape_in_string() -> None:
    # Braces inside a JSON string (and an escaped quote) must not break extraction.
    obj = parse_grading(
        '{"assertion_results": [{"evidence": "a \\" } { quote", "passed": true}]}'
    )
    assert obj["assertion_results"][0]["passed"] is True
    assert "}" in obj["assertion_results"][0]["evidence"]


def test_parse_grading_skips_unbalanced_leading_brace() -> None:
    # A stray unbalanced '{' before the real object must be skipped, not corrupt parsing.
    obj = parse_grading('noise {oops not json\n\n{"assertion_results": [{"passed": true}]}')
    assert obj["assertion_results"][0]["passed"] is True


def test_parse_grading_skips_invalid_then_takes_valid() -> None:
    # A balanced-but-invalid object is skipped (json.loads fails); the next valid one is used.
    obj = parse_grading('{not: valid json} {"assertion_results": [{"passed": true}]}')
    assert obj["assertion_results"][0]["passed"] is True


def test_parse_grading_picks_the_grading_object_not_the_first_object() -> None:
    """THE bug (eval audit, C5): a grader that wrote another JSON object before its grading had
    that object picked — no assertion_results — and the case scored 0/N silently."""
    reply = (
        'Plan: {"steps": ["read the file", "check each assertion"]}\n'
        '{"assertion_results": [{"text": "a", "passed": true, "evidence": "x"}], '
        '"summary": {"total": 1, "passed": 1, "pass_rate": 1.0}}'
    )
    assert parse_grading(reply)["assertion_results"][0]["passed"] is True
    graded = grade_output(["a"], "out", "g", lambda s, p, w: reply, Path("."))
    assert graded["summary"] == {"total": 1, "passed": 1, "pass_rate": 1.0}


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


def test_grade_output_without_the_shape_is_ungraded_not_zero() -> None:
    # `{}` used to score 0/N with no complaint. A reply with no grading object — after the retry —
    # is GradingUnparseable; the run loop records the case as ungraded (see run_eval_cases tests).
    calls = {"n": 0}

    def empty_grader(system: str, prompt: str, workdir: Path) -> str:
        calls["n"] += 1
        return "{}"

    with pytest.raises(GradingUnparseable):
        grade_output(["a", "b"], "out", "g", empty_grader, Path("."))
    assert calls["n"] == 2  # the stricter retry was tried first


@pytest.mark.parametrize("spelling", ["true", "TRUE", "pass", "PASS", "passed", " Passed "])
def test_grade_output_accepts_passed_spellings(spelling: str) -> None:
    # A grader that ignores the JSON instruction and writes "PASS" used to be scored as a FAIL.
    def grader(system: str, prompt: str, workdir: Path) -> str:
        return json.dumps({"assertion_results": [{"text": "a", "passed": spelling}]})

    assert grade_output(["a"], "out", "g", grader, Path("."))["summary"]["passed"] == 1


@pytest.mark.parametrize("value", ["false", "FAIL", "no", False, None, 1, "yes"])
def test_grade_output_rejects_everything_else(value: object) -> None:
    def grader(system: str, prompt: str, workdir: Path) -> str:
        return json.dumps({"assertion_results": [{"text": "a", "passed": value}]})

    assert grade_output(["a"], "out", "g", grader, Path("."))["summary"]["passed"] == 0


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
    assert any("duplicate fixture destinations" in p for p in check_wiring("x", tmp_path))


# --- fixture layout below a `tree/` segment (audit C6d) --------------------------------------


def test_fixture_dest_is_basename_or_path_below_tree() -> None:
    from agentic_forge.evals import fixture_dest

    assert fixture_dest("eval/fixtures/reviewer/case1.diff") == "case1.diff"
    assert fixture_dest("eval/fixtures/rust-patterns/tree/src/lib.rs") == "src/lib.rs"
    assert fixture_dest("eval/fixtures/x/tree/plugin/agents/a.md") == "plugin/agents/a.md"
    # the marker is a DIRECTORY segment: a file literally named `tree` lands by basename
    assert fixture_dest("eval/fixtures/x/tree") == "tree"
    # only the first marker counts; a deeper `tree/` is part of the seeded layout
    assert fixture_dest("eval/fixtures/x/tree/src/tree/y.rs") == "src/tree/y.rs"


def test_materialize_fixtures_keeps_the_layout_below_tree(tmp_path: Path) -> None:
    src = tmp_path / "eval" / "fixtures" / "p" / "tree" / "src"
    src.mkdir(parents=True)
    (src / "lib.rs").write_text("pub fn f() {}", encoding="utf-8")
    (src.parent / "Cargo.toml").write_text("[package]", encoding="utf-8")
    wd = tmp_path / "wd"
    wd.mkdir()
    rels = ["eval/fixtures/p/tree/Cargo.toml", "eval/fixtures/p/tree/src/lib.rs"]
    materialize_fixtures(tmp_path, rels, wd)
    assert (wd / "Cargo.toml").is_file() and (wd / "src" / "lib.rs").is_file()
    assert not (wd / "eval").exists() and not (wd / "tree").exists()  # no repo path leaks
    labels = load_fixtures(tmp_path, rels)
    assert "--- FILE: src/lib.rs ---" in labels and "eval/fixtures" not in labels


# --- a session that never ran is neither a pass nor a fail (eval audit C7/C8/C13/C14) ---------

# Envelope shapes measured on Claude Code 2.1.270 with `claude -p --output-format json`.
API_ERROR = (
    '{"is_error":true,"subtype":"success","api_error_status":404,"result":"Not found: model"}'
)
CAP_HIT = (
    '{"type":"result","is_error":true,"subtype":"error_max_turns","terminal_reason":"max_turns",'
    '"num_turns":40}'
)
LIMIT_HIT = (
    '{"type":"result","subtype":"error","is_error":true,'
    '"result":"You\'ve hit your session limit · resets 4pm (America/New_York)"}'
)


def test_session_outcome_reads_each_measured_shape() -> None:
    api = session_outcome(API_ERROR)
    assert isinstance(api, SessionUndetermined) and not isinstance(api, TurnCapHit)
    assert api.subtype == "api_error_404" and "Not found" in api.text and api.marker == "!"
    cap = session_outcome(CAP_HIT)
    assert isinstance(cap, TurnCapHit) and cap.subtype == "error_max_turns"
    assert cap.num_turns == 40 and cap.text == "" and cap.marker == "C"
    assert "num_turns=40" in str(cap)
    limit = session_outcome(LIMIT_HIT)
    assert isinstance(limit, SessionUndetermined) and limit.subtype == "error"
    assert "session limit" in limit.text
    # the json format's "no assistant turn": a success envelope with zero turns
    dead = session_outcome('{"subtype":"success","is_error":false,"result":"","num_turns":0}')
    assert dead is not None and dead.subtype == "no_turns"


def test_session_outcome_is_none_for_a_reply_or_a_non_envelope() -> None:
    assert session_outcome('{"result":"VERDICT-OK","subtype":"success","num_turns":1}') is None
    assert session_outcome('{"result":"ok"}') is None  # older CLI: no subtype, no num_turns
    assert session_outcome("not json at all") is None  # a transport failure, not an outcome
    assert session_outcome("[1, 2]") is None and session_outcome("") is None


def test_undetermined_is_a_runtime_error_with_the_audit_shape() -> None:
    exc = SessionUndetermined("error", "limit", num_turns=None)
    assert isinstance(exc, RuntimeError)  # pr_watch and the old CLI paths still catch it
    assert issubclass(TurnCapHit, SessionUndetermined)
    assert issubclass(SessionTimedOut, SessionUndetermined)
    assert (exc.subtype, exc.text, exc.num_turns) == ("error", "limit", None)


@pytest.mark.parametrize(
    ("stdout", "kind", "marker"),
    [
        (CAP_HIT, TurnCapHit, "C"),
        (API_ERROR, SessionUndetermined, "!"),
        (LIMIT_HIT, SessionUndetermined, "!"),
    ],
)
def test_claude_cli_runner_never_retries_a_session_that_said_no(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stdout: str, kind: type,
    marker: str,
) -> None:
    """A dead session or a cap hit was retried 3x with 15/30/45 s backoff — a cap hit re-running
    the full session in the SAME workdir, so a write role saw its own partial files."""
    import subprocess
    import time

    calls = {"n": 0}

    def exit_1(cmd: list[str], **kw: object) -> object:
        calls["n"] += 1
        raise subprocess.CalledProcessError(1, cmd, output=stdout)

    monkeypatch.setattr(subprocess, "run", exit_1)
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("a session outcome must not sleep"))
    with pytest.raises(kind):
        claude_cli_runner(retries=3)("S", "P", Path("."))
    assert calls["n"] == 1 and capsys.readouterr().err == marker


def test_claude_cli_runner_reads_the_envelope_on_exit_0_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The usage-limit refusal's exit code is not pinned down: handle both. Exit 0 with an is_error
    # envelope used to be returned as the reply text and graded — as a fail.
    import subprocess

    class _Done:
        stdout = LIMIT_HIT

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Done())
    with pytest.raises(SessionUndetermined, match="session limit"):
        claude_cli_runner()("S", "P", Path("."))


def test_claude_cli_runner_decodes_a_bytes_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def exit_1(cmd: list[str], **kw: object) -> object:
        raise subprocess.CalledProcessError(1, cmd, output=CAP_HIT.encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", exit_1)
    with pytest.raises(TurnCapHit) as info:
        claude_cli_runner()("S", "P", Path("."))
    assert info.value.num_turns == 40


def test_claude_cli_runner_timeout_prints_T_retries_once_and_keeps_partial_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """TimeoutExpired printed nothing, was retried 3x with a fresh 900 s budget each, and the
    partial stdout survived only as a 400-char repr tail (eval audit, C7)."""
    import subprocess
    import time

    calls = {"n": 0}

    def always_timeout(cmd: list[str], **kw: object) -> object:
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd, 900, output=b"partial \xc3\xa9 transcript")

    monkeypatch.setattr(subprocess, "run", always_timeout)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    with pytest.raises(SessionTimedOut) as info:
        claude_cli_runner(retries=3)("S", "P", Path("."))
    assert calls["n"] == 2 and sleeps == [15]  # one retry, not three
    assert capsys.readouterr().err == "TT"  # one marker per timed-out attempt
    assert info.value.subtype == "timeout" and "partial é transcript" in info.value.text
    assert "2 attempt(s) of 900s" in str(info.value)


def test_claude_cli_runner_timeout_then_success_returns_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess
    import time

    calls = {"n": 0}

    class _Done:
        stdout = '{"result": "ok", "subtype": "success", "num_turns": 3}'

    def once(cmd: list[str], **kw: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd, 1)
        return _Done()

    monkeypatch.setattr(subprocess, "run", once)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert claude_cli_runner()("S", "P", Path(".")) == "ok" and calls["n"] == 2


def test_api_runner_raises_when_the_reply_was_cut_at_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `stop_reason` was never inspected: a truncated artifact was graded as the role's work (C13).
    import sys
    import types

    class _Block:
        type = "text"

        def __init__(self, text: str) -> None:
            self.text = text

    class _Msg:
        content = [_Block("a very long design that got cut")]
        stop_reason = "max_tokens"
        usage = types.SimpleNamespace(input_tokens=40, output_tokens=4096)

    class _Client:
        messages = types.SimpleNamespace(create=lambda **kw: _Msg())

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: _Client()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    with pytest.raises(SessionUndetermined) as info:
        api_runner("m", max_tokens=4096)("S", "P", Path("."))
    assert info.value.subtype == "max_tokens" and "got cut" in info.value.text


# --- Tier-2 records an undetermined case instead of aborting the role (C8/C13/C14) ------------

_TWO_CASES = [
    {"id": 1, "prompt": "do a", "assertions": ["a1", "a2"]},
    {"id": 2, "prompt": "do b", "assertions": ["b1", "b2"]},
]
_THRESH = {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}}


def _dying_component(die_on: set[tuple[int, int]], exc: Exception):
    """A component that raises `exc` on the given (run, case) sessions and passes otherwise."""
    seen: dict[int, int] = {}

    def run(system: str, prompt: str, workdir: Path) -> str:
        case = 1 if prompt.startswith("do a") else 2
        seen[case] = seen.get(case, 0) + 1
        if (seen[case], case) in die_on:
            raise exc
        return "GOOD"

    return run


def _eval(run_fn, *, runs: int = 5, grader=None):
    return run_eval_cases(
        system_body="s", grader_body="g", cases=_TWO_CASES, thresholds=_THRESH,
        plugin_dir=PLUGIN, run_fn=run_fn, grader_fn=grader or make_grader(True), runs=runs,
        isolate=False,
    )


def test_one_dead_session_is_excluded_counted_and_printed_not_fatal() -> None:
    """Before: `_run_passes` let the RuntimeError through to the CLI, which printed ERROR and
    dropped the WHOLE role — every finished session ungraded. Now the case is undetermined."""
    cap = TurnCapHit("error_max_turns", "", num_turns=40)
    bench, result, gradings = _eval(_dying_component({(1, 2)}, cap))
    ws = bench["run_summary"]["with_skill"]
    assert ws["n"] == 5 and ws["pass_rate"]["mean"] == 1.0  # the other 9 sessions still count
    assert gradings[0]["summary"]["total"] == 2  # run 1 graded only case 1's two assertions
    assert ws["sessions"]["total"] == 10 and ws["sessions"]["undetermined"] == 1
    assert ws["sessions"]["subtypes"] == {"error_max_turns": 1}
    (event,) = ws["sessions"]["events"]
    assert (event["run"], event["case"], event["kind"]) == (1, 2, "undetermined")
    assert event["subtype"] == "error_max_turns" and event["num_turns"] == 40
    assert result.passed  # 1 of 10 = 10%: not over the cap
    report = RoleReport("x", 5, bench, result)
    assert "n=5; 1/10 sessions unmeasured: 1 undetermined [error_max_turns x1]" in (
        report.summary_line()
    )
    assert report.evidence_lines() == [
        "    unmeasured: run 1 case 2 undetermined (error_max_turns, num_turns=40)"
    ]


def test_too_many_dead_sessions_fail_the_role_with_the_reason() -> None:
    dead = SessionUndetermined("api_error_404", "Not found: model")
    bench, result, _ = _eval(_dying_component({(1, 1), (2, 2)}, dead))
    ws = bench["run_summary"]["with_skill"]
    assert ws["pass_rate"]["mean"] == 1.0  # the rate over the rest is fine…
    assert not result.passed  # …but 2 of 10 > 10%: the run failed, not the component
    assert any(
        "2 of 10 sessions unmeasured (> 10%): 2 undetermined [api_error_404 x2]" in r
        for r in result.reasons
    )
    assert "FAIL" in RoleReport("x", 5, bench, result).summary_line()


def test_a_run_whose_every_session_died_is_dropped_not_scored_zero() -> None:
    timeout = SessionTimedOut("timeout", "2 attempt(s) of 900s")
    bench, result, gradings = _eval(_dying_component({(1, 1), (1, 2)}, timeout))
    ws = bench["run_summary"]["with_skill"]
    assert len(gradings) == 4 and ws["n"] == 4  # run 1 has nothing to summarize: n drops
    assert ws["pass_rate"]["mean"] == 1.0  # not dragged to 0.8 by a fabricated 0.0
    assert any("only 4 run(s); need >= 5" in r for r in result.reasons)
    assert any("timeout x2" in r for r in result.reasons)


def test_an_unparseable_grading_is_ungraded_not_zero() -> None:
    graded_once = {"n": 0}

    def flaky_grader(system: str, prompt: str, workdir: Path) -> str:
        graded_once["n"] += 1
        if graded_once["n"] <= 2:  # the first case's grading AND its stricter retry: no shape
            return '{"plan": "look at the output"}'
        return make_grader(True)(system, prompt, workdir)

    bench, result, _ = _eval(lambda s, p, w: "GOOD", grader=flaky_grader)
    ws = bench["run_summary"]["with_skill"]
    assert ws["sessions"]["ungraded"] == 1 and ws["sessions"]["undetermined"] == 0
    assert ws["sessions"]["subtypes"] == {}  # subtypes are the component's, not the grader's
    assert ws["pass_rate"]["mean"] == 1.0 and result.passed  # 1 of 10: reported, not fatal
    line = RoleReport("x", 5, bench, result).summary_line()
    assert "1/10 sessions unmeasured: 1 ungraded" in line
    (event,) = ws["sessions"]["events"]
    assert event["kind"] == "ungraded" and "no valid JSON grading object" in event["text"]


def test_baseline_pass_records_its_own_sessions() -> None:
    bench, _, _ = run_eval_cases(
        system_body="s", grader_body="g", cases=_TWO_CASES, thresholds=_THRESH,
        plugin_dir=PLUGIN, run_fn=lambda s, p, w: "GOOD", grader_fn=make_grader(True), runs=5,
        isolate=False, baseline_system_body="",
    )
    rs = bench["run_summary"]
    assert rs["with_skill"]["sessions"]["total"] == 10
    assert rs["without_skill"]["sessions"]["total"] == 10


def test_agent_eval_stays_python_39_compatible() -> None:
    """`pr_watch` imports `agent_eval` on a hook-reachable path that may run under a bare
    `python3` (observed 3.9, ADR 0050): no `match`, no `zip(strict=)`, no runtime PEP 604 unions,
    no `datetime.UTC`. The grammar check parses with the 3.9 feature set; the rest is grepped."""
    import ast

    src = (PLUGIN / "lib" / "agentic_forge" / "agent_eval.py").read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 9))
    assert "from __future__ import annotations" in src
    assert "strict=" not in src and "datetime.UTC" not in src
