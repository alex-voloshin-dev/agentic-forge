from __future__ import annotations

from agentic_forge import benchmark


def _grading(rate: float) -> dict:
    return {"summary": {"pass_rate": rate}}


def test_pass_rate_from_summary() -> None:
    assert benchmark.pass_rate_of({"summary": {"pass_rate": 0.75}}) == 0.75


def test_pass_rate_from_counts() -> None:
    assert benchmark.pass_rate_of({"summary": {"passed": 3, "total": 4}}) == 0.75


def test_pass_rate_from_assertion_results() -> None:
    g = {"assertion_results": [{"passed": True}, {"passed": False}]}
    assert benchmark.pass_rate_of(g) == 0.5


def test_pass_rate_empty() -> None:
    assert benchmark.pass_rate_of({}) == 0.0


def test_summarize_with_only() -> None:
    out = benchmark.summarize([_grading(0.8), _grading(0.9)])
    ws = out["run_summary"]["with_skill"]
    assert abs(ws["pass_rate"]["mean"] - 0.85) < 1e-9
    assert ws["n"] == 2
    assert ws["pass_rate"]["stddev"] > 0
    assert "without_skill" not in out["run_summary"]


def test_summarize_with_baseline_delta() -> None:
    out = benchmark.summarize([_grading(0.8), _grading(0.8)], [_grading(0.3), _grading(0.3)])
    assert abs(out["run_summary"]["delta"]["pass_rate"] - 0.5) < 1e-9
    assert out["run_summary"]["with_skill"]["pass_rate"]["stddev"] == 0.0


def test_summarize_empty() -> None:
    out = benchmark.summarize([])
    assert out["run_summary"]["with_skill"]["n"] == 0


def test_summarize_with_timing_overhead() -> None:
    out = benchmark.summarize(
        [_grading(0.9)],
        [_grading(0.4)],
        with_skill_timing=[{"total_tokens": 5000, "duration_ms": 40000}],
        without_skill_timing=[{"total_tokens": 2000, "duration_ms": 30000}],
    )
    rs = out["run_summary"]
    assert rs["with_skill"]["tokens"] == 5000
    assert rs["with_skill"]["time_seconds"] == 40.0
    assert rs["delta"]["tokens"] == 3000
    assert rs["delta"]["time_seconds"] == 10.0


def test_summarize_timing_with_only() -> None:
    out = benchmark.summarize(
        [_grading(0.9)],
        with_skill_timing=[{"total_tokens": 100, "duration_ms": 1000}],
    )
    assert out["run_summary"]["with_skill"]["tokens"] == 100
    assert "delta" not in out["run_summary"]
