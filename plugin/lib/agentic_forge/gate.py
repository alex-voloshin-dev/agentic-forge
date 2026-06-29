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
    "trigger_metrics",
    "tier1_trigger",
    "tier2_quality",
    "format_tier2_summary",
    "evaluate",
    "all_passed",
]

# Float-comparison tolerance: a metric exactly at its threshold must not FAIL due to binary-float
# representation (e.g. 0.85 - 0.05 == 0.7999999999999999, not 0.8).
_EPS = 1e-9


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


def format_tier2_summary(
    label: str, *, passed: bool, benchmark: dict[str, Any], reasons: list[str]
) -> str:
    """One-line Tier-2 result: ``<label>: PASS/FAIL (mean=…, stddev=…, lower_bound=…, n=…)``.

    Shared by the role and skill runners so the lower-bound formula lives in one place (here, next
    to :func:`tier2_quality`)."""
    ws = (benchmark.get("run_summary") or {}).get("with_skill") or {}
    pr = ws.get("pass_rate") or {}
    mean = pr.get("mean", 0.0)
    stddev = pr.get("stddev", 0.0)
    status = "PASS" if passed else "FAIL"
    detail = "" if passed else " — " + "; ".join(reasons)
    return (
        f"{label}: {status} "
        f"(mean={mean:.3f}, stddev={stddev:.3f}, lower_bound={mean - stddev:.3f}, "
        f"n={ws.get('n', 0)}){detail}"
    )


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
