"""Aggregate eval run results into benchmark statistics.

skill-creator (the LLM-driven engine) produces one grading.json per run with a
`summary.pass_rate`. This module turns a set of those into the aggregate shape used
by the official benchmark.json (run_summary -> with_skill / without_skill / delta),
so the deterministic threshold gate can consume it.
"""

from __future__ import annotations

import statistics
from typing import Any


def pass_rate_of(grading: dict[str, Any]) -> float:
    """Extract a 0..1 pass rate from a single grading.json mapping."""
    summary = grading.get("summary") or {}
    if "pass_rate" in summary:
        return float(summary["pass_rate"])
    total = summary.get("total")
    passed = summary.get("passed")
    if total:
        return float(passed or 0) / float(total)
    # Fall back to the assertion_results list.
    results = grading.get("assertion_results") or []
    if not results:
        return 0.0
    hits = sum(1 for r in results if r.get("passed"))
    return hits / len(results)


def _stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "n": 0}
    mean = statistics.fmean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"mean": mean, "stddev": stddev, "n": len(values)}


def summarize(
    with_skill: list[dict[str, Any]],
    without_skill: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a benchmark.json-shaped mapping from grading.json lists."""
    ws = _stats([pass_rate_of(g) for g in with_skill])
    run_summary: dict[str, Any] = {
        "with_skill": {
            "pass_rate": {"mean": ws["mean"], "stddev": ws["stddev"]},
            "n": ws["n"],
        }
    }
    if without_skill is not None:
        wo = _stats([pass_rate_of(g) for g in without_skill])
        run_summary["without_skill"] = {
            "pass_rate": {"mean": wo["mean"], "stddev": wo["stddev"]},
            "n": wo["n"],
        }
        run_summary["delta"] = {"pass_rate": ws["mean"] - wo["mean"]}
    return {"run_summary": run_summary}
