"""The agentic-forge eval gate: turn measurements into pass/fail against thresholds.

This is the policy layer on top of skill-creator. It applies the eval pyramid:
- Tier 1 (trigger): recall / specificity of auto-loading.
- Tier 2 (quality): pass-rate lower bound (mean - stddev), run count, overhead.
Tier 0 (static) is handled by validation.py; Tier 3 (E2E) is added with workflows.

All functions are pure and deterministic so they are unit-testable without an LLM.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "GateResult",
    "MAX_UNDETERMINED",
    "trigger_metrics",
    "tier1_trigger",
    "tier2_quality",
    "version_regression",
    "format_tier2_summary",
    "tier2_evidence_lines",
    "evaluate",
    "all_passed",
]

# Float-comparison tolerance: a metric exactly at its threshold must not FAIL due to binary-float
# representation (e.g. 0.85 - 0.05 == 0.7999999999999999, not 0.8).
_EPS = 1e-9

# A run with more than this share of its samples unmeasured FAILS on that alone: the rate over the
# rest may be fine, but the run is not the measurement it claims to be. Below it, a stray dead
# session, turn-cap hit, unparseable grading or no-decision router call is excluded from the rate
# rather than read as a failure (ADR 0093, first for Tier-1b; now every tier). One number, one
# meaning: "sample produced no measurement" is the same event whichever runner saw it.
MAX_UNDETERMINED = 0.10


@dataclass
class GateResult:
    tier: str
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        suffix = "" if self.passed else ": " + "; ".join(self.reasons)
        return f"{self.tier} {status}{suffix}"


def trigger_metrics(
    should_trigger_rates: list[float],
    should_not_trigger_rates: list[float],
) -> dict[str, float | None]:
    """Compute recall and specificity from per-prompt routing **rates** (ADR 0026).

    Each rate is the fraction of router samples that picked the skill for that prompt (``[0, 1]``).
    ``recall`` is the mean rate over should-trigger prompts; ``specificity`` the mean rate of *not*
    picking the skill over should-not-trigger prompts. Booleans (``0.0``/``1.0``) are valid rates,
    so single-sample runs still work. Replaces the fraction-of-prompt-majorities, which flickered
    at the 50% cliff and passed barely-majority routing.
    """
    recall = (
        sum(should_trigger_rates) / len(should_trigger_rates) if should_trigger_rates else None
    )
    specificity = (
        sum(1.0 - r for r in should_not_trigger_rates) / len(should_not_trigger_rates)
        if should_not_trigger_rates
        else None
    )
    return {"recall": recall, "specificity": specificity}


def tier1_trigger(measured: dict[str, float | None], thresholds: dict[str, Any]) -> GateResult:
    """Gate recall/specificity, and — when the contract sets ``tier1_trigger.runs`` — the number of
    samples each prompt was asked (``measured["runs"]``): a rate from one call per prompt is a coin
    flip dressed as a rate, so a contract may pin the floor the CLI's default (5) provides."""
    want = thresholds.get("tier1_trigger") or {}
    reasons: list[str] = []
    for key in ("recall", "specificity"):
        target = want.get(key)
        if target is None:
            continue
        got = measured.get(key)
        if got is None:
            reasons.append(f"missing measured {key}")
        elif got < target - _EPS:
            reasons.append(f"{key} {got:.3f} < required {target:.3f}")
    req_runs = want.get("runs")
    if req_runs is not None:
        n = measured.get("runs")
        if n is None or n < req_runs:
            reasons.append(
                f"only {n if n is not None else 0} sample(s) per prompt; need >= {req_runs}"
            )
    return GateResult("tier1_trigger", not reasons, reasons)


