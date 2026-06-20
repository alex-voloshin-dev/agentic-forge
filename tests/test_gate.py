from __future__ import annotations

from agentic_forge import gate


def _benchmark(mean: float, stddev: float, n: int, delta: dict | None = None) -> dict:
    rs = {"with_skill": {"pass_rate": {"mean": mean, "stddev": stddev}, "n": n}}
    if delta is not None:
        rs["delta"] = delta
    return {"run_summary": rs}


# --- trigger metrics ---

def test_trigger_metrics() -> None:
    m = gate.trigger_metrics([True, True, False], [False, False])
    assert abs(m["recall"] - 2 / 3) < 1e-9
    assert m["specificity"] == 1.0


def test_trigger_metrics_empty() -> None:
    m = gate.trigger_metrics([], [])
    assert m["recall"] is None and m["specificity"] is None


# --- tier 1 ---

def test_tier1_pass() -> None:
    res = gate.tier1_trigger(
        {"recall": 0.95, "specificity": 0.95},
        {"tier1_trigger": {"recall": 0.9, "specificity": 0.9}},
    )
    assert res.passed


def test_tier1_fail_low_recall() -> None:
    res = gate.tier1_trigger(
        {"recall": 0.5, "specificity": 0.95},
        {"tier1_trigger": {"recall": 0.9, "specificity": 0.9}},
    )
    assert not res.passed
    assert any("recall" in r for r in res.reasons)


def test_tier1_fail_missing_measurement() -> None:
    res = gate.tier1_trigger({"recall": None}, {"tier1_trigger": {"recall": 0.9}})
    assert not res.passed


# --- tier 2 ---

def test_tier2_pass_lower_bound() -> None:
    bm = _benchmark(0.9, 0.05, 5)
    res = gate.tier2_quality(bm, {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}})
    assert res.passed, res.reasons


def test_tier2_fail_lower_bound() -> None:
    # mean - stddev = 0.78 < 0.8
    bm = _benchmark(0.85, 0.07, 5)
    res = gate.tier2_quality(bm, {"tier2_quality": {"min_pass_rate": 0.8}})
    assert not res.passed


def test_tier2_fail_too_few_runs() -> None:
    bm = _benchmark(0.95, 0.0, 2)
    res = gate.tier2_quality(bm, {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}})
    assert not res.passed
    assert any("run" in r for r in res.reasons)


def test_tier2_fail_token_overhead() -> None:
    bm = _benchmark(0.95, 0.0, 5, delta={"tokens": 5000})
    res = gate.tier2_quality(bm, {"tier2_quality": {"max_overhead_tokens": 1000}})
    assert not res.passed


def test_tier2_no_benchmark() -> None:
    res = gate.tier2_quality({}, {"tier2_quality": {"min_pass_rate": 0.8}})
    assert not res.passed


# --- evaluate orchestration ---

def test_evaluate_runs_applicable_tiers() -> None:
    evals_json = {
        "thresholds": {
            "tier1_trigger": {"recall": 0.9, "specificity": 0.9},
            "tier2_quality": {"min_pass_rate": 0.8, "runs": 5},
        }
    }
    results = gate.evaluate(
        evals_json,
        benchmark=_benchmark(0.95, 0.02, 5),
        trigger_measured={"recall": 1.0, "specificity": 1.0},
    )
    assert len(results) == 2
    assert gate.all_passed(results)
