from __future__ import annotations

from agentic_forge import gate


def _benchmark(mean: float, stddev: float, n: int, delta: dict | None = None) -> dict:
    rs = {"with_skill": {"pass_rate": {"mean": mean, "stddev": stddev}, "n": n}}
    if delta is not None:
        rs["delta"] = delta
    return {"run_summary": rs}


# --- trigger metrics ---

def test_trigger_metrics() -> None:
    # Booleans are valid 0.0/1.0 rates (single-sample runs).
    m = gate.trigger_metrics([1.0, 1.0, 0.0], [0.0, 0.0])
    assert abs(m["recall"] - 2 / 3) < 1e-9
    assert m["specificity"] == 1.0


def test_trigger_metrics_mean_of_rates() -> None:
    # Mean routing rate (ADR 0026), not fraction-of-majorities: a 0.6 prompt contributes 0.6.
    m = gate.trigger_metrics([1.0, 0.6], [0.2, 0.0])
    assert abs(m["recall"] - 0.8) < 1e-9  # mean(1.0, 0.6)
    assert abs(m["specificity"] - 0.9) < 1e-9  # mean(1-0.2, 1-0.0)


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


def test_tier2_no_threshold_is_not_vacuous_pass() -> None:
    # a tier2_quality block with no min_pass_rate must NOT pass a zero-rate benchmark
    bm = _benchmark(0.0, 0.0, 5)
    res = gate.tier2_quality(bm, {"tier2_quality": {}})
    assert not res.passed
    assert any("min_pass_rate" in r for r in res.reasons)


def test_tier2_boundary_lower_bound_equal_passes() -> None:
    # lower bound exactly equal to the threshold passes (>= intent, no off-by-one)
    bm = _benchmark(0.8, 0.0, 5)
    res = gate.tier2_quality(bm, {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}})
    assert res.passed, res.reasons


def test_all_passed_empty_is_false() -> None:
    # nothing measured is not a pass (guards evaluate() called with no data)
    assert gate.all_passed([]) is False


def test_tier2_float_error_at_threshold_passes() -> None:
    # 0.85 - 0.05 == 0.7999999999999999 must NOT fail the 0.8 gate (binary-float tolerance)
    res = gate.tier2_quality(_benchmark(0.85, 0.05, 5), {"tier2_quality": {"min_pass_rate": 0.8}})
    assert res.passed, res.reasons


def test_tier1_float_error_at_threshold_passes() -> None:
    # mean([.7,.8,.9]) == 0.7999999999999999 must pass recall >= 0.8
    m = gate.trigger_metrics([0.7, 0.8, 0.9], [0.0])
    res = gate.tier1_trigger(m, {"tier1_trigger": {"recall": 0.8, "specificity": 0.9}})
    assert res.passed, res.reasons


# --- evaluate orchestration ---

def test_tier2_fail_time_overhead() -> None:
    bm = _benchmark(0.95, 0.0, 5, delta={"time_seconds": 120.0})
    res = gate.tier2_quality(bm, {"tier2_quality": {"max_overhead_seconds": 30}})
    assert not res.passed
    assert any("time overhead" in r for r in res.reasons)


def test_gate_result_str() -> None:
    passing = gate.GateResult("tier2_quality", True)
    failing = gate.GateResult("tier1_trigger", False, ["recall 0.5 < required 0.9"])
    assert "PASS" in str(passing)
    assert "FAIL" in str(failing) and "recall" in str(failing)


def test_evaluate_skips_tiers_without_data() -> None:
    evals_json = {"thresholds": {"tier2_quality": {"min_pass_rate": 0.8}}}
    # No benchmark and no trigger data -> no tiers evaluated.
    assert gate.evaluate(evals_json) == []


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


# --- version-over-version A/B (ADR 0047) -------------------------------------


def test_version_regression_skips_without_threshold_or_prior() -> None:
    bench = _benchmark(0.9, 0.0, 5)
    assert gate.version_regression(bench, {"mean": 0.9}, {"tier2_quality": {}}) is None  # opt-in
    thr = {"tier2_quality": {"max_regression": 0.05}}
    assert gate.version_regression(bench, None, thr) is None  # no prior (first run) -> skip


def test_version_regression_passes_within_tolerance_and_on_improvement() -> None:
    thr = {"tier2_quality": {"max_regression": 0.05}}
    within = gate.version_regression(_benchmark(0.86, 0.0, 5), {"mean": 0.90}, thr)  # dropped 0.04
    assert within is not None and within.passed
    up = gate.version_regression(_benchmark(0.95, 0.0, 5), {"mean": 0.90}, thr)  # improved
    assert up is not None and up.passed


def test_version_regression_fails_on_drop() -> None:
    thr = {"tier2_quality": {"max_regression": 0.05}}
    res = gate.version_regression(_benchmark(0.80, 0.0, 5), {"mean": 0.90}, thr)  # dropped 0.10
    assert res is not None and not res.passed and "regression" in res.reasons[0]


def test_version_regression_missing_mean_fails() -> None:
    thr = {"tier2_quality": {"max_regression": 0.05}}
    bench = {"run_summary": {"with_skill": {"pass_rate": {}, "n": 5}}}  # no current mean
    res = gate.version_regression(bench, {"mean": 0.9}, thr)
    assert res is not None and not res.passed


# --- sessions that produced no measurement (eval audit C8/C13; ADR 0093 for every tier) -------