def tier2_quality(benchmark: dict[str, Any], thresholds: dict[str, Any]) -> GateResult:
    want = thresholds.get("tier2_quality") or {}
    reasons: list[str] = []

    run_summary = benchmark.get("run_summary") or {}
    ws = run_summary.get("with_skill") or {}
    pr = ws.get("pass_rate") or {}
    mean = pr.get("mean")
    stddev = pr.get("stddev", 0.0)
    n = ws.get("n", 0)

    if mean is None:
        return GateResult("tier2_quality", False, ["no with_skill pass_rate in benchmark"])

    min_pr = want.get("min_pass_rate")
    if min_pr is None:
        # A tier2_quality block with no pass-rate threshold gates nothing — treat as misconfigured
        # rather than a vacuous PASS (the schema also requires min_pass_rate, so this is defence in
        # depth for a contract that reached the gate another way).
        reasons.append("tier2_quality declared without a min_pass_rate threshold")
    else:
        lower_bound = mean - stddev
        if lower_bound < min_pr - _EPS:
            reasons.append(f"pass-rate lower bound {lower_bound:.3f} < required {min_pr:.3f}")

    req_runs = want.get("runs")
    if req_runs is not None and n < req_runs:
        reasons.append(f"only {n} run(s); need >= {req_runs}")

    # Sessions that produced no measurement — the component never answered (undetermined) or the
    # grader never graded (ungraded) — are out of the pass-rate; above MAX_UNDETERMINED of them the
    # run fails on that alone, with the reason naming what happened (ADR 0093 applied to Tier-2).
    total, unmeasured = _unmeasured(ws)
    if total and unmeasured / total > MAX_UNDETERMINED:
        reasons.append(
            f"{unmeasured} of {total} sessions unmeasured (> {MAX_UNDETERMINED:.0%}): "
            f"{_unmeasured_breakdown(ws)} — the run failed, not the component"
        )

    delta = run_summary.get("delta") or {}
    max_tokens = want.get("max_overhead_tokens")
    if max_tokens is not None and "tokens" in delta and delta["tokens"] > max_tokens:
        reasons.append(f"token overhead {delta['tokens']} > max {max_tokens}")
    max_seconds = want.get("max_overhead_seconds")
    if max_seconds is not None and "time_seconds" in delta and delta["time_seconds"] > max_seconds:
        reasons.append(f"time overhead {delta['time_seconds']}s > max {max_seconds}s")
    # A-B lift: with the skill, the pass-rate must beat no-skill by at least min_lift (ADR 0036).
    # Skips when no baseline was run (no delta), so a normal single-pass run is unaffected.
    min_lift = want.get("min_lift")
    if min_lift is not None and "pass_rate" in delta and delta["pass_rate"] < min_lift - _EPS:
        reasons.append(f"A/B pass-rate lift {delta['pass_rate']:.3f} < required {min_lift:.3f}")

    return GateResult("tier2_quality", not reasons, reasons)


def version_regression(
    benchmark: dict[str, Any],
    prior: dict[str, Any] | None,
    thresholds: dict[str, Any],
) -> GateResult | None:
    """Version-over-version A/B (ADR 0047): FAIL if the current ``with_skill`` pass-rate mean
    dropped more than ``max_regression`` below a ``prior`` recorded run's mean (a stored benchmark
    history record). Returns ``None`` — skip — when there is no ``max_regression`` threshold or no
    ``prior``, so it is opt-in and engages only once a baseline exists (a first run can't regress
    against nothing). A distinct cross-run gate, separate from single-run :func:`tier2_quality`."""
    want = thresholds.get("tier2_quality") or {}
    max_reg = want.get("max_regression")
    if max_reg is None or prior is None:
        return None
    ws = (benchmark.get("run_summary") or {}).get("with_skill") or {}
    cur = (ws.get("pass_rate") or {}).get("mean")
    prior_mean = prior.get("mean")
    if cur is None or prior_mean is None:
        return GateResult("version_regression", False, ["missing current or prior mean"])
    reasons: list[str] = []
    drop = prior_mean - cur
    if drop > max_reg + _EPS:
        reasons.append(
            f"version regression: mean {cur:.3f} is {drop:.3f} below prior {prior_mean:.3f} "
            f"(max allowed {max_reg:.3f})"
        )
    return GateResult("version_regression", not reasons, reasons)


def _unmeasured(ws: dict[str, Any]) -> tuple[int, int]:
    """``(sessions attempted, sessions unmeasured)`` from a ``with_skill`` summary's ``sessions``
    block (absent for a stub transport that never fails: 0/0)."""
    sessions = ws.get("sessions") or {}
    total = int(sessions.get("total", 0) or 0)
    dead = int(sessions.get("undetermined", 0) or 0) + int(sessions.get("ungraded", 0) or 0)
    return total, dead


