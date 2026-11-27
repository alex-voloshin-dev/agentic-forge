"""The agent-eval harness applies a role's `omitClaudeMd` (ADR 0113, amended).

Covers the frontmatter read, the `--omit-claude-md` / `--claude-md` flags of `run_agent_evals`, the
workspace CLAUDE.md placement, the per-session `CLAUDE_CODE_DISABLE_CLAUDE_MDS` switch, the prompt-
token and cost capture an A/B reads its saving from, and the benchmark/history record. The `claude`
CLI is always stubbed: no model is called.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
_FIXTURE = _PLUGIN / "eval" / "fixtures" / "claude-md" / "typical-project.md"
sys.path.insert(0, str(_REPO / "dev"))

import _eval_cli  # noqa: E402
import run_agent_evals  # noqa: E402
from agentic_forge import agent_eval, benchmark, gate  # noqa: E402
from agentic_forge.agent_eval import RunOutput  # noqa: E402

_GRADING = json.dumps(
    {
        "assertion_results": [{"text": "a", "passed": True, "evidence": "e"}],
        "summary": {"total": 1, "passed": 1, "pass_rate": 1.0},
    }
)


def _plugin_with_role(tmp_path: Path, frontmatter: str) -> Path:
    agents = tmp_path / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "lens.md").write_text(
        f"---\nname: lens\ndescription: d\n{frontmatter}---\n\nbody\n", encoding="utf-8"
    )
    return tmp_path


# --- the frontmatter read ------------------------------------------------------


def test_omits_claude_md_reads_the_shipped_roles() -> None:
    assert agent_eval.omits_claude_md(_PLUGIN, "grader") is True  # ADR 0113 set it
    assert agent_eval.omits_claude_md(_PLUGIN, "reviewer") is False
    assert agent_eval.omits_claude_md(_PLUGIN, "security-engineer") is False


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("omitClaudeMd: true\n", True),
        ("omitClaudeMd: false\n", False),
        ("", False),  # absent
        ('omitClaudeMd: "true"\n', False),  # a string is not the boolean the agent schema takes
        ("omitClaudeMd: yes\n", False),  # YAML 1.1 reads it as true; Claude Code need not
        ("omitClaudeMd: on\n", False),
        ("omitClaudeMd: True\n", False),
    ],
)
def test_omits_claude_md_takes_only_a_yaml_true(tmp_path: Path, line: str, expected: bool) -> None:
    assert agent_eval.omits_claude_md(_plugin_with_role(tmp_path, line), "lens") is expected


def test_omits_claude_md_reads_the_frontmatter_not_the_body(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "lens.md").write_text(
        "---\nname: lens\ndescription: d\n---\n\nomitClaudeMd: true\n", encoding="utf-8"
    )
    assert agent_eval.omits_claude_md(tmp_path, "lens") is False


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("omitClaudeMd: true\n", True),
        ("omitClaudeMd: false\n", True),
        ("omitClaudeMd: yes\n", False),
        ("omitClaudeMd: on\n", False),
        ("", True),
    ],
)
def test_tier0_holds_omit_claude_md_to_the_literal(tmp_path: Path, line: str, ok: bool) -> None:
    from agentic_forge import validation

    agent = tmp_path / "agents" / "grader.md"
    agent.parent.mkdir(parents=True)
    text = (_PLUGIN / "agents" / "grader.md").read_text(encoding="utf-8")
    agent.write_text(text.replace("omitClaudeMd: true\n", line), encoding="utf-8")
    errors = [str(e) for e in validation.validate_agent(agent).errors]
    literal = [e for e in errors if "omitClaudeMd" in e]
    assert (literal == []) is ok


def test_resolve_mode_follows_the_role_or_forces_it(tmp_path: Path) -> None:
    plugin = _plugin_with_role(tmp_path, "omitClaudeMd: true\n")
    assert agent_eval.resolve_omit_claude_md("role", plugin, "lens") is True
    assert agent_eval.resolve_omit_claude_md("off", plugin, "lens") is False
    assert agent_eval.resolve_omit_claude_md("on", _PLUGIN, "reviewer") is True
    with pytest.raises(ValueError, match="omit-claude-md mode"):
        agent_eval.resolve_omit_claude_md("maybe", plugin, "lens")


def test_claude_md_env_sets_the_switch_both_ways() -> None:
    assert agent_eval.claude_md_env(True) == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
    assert agent_eval.claude_md_env(False) == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "0"}


# --- where Claude Code will not load a CLAUDE.md --------------------------------


# A fixed root, not tmp_path: the test must hold when pytest's own temp dir sits in a scratchpad.
_ROOT = Path("/srv/af-test")


def test_claude_md_unloadable_names_a_scratchpad_and_artifact_work() -> None:
    measured = _ROOT / "claude-1000" / "-home-u-proj" / "0a1b-sess" / "scratchpad" / "ws"
    assert "scratchpad" in (agent_eval.claude_md_unloadable(measured) or "")
    plain = _ROOT / "claude" / "p" / "s" / "scratchpad"
    assert agent_eval.claude_md_unloadable(plain) is not None
    assert ".artifact-work" in (agent_eval.claude_md_unloadable(_ROOT / ".artifact-work") or "")
    assert agent_eval.claude_md_unloadable(_ROOT / "af-eval-x") is None
    # a folder merely named scratchpad, not laid out like a session's, is fine
    assert agent_eval.claude_md_unloadable(_ROOT / "notes" / "scratchpad") is None


def test_claude_md_unloadable_follows_a_link(tmp_path: Path) -> None:
    real = tmp_path / "claude-1" / "p" / "s" / "scratchpad"
    real.mkdir(parents=True)
    link = tmp_path / "tmpdir"
    link.symlink_to(real)
    assert agent_eval.claude_md_unloadable(link) is not None  # the CLI judges the target


# --- the workspace CLAUDE.md ---------------------------------------------------


def test_place_claude_md_writes_and_refuses_to_overwrite(tmp_path: Path) -> None:
    agent_eval.place_claude_md(tmp_path, "rules")
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "rules"
    with pytest.raises(ValueError, match="already provide CLAUDE.md"):
        agent_eval.place_claude_md(tmp_path, "other")


def test_run_role_puts_claude_md_in_a_fresh_workspace_for_a_read_role(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def role_fn(system: str, prompt: str, workdir: Path) -> str:
        seen.setdefault("workdirs", []).append(workdir)
        seen.setdefault("claude_md", []).append((workdir / "CLAUDE.md").read_text(encoding="utf-8"))
        seen.setdefault("listing", []).append(sorted(p.name for p in workdir.iterdir()))
        seen["prompt"] = prompt
        return "VERDICT: changes"

    def grader_fn(system: str, prompt: str, workdir: Path) -> str:
        seen["grader_workdir"] = workdir
        return _GRADING

    report = agent_eval.run_role(
        "reviewer",
        _PLUGIN,
        run_role_fn=role_fn,
        run_grader_fn=grader_fn,
        runs=1,
        workdir=tmp_path / "never-used",
        claude_md="# project rules\n",
    )
    assert report.runs == 1
    assert seen["claude_md"] == ["# project rules\n"] * 3  # every case's session would load it
    # each case's fixture materialized beside it: isolation was forced for a read role
    assert seen["listing"] == [
        ["CLAUDE.md", "case1.diff"],
        ["CLAUDE.md", "case2.diff"],
        ["CLAUDE.md", "case3-tech-design.md"],
    ]
    assert "in your working directory" in seen["prompt"]
    assert len(set(seen["workdirs"])) == 3  # a fresh workspace per case
    for work in seen["workdirs"]:
        assert not work.is_relative_to(_PLUGIN)  # never the repo
        assert not work.exists()  # removed after the case
    assert seen["grader_workdir"] == seen["workdirs"][-1]  # the judge reads the same workspace
    assert not (_PLUGIN / "CLAUDE.md").exists()
    assert not (tmp_path / "never-used").exists()


def test_run_role_without_claude_md_keeps_a_read_role_in_place() -> None:
    workdirs: list[Path] = []

    def role_fn(system: str, prompt: str, workdir: Path) -> str:
        workdirs.append(workdir)
        return "VERDICT: approve"

    agent_eval.run_role(
        "reviewer",
        _PLUGIN,
        run_role_fn=role_fn,
        run_grader_fn=lambda *a: _GRADING,
        runs=1,
    )
    assert set(workdirs) == {_PLUGIN}  # unchanged: the CLI finds the repo's CLAUDE.md upward


def test_run_eval_cases_refuses_claude_md_without_isolation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs isolate"):
        agent_eval.run_eval_cases(
            system_body="s",
            grader_body="g",
            cases=[{"prompt": "p", "assertions": ["a"]}],
            thresholds={},
            plugin_dir=tmp_path,
            run_fn=lambda *a: "x",
            grader_fn=lambda *a: _GRADING,
            runs=1,
            isolate=False,
            claude_md="rules",
        )


def test_a_fixture_named_claude_md_is_an_error_not_an_overwrite(tmp_path: Path) -> None:
    fixture = tmp_path / "eval" / "fixtures" / "x" / "CLAUDE.md"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("the case's own", encoding="utf-8")
    with pytest.raises(ValueError, match="already provide CLAUDE.md"):
        agent_eval.run_eval_cases(
            system_body="s",
            grader_body="g",
            cases=[{"prompt": "p", "files": ["eval/fixtures/x/CLAUDE.md"], "assertions": ["a"]}],
            thresholds={},
            plugin_dir=tmp_path,
            run_fn=lambda *a: "x",
            grader_fn=lambda *a: _GRADING,
            runs=1,
            isolate=True,
            claude_md="rules",
        )


# --- the session environment ---------------------------------------------------


class _Done:
    returncode = 0
    stdout = json.dumps({"result": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}})
    stderr = ""


def test_cli_runner_overrides_an_inherited_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kw: Any) -> _Done:
        captured["env"] = kw["env"]
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_CLAUDE_MDS", "1")  # the operator's shell exports it
    agent_eval.claude_cli_runner(env=agent_eval.claude_md_env(False))("S", "P", Path("."))
    assert captured["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "0"  # the "off" arm still loads
    agent_eval.claude_cli_runner(env=agent_eval.claude_md_env(True))("S", "P", Path("."))
    assert captured["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"


def test_build_runners_sets_the_switch_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    envs: list[dict[str, str] | None] = []

    def fake_cli(**kw: Any) -> str:
        envs.append(kw["env"])
        return "runner"

    monkeypatch.setattr(_eval_cli.agent_eval, "claude_cli_runner", fake_cli)
    _eval_cli.build_runners(
        "claude",
        allowed_tools="Read",
        model="m",
        plugin_dir=_PLUGIN,
        omit_claude_md=False,
        grader_omit_claude_md=True,
    )
    component, judge = envs
    assert component is not None and judge is not None
    assert component["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "0"
    assert judge["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert component["CLAUDE_PLUGIN_ROOT"] == judge["CLAUDE_PLUGIN_ROOT"]  # pins kept (ADR 0097)
    envs.clear()
    _eval_cli.build_runners("claude", allowed_tools="Read", model="m", plugin_dir=_PLUGIN)
    # the skill runner asks nothing: both sessions are pinned to "load", as they always loaded,
    # so a `1` exported in the operator's shell cannot strip CLAUDE.md from a skill eval
    assert [(e or {}).get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") for e in envs] == ["0", "0"]
    envs.clear()
    _eval_cli.build_runners("claude", allowed_tools="Read", model="m", omit_claude_md=True)
    assert envs[0] == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"} and envs[1] is None


# --- token and cost accounting -------------------------------------------------

# The `--output-format json` envelope of a two-turn session on Claude Code 2.1.331 (a local fake API
# answering 10 input / 300 cache-write / 1000 cache-read / 7 output tokens per turn): usage is the
# session's sum, and input_tokens leaves the cached prompt out.
_ENVELOPE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 2,
    "result": "done",
    "total_cost_usd": 0.00376,
    "usage": {
        "input_tokens": 20,
        "cache_creation_input_tokens": 600,
        "cache_read_input_tokens": 2000,
        "output_tokens": 14,
        "server_tool_use": {"web_search_requests": 0},
    },
}


def test_parse_cli_json_keeps_cached_input_and_cost() -> None:
    out = agent_eval._parse_cli_json(json.dumps(_ENVELOPE))
    assert out == "done"
    assert out.usage == {
        "input_tokens": 20,
        "output_tokens": 14,
        "total_tokens": 34,  # unchanged meaning: what max_overhead_tokens has always gated
        "cache_creation_input_tokens": 600,
        "cache_read_input_tokens": 2000,
        "prompt_tokens": 2620,
    }
    assert out.cost_usd == pytest.approx(0.00376)


def test_parse_cli_json_without_cache_fields_keeps_the_old_shape() -> None:
    out = agent_eval._parse_cli_json(
        json.dumps({"result": "r", "usage": {"input_tokens": 2, "output_tokens": 3}})
    )
    assert out.usage == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
    assert out.cost_usd is None
    assert agent_eval._prompt_tokens(out) == 2  # falls back to input_tokens
    assert (
        agent_eval._parse_cli_json(json.dumps({"result": "r", "total_cost_usd": 0.5})).usage is None
    )
    assert (
        agent_eval._parse_cli_json(json.dumps({"result": "r", "total_cost_usd": True})).cost_usd
        is None
    )


def test_api_runner_keeps_cached_input(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Block:
        type = "text"
        text = "answer"

    class _Msg:
        content = [_Block()]
        stop_reason = "end_turn"
        usage = types.SimpleNamespace(
            input_tokens=5,
            output_tokens=2,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=40,
        )

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: types.SimpleNamespace(  # type: ignore[attr-defined]
        messages=types.SimpleNamespace(create=lambda **kw: _Msg())
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    out = agent_eval.api_runner("m")("S", "P", Path("."))
    assert out.usage["prompt_tokens"] == 45  # type: ignore[attr-defined]
    assert out.usage["cache_creation_input_tokens"] == 0  # type: ignore[attr-defined]


def test_run_sums_prompt_tokens_and_cost_of_the_role_only(tmp_path: Path) -> None:
    usage = {"input_tokens": 20, "output_tokens": 14, "total_tokens": 34, "prompt_tokens": 2620}

    def role_fn(system: str, prompt: str, workdir: Path) -> str:
        return RunOutput("work", dict(usage), 0.01)

    def grader_fn(system: str, prompt: str, workdir: Path) -> str:
        return RunOutput(
            _GRADING, {"input_tokens": 9999, "output_tokens": 1, "total_tokens": 10000}, 9.0
        )

    bench, _result, _ = agent_eval.run_eval_cases(
        system_body="s",
        grader_body="g",
        cases=[{"prompt": "p1", "assertions": ["a"]}, {"prompt": "p2", "assertions": ["a"]}],
        thresholds={},
        plugin_dir=tmp_path,
        run_fn=role_fn,
        grader_fn=grader_fn,
        runs=2,
        isolate=True,
    )
    ws = bench["run_summary"]["with_skill"]
    assert ws["tokens"] == 68.0  # two cases per run
    assert ws["prompt_tokens"] == 5240.0  # the judge's 9999 never counts
    assert ws["cost_usd"] == pytest.approx(0.02)
    assert ws["answered_sessions"] == 2.0


def test_role_usage_counts_even_when_the_judge_fails_to_grade(tmp_path: Path) -> None:
    usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2, "prompt_tokens": 1000}
    replies = iter([_GRADING, "no json", "still no json"])  # case 2's grading fails, retry too

    def role_fn(system: str, prompt: str, workdir: Path) -> str:
        return RunOutput("work", dict(usage), 0.5)

    bench, _result, _ = agent_eval.run_eval_cases(
        system_body="s",
        grader_body="g",
        cases=[{"prompt": "p1", "assertions": ["a"]}, {"prompt": "p2", "assertions": ["a"]}],
        thresholds={},
        plugin_dir=tmp_path,
        run_fn=role_fn,
        grader_fn=lambda *a: next(replies),
        runs=1,
        isolate=True,
    )
    ws = bench["run_summary"]["with_skill"]
    assert ws["sessions"]["ungraded"] == 1
    assert ws["prompt_tokens"] == 2000.0 and ws["cost_usd"] == 1.0  # both sessions were spent
    assert ws["tokens"] == 2.0  # unchanged meaning: graded cases only


def test_usage_survives_a_run_whose_every_case_went_ungraded(tmp_path: Path) -> None:
    usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2, "prompt_tokens": 700}

    def role_fn(system: str, prompt: str, workdir: Path) -> str:
        return RunOutput("work", dict(usage), 0.25)

    bench, _result, _ = agent_eval.run_eval_cases(
        system_body="s",
        grader_body="g",
        cases=[{"prompt": "p1", "assertions": ["a"]}, {"prompt": "p2", "assertions": ["a"]}],
        thresholds={},
        plugin_dir=tmp_path,
        run_fn=role_fn,
        grader_fn=lambda *a: "never json",  # every grading fails, retries included
        runs=1,
        isolate=True,
    )
    ws = bench["run_summary"]["with_skill"]
    assert ws["n"] == 0 and ws["sessions"]["ungraded"] == 2  # no run to score...
    assert ws["prompt_tokens"] == 1400.0 and ws["cost_usd"] == 0.5  # ...but the spend is kept
    assert ws["answered_sessions"] == 2.0
    assert "tokens" not in ws  # graded cases only, as before


def test_answered_sessions_leave_out_the_undetermined(tmp_path: Path) -> None:
    calls = iter(
        [
            agent_eval.TurnCapHit("error_max_turns"),
            RunOutput(
                "w", {"input_tokens": 3, "output_tokens": 0, "total_tokens": 3, "prompt_tokens": 30}
            ),
        ]
    )

    def role_fn(system: str, prompt: str, workdir: Path) -> str:
        nxt = next(calls)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    bench, _result, _ = agent_eval.run_eval_cases(
        system_body="s",
        grader_body="g",
        cases=[{"prompt": "p1", "assertions": ["a"]}, {"prompt": "p2", "assertions": ["a"]}],
        thresholds={},
        plugin_dir=tmp_path,
        run_fn=role_fn,
        grader_fn=lambda *a: _GRADING,
        runs=1,
        isolate=True,
    )
    ws = bench["run_summary"]["with_skill"]
    assert ws["sessions"]["total"] == 2 and ws["answered_sessions"] == 1.0


def test_summarize_reports_no_fake_zero_and_covers_the_baseline() -> None:
    grading = [{"summary": {"pass_rate": 1.0}}]
    bare = benchmark.summarize(grading, with_skill_timing=[{"duration_ms": 1.0}])
    assert "prompt_tokens" not in bare["run_summary"]["with_skill"]
    assert "cost_usd" not in bare["run_summary"]["with_skill"]
    both = benchmark.summarize(
        grading,
        grading,
        with_skill_sessions={"spend": [{"answered": 2, "prompt_tokens": 100}]},
        without_skill_sessions={"spend": [{"answered": 1, "prompt_tokens": 60, "cost_usd": 0.5}]},
    )
    assert both["run_summary"]["with_skill"]["prompt_tokens"] == 100.0
    assert "cost_usd" not in both["run_summary"]["with_skill"]  # never reported: no fake 0.0
    assert both["run_summary"]["without_skill"]["prompt_tokens"] == 60.0
    assert both["run_summary"]["without_skill"]["cost_usd"] == 0.5
    assert both["run_summary"]["without_skill"]["answered_sessions"] == 1.0


def test_summary_line_prints_prompt_tokens_and_cost_only_when_measured() -> None:
    ws: dict[str, Any] = {"pass_rate": {"mean": 1.0, "stddev": 0.0}, "n": 5}
    plain = gate.format_tier2_summary(
        "r", passed=True, benchmark={"run_summary": {"with_skill": ws}}, reasons=[]
    )
    assert plain == "r: PASS (mean=1.000, stddev=0.000, lower_bound=1.000, n=5)"
    ws.update(prompt_tokens=52400.4, cost_usd=0.123456)
    line = gate.format_tier2_summary(
        "r", passed=True, benchmark={"run_summary": {"with_skill": ws}}, reasons=[]
    )
    assert line == (
        "r: PASS (mean=1.000, stddev=0.000, lower_bound=1.000, n=5; "
        "prompt_tokens/run=52400, cost/run=$0.1235)"
    )


# --- the record ----------------------------------------------------------------


def _bench(**fields: Any) -> dict[str, Any]:
    return {
        "run_summary": {"with_skill": {"pass_rate": {"mean": 0.9, "stddev": 0.0}, "n": 5}},
        **fields,
    }


def test_make_record_keeps_the_claude_md_setup() -> None:
    rec = benchmark.make_record(
        "reviewer",
        "m",
        _bench(
            omit_claude_md="on",
            omit_claude_md_mode="on",
            grader_omit_claude_md="on",
            claude_md="typical-project.md@sha256:abc",
        ),
    )
    assert rec["omit_claude_md"] == "on" and rec["grader_omit_claude_md"] == "on"
    assert rec["claude_md"] == "typical-project.md@sha256:abc"
    assert "omit_claude_md_mode" not in rec  # what was asked; the setup is what ran
    assert "omit_claude_md" not in benchmark.make_record("reviewer", "m", _bench())  # skill runs
    usage = _bench(runner="claude", claude_version="2.1.331 (Claude Code)")
    usage["run_summary"]["with_skill"].update(prompt_tokens=5240.0, cost_usd=0.02)
    rec = benchmark.make_record("reviewer", "m", usage)
    assert rec["runner"] == "claude" and rec["claude_version"] == "2.1.331 (Claude Code)"
    assert rec["prompt_tokens"] == 5240.0 and rec["cost_usd"] == 0.02


def test_ab_counterpart_pairs_the_other_arm_on_the_same_cli() -> None:
    base = {"component": "reviewer", "model": "m", "grader_model": "j", "runner": "claude"}
    base |= {"grader_omit_claude_md": "on", "claude_md": "f@1", "claude_version": "2.1.331"}
    base |= {"fingerprint": "fp1"}
    off = {**base, "omit_claude_md": "off"}
    other_cli = {**off, "claude_version": "2.1.400"}
    other_file = {**off, "claude_md": "f@2"}
    on_setup = benchmark.run_setup({**base, "omit_claude_md": "on"})
    pair = benchmark.ab_counterpart
    kw: dict[str, Any] = {"grader_model": "j", "claude_version": "2.1.331", "fingerprint": "fp1"}
    assert pair([off, other_cli, other_file], "reviewer", "m", setup=on_setup, **kw) is off
    assert pair([other_cli], "reviewer", "m", setup=on_setup, **kw) is None  # another CLI
    assert pair([off], "reviewer", "m", setup=on_setup, **{**kw, "grader_model": "x"}) is None
    # other inputs (a role, contract or fixture edited between the arms): never a pair
    assert pair([off], "reviewer", "m", setup=on_setup, **{**kw, "fingerprint": "fp2"}) is None
    assert pair([off], "reviewer", "m", setup=on_setup, **{**kw, "fingerprint": None}) is None
    on = {**base, "omit_claude_md": "on"}
    assert pair([on], "reviewer", "m", setup=benchmark.run_setup(off), **kw) is on


def test_prior_record_compares_only_a_like_setup() -> None:
    legacy = {"component": "reviewer", "model": "m", "mean": 0.9}
    off_arm = {**legacy, "omit_claude_md": "off", "grader_omit_claude_md": "on", "claude_md": "f@1"}
    on_arm = {**off_arm, "omit_claude_md": "on"}
    history = [legacy, off_arm, on_arm]
    setup = benchmark.run_setup
    assert benchmark.prior_record(history, "reviewer", "m", setup=setup(off_arm)) is off_arm
    assert benchmark.prior_record(history, "reviewer", "m", setup=setup(on_arm)) is on_arm
    # a legacy record is what a run with no fields is: both loaded CLAUDE.md, no file, no runner
    assert setup(legacy) == {
        "omit_claude_md": "off",
        "grader_omit_claude_md": "off",
        "claude_md": None,
        "runner": None,
    }
    assert benchmark.prior_record(history, "reviewer", "m", setup=setup({})) is legacy
    default_now = {**setup(legacy), "grader_omit_claude_md": "on", "runner": "claude"}
    assert benchmark.prior_record(history, "reviewer", "m", setup=default_now) is None
    assert benchmark.prior_record(history, "reviewer", "m") is on_arm  # no filter: the latest
    # the runner is part of the setup: an api record is not a claude baseline
    api = {**legacy, "runner": "api"}
    assert benchmark.prior_record([api], "reviewer", "m", setup=setup({"runner": "claude"})) is None


class _Report:
    def __init__(self, mean: float, **fields: Any) -> None:
        self.benchmark = {
            "run_summary": {"with_skill": {"pass_rate": {"mean": mean, "stddev": 0.0}, "n": 5}},
            **fields,
        }
        self.thresholds = {"tier2_quality": {"max_regression": 0.05}}
        self.passed = True


def test_version_check_does_not_compare_across_a_changed_judge(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    benchmark.save_history(history, [{"component": "reviewer", "model": "m", "mean": 0.95, "n": 5}])
    now = {"omit_claude_md": "off", "grader_omit_claude_md": "on"}
    # the legacy record's judge loaded CLAUDE.md, this one did not: another instrument, no verdict
    assert (
        _eval_cli.version_check(
            _Report(0.5, **now), component="reviewer", model="m", history_path=history, record=True
        )
        is None
    )
    saved = benchmark.load_history(history)
    assert saved[-1]["grader_omit_claude_md"] == "on"  # recorded: the new baseline
    regressed = _eval_cli.version_check(
        _Report(0.2, **now), component="reviewer", model="m", history_path=history, record=False
    )
    assert regressed is not None and not regressed.passed  # like for like is compared again


# --- the CLI -------------------------------------------------------------------


class _FakeRoleReport:
    def __init__(self, prompt_tokens: float | None = None, passed: bool = True) -> None:
        self.passed = passed
        self.runs = 5
        ws: dict[str, Any] = {"pass_rate": {"mean": 1.0, "stddev": 0.0}, "n": 5}
        ws["sessions"] = {"total": 15}  # three role sessions per run
        if prompt_tokens is not None:
            ws["prompt_tokens"] = prompt_tokens
            ws["answered_sessions"] = 3.0
        self.benchmark: dict[str, Any] = {"run_summary": {"with_skill": ws}}
        self.thresholds: dict[str, Any] = {}
        self.gate = types.SimpleNamespace(reasons=[])

    def summary_line(self) -> str:
        return "fake summary"

    def evidence_lines(self) -> list[str]:
        return []


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """`run_agent_evals.main` with the runners and the role run stubbed; collects what they got.

    The temp dir and `claude --version` are fixed, so nothing depends on the machine's TMPDIR or
    CLI; `hist` keeps every history and A/B file under tmp_path, never in the repository."""
    seen: dict[str, Any] = {"build": {}, "run_role": {}, "reports": {}, "prompt_tokens": None}
    seen["hist"] = ["--benchmark-history", str(tmp_path / "history.json")]
    seen["ab"] = tmp_path / "claude-md-ab.json"
    seen["passed"] = True
    # what each arm's probe session answers: by default, what a working switch makes it answer
    seen["probe"] = {"off": "# Ledgerline - project rules", "on": "NONE"}
    seen["probe_calls"] = []

    def fake_probe(*, model: str, plugin_dir: Path, omit_claude_md: bool) -> agent_eval.Runner:
        arm = "on" if omit_claude_md else "off"

        def run(system: str, prompt: str, workdir: Path) -> str:
            seen["probe_calls"].append((arm, prompt, (workdir / "CLAUDE.md").is_file(), system))
            answer = seen["probe"][arm]
            if isinstance(answer, Exception):
                raise answer
            tokens = 3000 if arm == "off" else 900
            usage = {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}
            return RunOutput(answer, {**usage, "prompt_tokens": tokens})

        return run

    def fake_build(
        runner: str, role: str, plugin_dir: Path, model: str, **kw: Any
    ) -> tuple[object, object]:
        seen["build"][role] = kw
        return object(), object()

    def fake_run_role(role: str, plugin_dir: Path, **kw: Any) -> _FakeRoleReport:
        seen["run_role"][role] = kw
        report = _FakeRoleReport(seen["prompt_tokens"], seen["passed"])
        seen["reports"][role] = report
        return report

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_agent_evals, "_temp_root", lambda: Path("/srv/af-test/tmp"))
    monkeypatch.setattr(
        run_agent_evals._eval_cli, "claude_version", lambda: "2.1.331 (Claude Code)"
    )
    monkeypatch.setattr(run_agent_evals, "_build_runners", fake_build)
    monkeypatch.setattr(run_agent_evals, "_build_probe", fake_probe)
    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", fake_run_role)
    monkeypatch.setattr(
        run_agent_evals.settings, "resolve", lambda *a, **k: types.SimpleNamespace(models={})
    )
    return seen


def test_cli_default_follows_each_frontmatter(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        run_agent_evals.main(["x", "--runner", "claude", "--role", "reviewer", "--role", "grader"])
        == 0
    )
    assert cli["build"]["reviewer"]["omit_claude_md"] is False
    assert cli["build"]["grader"]["omit_claude_md"] is True  # the grader under test omits it
    assert {kw["grader_omit_claude_md"] for kw in cli["build"].values()} == {True}  # the judge
    assert cli["run_role"]["reviewer"]["claude_md"] is None
    assert cli["reports"]["reviewer"].benchmark["omit_claude_md"] == "off"
    assert cli["reports"]["reviewer"].benchmark["omit_claude_md_mode"] == "role"
    assert cli["reports"]["reviewer"].benchmark["grader_omit_claude_md"] == "on"
    assert "claude_md" not in cli["reports"]["reviewer"].benchmark
    assert cli["reports"]["reviewer"].benchmark["runner"] == "claude"
    assert cli["reports"]["reviewer"].benchmark["claude_version"] == "2.1.331 (Claude Code)"
    out = capsys.readouterr().out
    assert "[reviewer] running via claude (model=" in out and "CLAUDE.md=loaded)" in out
    assert "[grader] running via claude" in out and "CLAUDE.md=omitted)" in out


@pytest.mark.parametrize(("mode", "expected"), [("on", True), ("off", False)])
def test_cli_mode_forces_the_role_not_the_judge(
    cli: dict[str, Any], mode: str, expected: bool
) -> None:
    argv = [
        "x",
        "--runner",
        "claude",
        "--role",
        "reviewer",
        "--role",
        "grader",
        "--omit-claude-md",
        mode,
    ]
    assert run_agent_evals.main(argv) == 0
    assert cli["build"]["reviewer"]["omit_claude_md"] is expected
    assert cli["build"]["grader"]["omit_claude_md"] is expected
    assert cli["build"]["reviewer"]["grader_omit_claude_md"] is True  # the judge never moves
    assert cli["reports"]["reviewer"].benchmark["omit_claude_md"] == mode
    assert cli["reports"]["reviewer"].benchmark["omit_claude_md_mode"] == mode


def test_cli_claude_md_reaches_every_workspace_and_the_record(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["x", "--runner", "claude", "--role", "reviewer", "--claude-md", str(_FIXTURE)]
    assert run_agent_evals.main([*argv, *cli["hist"], "--omit-claude-md", "on"]) == 0
    text = _FIXTURE.read_text(encoding="utf-8")
    assert cli["run_role"]["reviewer"]["claude_md"] == text
    label = f"typical-project.md@sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"
    assert cli["reports"]["reviewer"].benchmark["claude_md"] == label
    assert f"workspace CLAUDE.md={label}" in capsys.readouterr().out


def test_cli_rejects_a_missing_claude_md(cli: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        run_agent_evals.main(["x", "--runner", "claude", "--claude-md", str(tmp_path / "nope.md")])
    assert exc.value.code == 2
    assert cli["run_role"] == {}


@pytest.mark.parametrize(
    "extra",
    [["--claude-md", str(_FIXTURE)], ["--omit-claude-md", "on"], ["--omit-claude-md", "off"]],
)
def test_cli_api_runner_refuses_what_it_cannot_measure(
    cli: dict[str, Any], extra: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run_agent_evals.main(["x", "--runner", "api", "--role", "reviewer", *extra])
    assert exc.value.code == 2


def test_cli_api_runner_default_records_no_setup(cli: dict[str, Any]) -> None:
    assert run_agent_evals.main(["x", "--runner", "api", "--role", "reviewer"]) == 0
    assert cli["build"]["reviewer"]["omit_claude_md"] is None
    assert cli["build"]["reviewer"]["grader_omit_claude_md"] is None
    assert "omit_claude_md" not in cli["reports"]["reviewer"].benchmark
    assert cli["reports"]["reviewer"].benchmark["runner"] == "api"
    assert "claude_version" not in cli["reports"]["reviewer"].benchmark


def test_cli_refuses_a_temp_dir_the_cli_will_not_load_from(
    cli: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratch = tmp_path / "claude-1000" / "proj" / "sess" / "scratchpad"
    monkeypatch.setattr(run_agent_evals, "_temp_root", lambda: scratch)
    with pytest.raises(SystemExit) as exc:
        run_agent_evals.main(
            ["x", "--runner", "claude", "--role", "reviewer", "--claude-md", str(_FIXTURE)]
        )
    assert exc.value.code == 2
    assert "TMPDIR" in capsys.readouterr().err
    assert cli["run_role"] == {}
    # without --claude-md there is no file to lose, so the same temp dir is fine
    assert run_agent_evals.main(["x", "--runner", "claude", "--role", "reviewer"]) == 0


def test_cli_dry_run_accepts_the_flags(cli: dict[str, Any]) -> None:
    argv = [
        "x",
        "--runner",
        "dry",
        "--role",
        "reviewer",
        "--claude-md",
        str(_FIXTURE),
        "--omit-claude-md",
        "on",
    ]
    assert run_agent_evals.main(argv) == 0


def test_cli_rejects_claude_md_with_workdir(cli: dict[str, Any], tmp_path: Path) -> None:
    argv = ["x", "--runner", "claude", "--claude-md", str(_FIXTURE), "--workdir", str(tmp_path)]
    with pytest.raises(SystemExit) as exc:
        run_agent_evals.main(argv)
    assert exc.value.code == 2 and cli["run_role"] == {}


def test_cli_a_bad_role_file_fails_that_role_not_the_sweep(
    cli: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = agent_eval.resolve_omit_claude_md

    def resolve(mode: str, plugin_dir: Path, role: str) -> bool:
        if role == "reviewer":
            raise FileNotFoundError("agents/reviewer.md")
        return real(mode, plugin_dir, role)

    monkeypatch.setattr(run_agent_evals.agent_eval, "resolve_omit_claude_md", resolve)
    argv = ["x", "--runner", "claude", "--role", "reviewer", "--role", "grader"]
    assert run_agent_evals.main(argv) == 1  # the reviewer failed...
    assert "reviewer: ERROR" in capsys.readouterr().out
    assert list(cli["run_role"]) == ["grader"]  # ...and the grader still ran


def _arm(cli: dict[str, Any], arm: str, prompt_tokens: float | None = 50_000.0) -> int:
    cli["prompt_tokens"] = prompt_tokens
    argv = ["x", "--runner", "claude", "--role", "reviewer", "--claude-md", str(_FIXTURE)]
    return run_agent_evals.main([*argv, *cli["hist"], "--omit-claude-md", arm])


def test_ab_probe_runs_in_a_workspace_like_a_case(cli: dict[str, Any]) -> None:
    assert _arm(cli, "off") == 0
    ((arm, prompt, has_file, system),) = cli["probe_calls"]
    assert arm == "off" and prompt == agent_eval.PROBE_PROMPT and has_file
    assert system == agent_eval.role_body(_PLUGIN, "reviewer")  # the role's own system prompt


def test_ab_pair_is_valid_when_both_probes_are_as_expected(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _arm(cli, "on", 50_000.0) == 0
    first = capsys.readouterr().out
    assert "A/B arm on (CLAUDE.md omitted): probe answered 'NONE'" in first
    assert "is not quoted — as expected" in first
    assert "this arm is sound; no other arm with the same inputs" in first
    assert _arm(cli, "off", 58_000.0) == 0
    second = capsys.readouterr().out
    assert "probe answered '# Ledgerline - project rules'" in second  # a hyphen for the em dash
    assert "is quoted — as expected" in second
    assert "A/B pair: the other arm ran at git " in second
    assert "probe prompt tokens off-on=2100" in second  # information, not the test
    assert "prompt_tokens/run off-on=8000" in second
    assert "A/B check: VALID — both probes as expected" in second
    arms = json.loads(cli["ab"].read_text(encoding="utf-8"))
    assert [r["omit_claude_md"] for r in arms] == ["on", "off"]
    assert arms[0]["fingerprint"] == arms[1]["fingerprint"]
    assert arms[0]["fingerprint"] == agent_eval.input_fingerprint(
        _PLUGIN, "reviewer", _FIXTURE.read_text(encoding="utf-8")
    )
    for rec in arms:
        assert rec["probe_ok"] is True and rec["claude_version"] == "2.1.331 (Claude Code)"
        assert rec["git"] and "+" not in rec["git"] and rec["dirty"] in (True, False, None)
        assert rec["timestamp"].endswith("+00:00")
    assert arms[1]["probe_prompt_tokens"] == 3000 and arms[0]["answered_sessions"] == 3.0


@pytest.mark.parametrize(("arm", "answer"), [("off", "NONE"), ("on", "Ledgerline — project rules")])
def test_ab_an_arm_whose_probe_is_wrong_is_invalid_on_its_own(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str], arm: str, answer: str
) -> None:
    cli["probe"][arm] = answer  # the switch did not act: a null experiment
    assert _arm(cli, arm) == 1
    out = capsys.readouterr().out
    assert "NOT as expected" in out
    assert f"A/B check: INVALID — the {arm} arm's probe shows the switch did not act" in out
    (rec,) = json.loads(cli["ab"].read_text(encoding="utf-8"))
    assert rec["probe_ok"] is False  # kept, so a later pair with it is refused too


def test_ab_pair_with_an_invalid_other_arm_is_invalid(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli["probe"]["on"] = "Ledgerline — project rules"
    assert _arm(cli, "on") == 1
    cli["probe"]["on"] = "NONE"
    assert _arm(cli, "off") == 1
    assert "INVALID — the other arm's probe was not as expected" in capsys.readouterr().out


def test_ab_a_failed_probe_session_is_invalid(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli["probe"]["off"] = agent_eval.SessionUndetermined("api_error_529", "overloaded")
    assert _arm(cli, "off") == 1
    out = capsys.readouterr().out
    assert "probe session failed (session undetermined (api_error_529)" in out
    assert "INVALID" in out


def test_ab_never_pairs_other_inputs_or_another_cli(
    cli: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _arm(cli, "on") == 0
    monkeypatch.setattr(
        run_agent_evals._eval_cli, "claude_version", lambda: "2.1.400 (Claude Code)"
    )
    assert _arm(cli, "off") == 0
    assert "no other arm with the same inputs" in capsys.readouterr().out
    monkeypatch.setattr(
        run_agent_evals._eval_cli, "claude_version", lambda: "2.1.331 (Claude Code)"
    )
    monkeypatch.setattr(run_agent_evals.agent_eval, "input_fingerprint", lambda *a: "edited")
    assert _arm(cli, "off") == 0  # a role or fixture changed between the arms
    assert "no other arm with the same inputs" in capsys.readouterr().out


def test_ab_an_arm_without_a_token_count_says_so(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _arm(cli, "on", None) == 0
    assert "A/B arm on: this arm reported no prompt tokens" in capsys.readouterr().out


def test_ab_a_corrupt_arm_file_is_refused_not_overwritten(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli["ab"].write_text("[{ truncated", encoding="utf-8")
    argv = ["x", "--runner", "claude", "--role", "reviewer", "--role", "grader"]
    argv += ["--claude-md", str(_FIXTURE), *cli["hist"]]
    assert run_agent_evals.main(argv) == 1
    out = capsys.readouterr().out
    assert "reviewer: ERROR in the A/B check" in out and "move it aside" in out
    assert "grader: ERROR in the A/B check" in out  # each role failed alone, the sweep went on
    assert cli["ab"].read_text(encoding="utf-8") == "[{ truncated"  # untouched
    cli["ab"].write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ValueError, match="does not hold a list"):
        run_agent_evals._load_arms(cli["ab"])


def test_ab_arm_file_is_written_atomically(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "claude-md-ab.json"
    run_agent_evals._save_arms(path, [{"a": 1}])
    run_agent_evals._save_arms(path, [{"a": 1}, {"b": 2}])
    assert json.loads(path.read_text(encoding="utf-8")) == [{"a": 1}, {"b": 2}]
    assert [p.name for p in path.parent.iterdir()] == ["claude-md-ab.json"]  # no temp left

    class Boom:  # json.dump fails half-way: the old file stays whole
        def __repr__(self) -> str:
            return "Boom"

    with pytest.raises(TypeError):
        run_agent_evals._save_arms(path, [Boom()])  # type: ignore[list-item]
    assert json.loads(path.read_text(encoding="utf-8")) == [{"a": 1}, {"b": 2}]
    assert [p.name for p in path.parent.iterdir()] == ["claude-md-ab.json"]


def test_cli_rejects_a_claude_md_without_a_heading(cli: dict[str, Any], tmp_path: Path) -> None:
    flat = tmp_path / "flat.md"
    flat.write_text("rules without a heading\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_agent_evals.main(["x", "--runner", "claude", "--claude-md", str(flat), *cli["hist"]])
    assert exc.value.code == 2


def test_ab_an_invalid_arm_never_becomes_a_baseline(cli: dict[str, Any]) -> None:
    history = Path(cli["hist"][1])
    cli["probe"]["off"] = "NONE"  # the switch did not act
    argv = ["x", "--runner", "claude", "--role", "reviewer", "--claude-md", str(_FIXTURE)]
    assert run_agent_evals.main([*argv, *cli["hist"], "--omit-claude-md", "off", "--record"]) == 1
    assert not history.exists()  # --record kept nothing...
    arms = json.loads(cli["ab"].read_text(encoding="utf-8"))
    assert [r["probe_ok"] for r in arms] == [False]  # ...but the arm file keeps the arm
    cli["probe"]["off"] = "Ledgerline — project rules"
    assert run_agent_evals.main([*argv, *cli["hist"], "--omit-claude-md", "off", "--record"]) == 0
    assert len(benchmark.load_history(history)) == 1  # a sound arm is recorded as before


@pytest.mark.parametrize(("arm", "code"), [("off", 0), ("on", 1)])
def test_ab_a_heading_quoted_after_a_long_preamble_is_found(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str], arm: str, code: int
) -> None:
    cli["probe"][arm] = "Here is what I was given. " * 12 + "# Ledgerline — project rules"
    assert len(cli["probe"][arm]) > 300
    assert _arm(cli, arm) == code  # off: quoted, as expected; on: quoted, so INVALID
    (rec,) = json.loads(cli["ab"].read_text(encoding="utf-8"))
    assert rec["probe_answer"].endswith("# Ledgerline — project rules")  # kept whole
    assert "probe answered" in capsys.readouterr().out


def test_ab_never_pairs_when_the_cli_version_is_unknown(
    cli: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run_agent_evals._eval_cli, "claude_version", lambda: "unknown")
    assert _arm(cli, "on") == 0
    assert _arm(cli, "off") == 0
    out = capsys.readouterr().out
    assert out.count("cannot be paired: `claude --version` did not answer") == 2
    assert "VALID" not in out


def test_ab_pair_warns_on_another_commit_or_run_count(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _arm(cli, "on") == 0
    arms = json.loads(cli["ab"].read_text(encoding="utf-8"))
    arms[0].update(git="0000000", n=3)
    cli["ab"].write_text(json.dumps(arms), encoding="utf-8")
    assert _arm(cli, "off") == 0
    out = capsys.readouterr().out
    assert "WARNING — the arms ran at different commits (0000000 vs" in out
    assert "WARNING — the arms measured different numbers of runs (n=3 vs n=5)" in out
    assert "A/B check: VALID" in out


@pytest.mark.parametrize(
    "heading",
    [
        "Rules",  # too short
        "Contributing",  # one word
        "Project CLAUDE.md",  # part of the probe's own question
        "Quote the first Markdown heading",  # ditto
    ],
)
def test_cli_refuses_a_generic_heading(cli: dict[str, Any], tmp_path: Path, heading: str) -> None:
    assert agent_eval.heading_problem(heading) is not None
    path = tmp_path / "generic.md"
    path.write_text(f"# {heading}\n\nrules\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_agent_evals.main(["x", "--runner", "claude", "--claude-md", str(path), *cli["hist"]])
    assert exc.value.code == 2 and cli["run_role"] == {}


def test_heading_problem_accepts_a_distinctive_heading() -> None:
    assert agent_eval.heading_problem("Ledgerline — project rules") is None
    assert agent_eval.heading_problem(None) is not None
    assert agent_eval.PROBE_PROMPT.endswith("Reply with the heading text only.")


# --- the probe's parts -----------------------------------------------------------


def test_first_heading_and_quotes_heading() -> None:
    assert agent_eval.first_heading("intro\n\n## Rules ##\n# Later\n") == "Rules"
    assert agent_eval.first_heading("no heading\n#hashtag\n") is None
    heading = agent_eval.first_heading(_FIXTURE.read_text(encoding="utf-8"))
    assert heading == "Ledgerline — project rules"
    assert agent_eval.quotes_heading("The heading is: # Ledgerline - Project  Rules", heading)
    assert not agent_eval.quotes_heading("NONE", heading)


def test_claude_md_probe_builds_and_removes_its_workspace() -> None:
    seen: dict[str, Any] = {}

    def run(system: str, prompt: str, workdir: Path) -> str:
        seen["work"] = workdir
        seen["file"] = (workdir / "CLAUDE.md").read_text(encoding="utf-8")
        return RunOutput("# Title", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    result = agent_eval.claude_md_probe(run, "SYS", "# Title\n")
    assert result == {"answer": "# Title", "prompt_tokens": 1}
    assert seen["file"] == "# Title\n" and seen["work"].name.startswith("af-eval-")
    assert not seen["work"].exists()

    def dead(system: str, prompt: str, workdir: Path) -> str:
        raise RuntimeError("claude call failed")

    assert agent_eval.claude_md_probe(dead, "SYS", "# T\n") == {"error": "claude call failed"}


def test_claude_md_probe_keeps_a_long_answer_whole() -> None:
    preamble = "x" * 300
    long = f"{preamble}\n\n  # Ledgerline — project rules  " + "y" * 5000

    def run(system: str, prompt: str, workdir: Path) -> str:
        return long

    answer = agent_eval.claude_md_probe(run, "SYS", "# Ledgerline — project rules\n")["answer"]
    assert answer.startswith(preamble + " # Ledgerline — project rules y")  # whitespace normalised
    assert len(answer) == 4000  # a generous cap, not the 200-character display cap
    assert agent_eval.quotes_heading(answer, "Ledgerline — project rules")


def test_input_fingerprint_moves_with_every_input(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    for rel in (
        "agents/reviewer.md",
        "agents/grader.md",
        "agents/evals/reviewer.evals.json",
        "eval/fixtures/reviewer",
    ):
        src, dst = _PLUGIN / rel, plugin / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copyfile(src, dst)
    base = agent_eval.input_fingerprint(plugin, "reviewer", "# F\n")
    assert base == agent_eval.input_fingerprint(_PLUGIN, "reviewer", "# F\n")  # content, not path
    assert agent_eval.input_fingerprint(plugin, "reviewer", "# G\n") != base
    for rel in (
        "agents/reviewer.md",
        "agents/grader.md",
        "eval/fixtures/reviewer/case2.diff",
        "agents/evals/reviewer.evals.json",
    ):
        target = plugin / rel
        original = target.read_bytes()
        target.write_bytes(original + b" ")
        assert agent_eval.input_fingerprint(plugin, "reviewer", "# F\n") != base, rel
        target.write_bytes(original)
    assert agent_eval.input_fingerprint(plugin, "reviewer", "# F\n") == base


def test_probe_runner_shares_the_component_env(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(
        _eval_cli.agent_eval, "claude_cli_runner", lambda **kw: built.append(kw) or "r"
    )
    _eval_cli.build_claude_md_probe(model="m", plugin_dir=_PLUGIN, omit_claude_md=False)
    _eval_cli.build_runners(
        "claude", allowed_tools="Read", model="m", plugin_dir=_PLUGIN, omit_claude_md=False
    )
    probe, component = built[0], built[1]
    assert probe["env"] == component["env"]  # the same switch and pinned variables
    assert probe["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "0"
    assert (probe["tools"], probe["allowed_tools"], probe["max_turns"]) == ("", "", 1)
    assert probe["model"] == "m"
    built.clear()
    _eval_cli.build_claude_md_probe(model="m", plugin_dir=_PLUGIN, omit_claude_md=True)
    assert built[0]["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"


# --- the fixture ---------------------------------------------------------------


def test_the_fixture_is_a_realistic_claude_md_with_rules_a_reviewer_honours() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    assert 120 <= len(text.splitlines()) <= 200
    # the two rules the README maps onto assertions the lenses already carry
    assert "negative index does not fail in Python" in text
    assert "Catching `IndexError` afterwards is not validation" in text
    assert "No secret reaches a log line" in text
    readme = (_FIXTURE.parent / "README.md").read_text(encoding="utf-8")
    assert "should honour when reviewing" in readme
    assert "`reviewer` case 1" in readme and "`security-engineer` case 2" in readme
