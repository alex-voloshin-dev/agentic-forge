"""Aggregate eval run results into benchmark statistics.

skill-creator (the LLM-driven engine) produces one grading.json per run with a
`summary.pass_rate`. This module turns a set of those into the aggregate shape used
by the official benchmark.json (run_summary -> with_skill / without_skill / delta),
so the deterministic threshold gate can consume it.
"""

from __future__ import annotations

import statistics
from typing import Any

__all__ = ["pass_rate_of", "summarize"]


def pass_rate_of(grading: dict[str, Any]) -> float:
    """Extract a 0..1 pass rate from a single grading.json mapping."""
    summary = grading.get("summary") or {}
    rate = summary.get("pass_rate")
    if rate is not None:  # tolerate a null pass_rate (don't crash on float(None))
        return float(rate)
    total = summary.get("total")
    if total is not None:  # an explicit total (incl. 0) is authoritative
        passed = summary.get("passed") or 0
        return (float(passed) / float(total)) if total else 0.0
    # Fall back to the assertion_results list.
    results = grading.get("assertion_results") or []
    if not results:
        return 0.0
    hits = sum(1 for r in results if r.get("passed") is True)
    return hits / len(results)


def _stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "n": 0}
    mean = statistics.fmean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"mean": mean, "stddev": stddev, "n": len(values)}


def _mean_tokens(timing: list[dict[str, Any]]) -> float:
    values = [float(t.get("total_tokens", 0)) for t in timing]
    return statistics.fmean(values) if values else 0.0


def _mean_seconds(timing: list[dict[str, Any]]) -> float:
    values = [float(t.get("duration_ms", 0)) / 1000.0 for t in timing]
    return statistics.fmean(values) if values else 0.0


def summarize(
    with_skill: list[dict[str, Any]],
    without_skill: list[dict[str, Any]] | None = None,
    *,
    with_skill_timing: list[dict[str, Any]] | None = None,
    without_skill_timing: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a benchmark.json-shaped mapping from grading.json (and optional timing.json) lists.

    Pass `*_timing` lists of `{total_tokens, duration_ms}` to populate token/time means and
    the with-vs-without overhead delta that `gate.tier2_quality` checks.
    """
    ws = _stats([pass_rate_of(g) for g in with_skill])
    ws_summary: dict[str, Any] = {
        "pass_rate": {"mean": ws["mean"], "stddev": ws["stddev"]},
        "n": ws["n"],
    }
    if with_skill_timing is not None:
        ws_summary["tokens"] = _mean_tokens(with_skill_timing)
        ws_summary["time_seconds"] = _mean_seconds(with_skill_timing)

    run_summary: dict[str, Any] = {"with_skill": ws_summary}

    if without_skill is not None:
        wo = _stats([pass_rate_of(g) for g in without_skill])
        wo_summary: dict[str, Any] = {
            "pass_rate": {"mean": wo["mean"], "stddev": wo["stddev"]},
            "n": wo["n"],
        }
        delta: dict[str, float] = {"pass_rate": ws["mean"] - wo["mean"]}
        if without_skill_timing is not None:
            wo_summary["tokens"] = _mean_tokens(without_skill_timing)
            wo_summary["time_seconds"] = _mean_seconds(without_skill_timing)
        if with_skill_timing is not None and without_skill_timing is not None:
            delta["tokens"] = ws_summary["tokens"] - wo_summary["tokens"]
            delta["time_seconds"] = ws_summary["time_seconds"] - wo_summary["time_seconds"]
        run_summary["without_skill"] = wo_summary
        run_summary["delta"] = delta

    return {"run_summary": run_summary}