def _unmeasured_breakdown(ws: dict[str, Any]) -> str:
    """``2 undetermined [error_max_turns x2], 1 ungraded`` — the WHY beside the count."""
    sessions = ws.get("sessions") or {}
    parts: list[str] = []
    dead = int(sessions.get("undetermined", 0) or 0)
    if dead:
        subtypes = sessions.get("subtypes") or {}
        why = ", ".join(
            f"{k} x{v}" for k, v in sorted(subtypes.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        parts.append(f"{dead} undetermined" + (f" [{why}]" if why else ""))
    ungraded = int(sessions.get("ungraded", 0) or 0)
    if ungraded:
        parts.append(f"{ungraded} ungraded")
    return ", ".join(parts)


def format_tier2_summary(
    label: str, *, passed: bool, benchmark: dict[str, Any], reasons: list[str]
) -> str:
    """One-line Tier-2 result: ``<label>: PASS/FAIL (mean=…, stddev=…, lower_bound=…, n=…)``.

    Shared by the role and skill runners so the lower-bound formula lives in one place (here, next
    to :func:`tier2_quality`). Sessions that produced no measurement are printed ALWAYS, pass or
    fail — ``n=5; 1/15 sessions unmeasured: 1 undetermined [timeout x1]`` — because a green number
    computed from fewer sessions than were asked is weaker evidence, and hiding that is a silent
    cap (the same rule Tier-1 applies to no-decision calls, ADR 0084)."""
    ws = (benchmark.get("run_summary") or {}).get("with_skill") or {}
    pr = ws.get("pass_rate") or {}
    mean = pr.get("mean", 0.0)
    stddev = pr.get("stddev", 0.0)
    status = "PASS" if passed else "FAIL"
    detail = "" if passed else " — " + "; ".join(reasons)
    total, unmeasured = _unmeasured(ws)
    noise = (
        f"; {unmeasured}/{total} sessions unmeasured: {_unmeasured_breakdown(ws)}"
        if unmeasured
        else ""
    )
    return (
        f"{label}: {status} "
        f"(mean={mean:.3f}, stddev={stddev:.3f}, lower_bound={mean - stddev:.3f}, "
        f"n={ws.get('n', 0)}{noise}){detail}"
    )


def tier2_evidence_lines(benchmark: dict[str, Any]) -> list[str]:
    """What the summary line cannot fit: one line per session that produced no measurement (which
    run and case, the CLI's ``subtype`` and ``num_turns``), then the assertions that actually
    failed, worst first. Both exist so a log can be diagnosed without paying for the run again —
    ADR 0084's rule for discarded calls, applied to the tier that costs the most to repeat."""
    ws = (benchmark.get("run_summary") or {}).get("with_skill") or {}
    events = (ws.get("sessions") or {}).get("events") or []
    lines: list[str] = []
    for ev in events:
        turns = f", num_turns={ev['num_turns']}" if ev.get("num_turns") is not None else ""
        text = f": {ev['text']}" if ev.get("text") else ""
        lines.append(
            f"    unmeasured: run {ev.get('run')} case {ev.get('case')} "
            f"{ev.get('kind')} ({ev.get('subtype')}{turns}){text}"
        )
    for row in ws.get("failed_assertions") or []:
        claim = " ".join(str(row.get("text", "")).split())[:120]
        lines.append(f"    failed {row.get('failed')}/{row.get('total')}: {claim}")
    sample = (ws.get("sessions") or {}).get("failed_sample")
    if isinstance(sample, dict) and sample.get("text"):
        lines.append(
            f"    sample (run {sample.get('run')} case {sample.get('case')} said): "
            f"{sample['text']}"
        )
    return lines


def evaluate(
    evals_json: dict[str, Any],
    *,
    benchmark: dict[str, Any] | None = None,
    trigger_measured: dict[str, float | None] | None = None,
) -> list[GateResult]:
    """Run every applicable tier for a component and return one GateResult per tier."""
    thresholds = evals_json.get("thresholds") or {}
    results: list[GateResult] = []
    if "tier1_trigger" in thresholds and trigger_measured is not None:
        results.append(tier1_trigger(trigger_measured, thresholds))
    if "tier2_quality" in thresholds and benchmark is not None:
        results.append(tier2_quality(benchmark, thresholds))
    return results


class _Passable(Protocol):
    @property
    def passed(self) -> bool: ...


def all_passed(results: Sequence[_Passable]) -> bool:
    # An empty result list means nothing was measured — that is NOT a pass; guards callers that gate
    # on evaluate() with no data. Generic over any result carrying `.passed` (GateResult /
    # Tier1Report / PhaseResult) so the runners share ONE definition instead of three copies.
    return bool(results) and all(r.passed for r in results)