def _sessions(total: int, undetermined: int = 0, ungraded: int = 0, **subtypes: int) -> dict:
    return {
        "total": total, "undetermined": undetermined, "ungraded": ungraded,
        "subtypes": subtypes, "events": [],
    }


def test_tier2_unmeasured_share_over_the_cap_fails() -> None:
    bm = _benchmark(1.0, 0.0, 5)
    bm["run_summary"]["with_skill"]["sessions"] = _sessions(10, undetermined=2, error_max_turns=2)
    res = gate.tier2_quality(bm, {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}})
    assert not res.passed
    assert res.reasons == [
        "2 of 10 sessions unmeasured (> 10%): 2 undetermined [error_max_turns x2] — the run "
        "failed, not the component"
    ]


def test_tier2_unmeasured_share_at_the_cap_passes_and_is_printed() -> None:
    bm = _benchmark(1.0, 0.0, 5)
    bm["run_summary"]["with_skill"]["sessions"] = _sessions(10, ungraded=1)
    res = gate.tier2_quality(bm, {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}})
    assert res.passed
    line = gate.format_tier2_summary("x", passed=True, benchmark=bm, reasons=[])
    assert line == (
        "x: PASS (mean=1.000, stddev=0.000, lower_bound=1.000, n=5; "
        "1/10 sessions unmeasured: 1 ungraded)"
    )


def test_tier2_summary_without_sessions_is_unchanged() -> None:
    line = gate.format_tier2_summary(
        "x", passed=True, benchmark=_benchmark(0.9, 0.05, 5), reasons=[]
    )
    assert line == "x: PASS (mean=0.900, stddev=0.050, lower_bound=0.850, n=5)"


def test_tier2_evidence_lines_name_run_case_subtype_and_turns() -> None:
    bm = _benchmark(1.0, 0.0, 5)
    bm["run_summary"]["with_skill"]["sessions"] = {
        "total": 10, "undetermined": 1, "ungraded": 1, "subtypes": {"error_max_turns": 1},
        "events": [
            {"run": 2, "case": 1, "kind": "undetermined", "subtype": "error_max_turns",
             "num_turns": 40, "text": ""},
            {"run": 3, "case": 2, "kind": "ungraded", "subtype": "grading-unparseable",
             "text": "no valid JSON grading object"},
        ],
    }
    assert gate.tier2_evidence_lines(bm) == [
        "    unmeasured: run 2 case 1 undetermined (error_max_turns, num_turns=40)",
        "    unmeasured: run 3 case 2 ungraded (grading-unparseable): no valid JSON grading object",
    ]
    assert gate.tier2_evidence_lines(_benchmark(1.0, 0.0, 5)) == []


def test_max_undetermined_is_one_number_for_every_tier() -> None:
    from agentic_forge import activation

    assert gate.MAX_UNDETERMINED == 0.10 and activation.MAX_UNDETERMINED is gate.MAX_UNDETERMINED


# --- Tier-1 samples-per-prompt floor (eval audit C3/C9) ----------------------------------------


def test_tier1_runs_floor_from_the_contract() -> None:
    thr = {"tier1_trigger": {"recall": 0.9, "specificity": 0.9, "runs": 5}}
    good = {"recall": 1.0, "specificity": 1.0, "runs": 5}
    assert gate.tier1_trigger(good, thr).passed
    thin = gate.tier1_trigger({**good, "runs": 2}, thr)
    assert not thin.passed and thin.reasons == ["only 2 sample(s) per prompt; need >= 5"]
    unknown = gate.tier1_trigger({"recall": 1.0, "specificity": 1.0}, thr)
    assert not unknown.passed and "only 0 sample(s)" in unknown.reasons[0]
    # no `runs` in the contract: the count is not gated (the CLI's default 5 still applies)
    assert gate.tier1_trigger({**good, "runs": 1}, {"tier1_trigger": {"recall": 0.9}}).passed


# --- a Tier-2 FAIL says WHICH assertion failed (ADR 0096) --------------------------------


def _graded(*rows: tuple[str, bool]) -> dict:
    return {"assertion_results": [{"text": t, "passed": p} for t, p in rows]}


def test_failed_assertions_are_tallied_worst_first() -> None:
    from agentic_forge.benchmark import failed_assertions

    gradings = [
        _graded(("no secret ships", False), ("zip lands under Downloads", True)),
        _graded(("no secret ships", False), ("zip lands under Downloads", False)),
        _graded(("no secret ships", "true"), ("zip lands under Downloads", True)),
    ]
    assert failed_assertions(gradings) == [
        {"text": "no secret ships", "failed": 2, "total": 3},
        {"text": "zip lands under Downloads", "failed": 1, "total": 3},
    ]
    assert failed_assertions([_graded(("all good", True))]) == []  # nothing failed, nothing said


def test_tier2_evidence_names_the_failing_assertion() -> None:
    """A pass-rate below the bar used to print the number and nothing else, so finding out which
    assertion slipped cost a second paid run — ADR 0084's rule, applied to the priciest tier."""
    from agentic_forge.benchmark import summarize

    bench = summarize([_graded(("no secret ships", False)), _graded(("no secret ships", True))])
    lines = gate.tier2_evidence_lines(bench)
    assert lines == ["    failed 1/2: no secret ships"]
    assert gate.tier2_evidence_lines({}) == []  # nothing recorded, nothing claimed

