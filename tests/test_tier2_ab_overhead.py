"""Tier-2 A/B + overhead wiring (ADR 0036).

Covers the newly-live half of the Tier-2 pyramid: per-run wall-clock timing capture, the opt-in
without-skill baseline that produces the with/without delta, the ``min_lift`` gate, and the
honest-tokens change in ``summarize`` (no phantom ``tokens: 0.0`` for wall-clock-only timing).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agentic_forge import agent_eval, benchmark, gate
from agentic_forge.skill_eval import (
    build_skill_baseline_system,
    build_skill_system,
    run_skill,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


# --- summarize: tokens reported only when a count is present ------------------


def test_summarize_wallclock_only_omits_tokens() -> None:
    out = benchmark.summarize(
        [{"summary": {"pass_rate": 1.0}}],
        with_skill_timing=[{"duration_ms": 1200}],  # no total_tokens (the live runner's shape)
    )
    ws = out["run_summary"]["with_skill"]
    assert "time_seconds" in ws and ws["time_seconds"] == 1.2
    assert "tokens" not in ws  # honest: no phantom 0.0 when the transport gave no usage


def test_summarize_reports_tokens_when_present() -> None:
    out = benchmark.summarize(
        [{"summary": {"pass_rate": 1.0}}],
        with_skill_timing=[{"duration_ms": 1000, "total_tokens": 42}],
    )
    assert out["run_summary"]["with_skill"]["tokens"] == 42


def test_summarize_delta_omits_token_overhead_for_wallclock_only() -> None:
    out = benchmark.summarize(
        [{"summary": {"pass_rate": 1.0}}],
        [{"summary": {"pass_rate": 0.5}}],
        with_skill_timing=[{"duration_ms": 2000}],
        without_skill_timing=[{"duration_ms": 1000}],
    )
    delta = out["run_summary"]["delta"]
    assert abs(delta["pass_rate"] - 0.5) < 1e-9
    assert abs(delta["time_seconds"] - 1.0) < 1e-9
    assert "tokens" not in delta  # no token overhead reported without token counts


# --- gate: the A/B min_lift check --------------------------------------------


def _bench(mean: float, *, n: int = 5, delta: dict[str, float] | None = None) -> dict[str, object]:
    rs: dict[str, object] = {"with_skill": {"pass_rate": {"mean": mean, "stddev": 0.0}, "n": n}}
    if delta is not None:
        rs["delta"] = delta
    return {"run_summary": rs}


def test_min_lift_fails_when_skill_does_not_help_enough() -> None:
    res = gate.tier2_quality(
        _bench(0.95, delta={"pass_rate": 0.05}),
        {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5, "min_lift": 0.1}},
    )
    assert not res.passed
    assert any("A/B pass-rate lift" in r for r in res.reasons)


def test_min_lift_passes_when_lift_meets_bar() -> None:
    res = gate.tier2_quality(
        _bench(0.95, delta={"pass_rate": 0.2}),
        {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5, "min_lift": 0.1}},
    )
    assert res.passed


def test_min_lift_skipped_without_a_baseline() -> None:
    # min_lift set but no delta (no --baseline run) must NOT fail — the lift is unmeasured.
    res = gate.tier2_quality(
        _bench(0.95),  # no delta
        {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5, "min_lift": 0.5}},
    )
    assert res.passed


# --- run_eval_cases: timing capture + baseline delta -------------------------


def _component_keyed_on_marker(system: str, prompt: str, workdir: Path) -> str:
    return "GOOD" if "WITHSKILL" in system else "BAD"


def _grader_keyed_on_output(system: str, prompt: str, workdir: Path) -> str:
    # The grading prompt embeds the component's WORK OUTPUT; pass each assertion iff it was GOOD.
    items = re.findall(r"^\d+\.\s+(.*)$", prompt, re.MULTILINE)
    ok = "GOOD" in prompt
    return json.dumps({"assertion_results": [{"text": a, "passed": ok} for a in items]})


_CASES = [{"prompt": "do the task", "assertions": ["a1", "a2"]}]
_THRESH = {"tier2_quality": {"min_pass_rate": 0.8, "runs": 3}}


def test_run_eval_cases_captures_timing_without_baseline() -> None:
    bench, _, _ = agent_eval.run_eval_cases(
        system_body="WITHSKILL",
        grader_body="g",
        cases=_CASES,
        thresholds=_THRESH,
        plugin_dir=PLUGIN,
        run_fn=_component_keyed_on_marker,
        grader_fn=_grader_keyed_on_output,
        runs=3,
        isolate=False,
    )
    rs = bench["run_summary"]
    assert "time_seconds" in rs["with_skill"]  # wall-clock captured on every run
    assert "without_skill" not in rs and "delta" not in rs  # no baseline -> no A/B


def test_run_eval_cases_baseline_produces_ab_lift() -> None:
    bench, _, _ = agent_eval.run_eval_cases(
        system_body="WITHSKILL",  # component returns GOOD -> all assertions pass
        grader_body="g",
        cases=_CASES,
        thresholds=_THRESH,
        plugin_dir=PLUGIN,
        run_fn=_component_keyed_on_marker,
        grader_fn=_grader_keyed_on_output,
        runs=3,
        isolate=False,
        baseline_system_body="(no marker)",  # component returns BAD -> all fail
    )
    rs = bench["run_summary"]
    assert abs(rs["with_skill"]["pass_rate"]["mean"] - 1.0) < 1e-9
    assert abs(rs["without_skill"]["pass_rate"]["mean"] - 0.0) < 1e-9
    assert abs(rs["delta"]["pass_rate"] - 1.0) < 1e-9
    assert "time_seconds" in rs["delta"]  # time-overhead delta present


# --- skill_eval: the without-skill baseline system ---------------------------


def test_baseline_system_for_pack_drops_the_pack_body() -> None:
    baseline = build_skill_baseline_system(PLUGIN, "python-patterns")
    assert "base engineering role" in baseline  # the executor is held constant...
    assert "Engineering standards" in baseline
    assert "Python patterns" not in baseline  # ...but the skill under test is removed
    # base role + standards == build_skill_system(engineering-standards) exactly
    assert baseline == build_skill_system(PLUGIN, "engineering-standards")
    assert len(build_skill_system(PLUGIN, "python-patterns")) > len(baseline)


def test_baseline_system_for_standards_is_base_role_only() -> None:
    baseline = build_skill_baseline_system(PLUGIN, "engineering-standards")
    assert "base engineering role" in baseline
    assert "Engineering standards" not in baseline  # standards IS the skill under test -> removed
    # the pack baseline (base + standards) extends the standards baseline (base only)
    assert build_skill_baseline_system(PLUGIN, "python-patterns").startswith(baseline)


def test_baseline_system_for_on_listing_skill_is_empty() -> None:
    assert build_skill_baseline_system(PLUGIN, "deep-review") == ""


# --- run_skill: end-to-end opt-in baseline -----------------------------------


def _runner(output: str) -> agent_eval.Runner:
    def run(system: str, prompt: str, workdir: Path) -> str:
        return output

    return run


def _grader(passed: bool) -> agent_eval.Runner:
    one = '{"passed":true}' if passed else '{"passed":false}'
    body = '{"assertion_results":[' + ",".join([one] * 8) + "]}"

    def run(system: str, prompt: str, workdir: Path) -> str:
        return body

    return run


def test_run_skill_without_baseline_has_no_ab() -> None:
    rep = run_skill(
        "deep-review",
        PLUGIN,
        run_skill_fn=_runner("done"),
        run_grader_fn=_grader(True),
        runs=2,
    )
    rs = rep.benchmark["run_summary"]
    assert "without_skill" not in rs and "delta" not in rs
    assert "time_seconds" in rs["with_skill"]  # timing still captured


def test_run_skill_with_baseline_produces_ab_block() -> None:
    rep = run_skill(
        "deep-review",
        PLUGIN,
        run_skill_fn=_runner("done"),
        run_grader_fn=_grader(True),
        runs=2,
        with_baseline=True,
    )
    rs = rep.benchmark["run_summary"]
    assert "without_skill" in rs and "delta" in rs  # the baseline pass ran and produced a delta
    assert "pass_rate" in rs["delta"] and "time_seconds" in rs["delta"]
