"""Aggregate eval run results into benchmark statistics.

skill-creator (the LLM-driven engine) produces one grading.json per run with a
`summary.pass_rate`. This module turns a set of those into the aggregate shape used
by the official benchmark.json (run_summary -> with_skill / without_skill / delta),
so the deterministic threshold gate can consume it.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

__all__ = [
    "pass_rate_of",
    "summarize",
    "make_record",
    "prior_record",
    "load_history",
    "save_history",
]


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
    passed, failed = summary.get("passed"), summary.get("failed")
    if passed is not None and failed is not None:  # {passed, failed} with no explicit total
        denom = float(passed) + float(failed)
        return float(passed) / denom if denom else 0.0
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


def _has_tokens(timing: list[dict[str, Any]]) -> bool:
    """True if any timing entry carries a token count. A transport that reports usage (a
    ``RunOutput`` — ADR 0038) populates ``total_tokens``; a text-only reply omits it, so token
    means/deltas are suppressed rather than reported as a misleading 0.0 (ADR 0036)."""
    return any("total_tokens" in t for t in timing)


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

    Pass `*_timing` lists of `{duration_ms}` (with an optional `total_tokens`) to populate the
    time/token means and the with-vs-without overhead delta that `gate.tier2_quality` checks.
    ``tokens`` is reported only when a count is present — transports that report usage supply it
    (ADR 0038); a text-only reply omits it (ADR 0036).
    """
    ws = _stats([pass_rate_of(g) for g in with_skill])
    ws_summary: dict[str, Any] = {
        "pass_rate": {"mean": ws["mean"], "stddev": ws["stddev"]},
        "n": ws["n"],
    }
    if with_skill_timing is not None:
        ws_summary["time_seconds"] = _mean_seconds(with_skill_timing)
        if _has_tokens(with_skill_timing):
            ws_summary["tokens"] = _mean_tokens(with_skill_timing)

    run_summary: dict[str, Any] = {"with_skill": ws_summary}

    if without_skill is not None:
        wo = _stats([pass_rate_of(g) for g in without_skill])
        wo_summary: dict[str, Any] = {
            "pass_rate": {"mean": wo["mean"], "stddev": wo["stddev"]},
            "n": wo["n"],
        }
        delta: dict[str, float] = {"pass_rate": ws["mean"] - wo["mean"]}
        if without_skill_timing is not None:
            wo_summary["time_seconds"] = _mean_seconds(without_skill_timing)
            if _has_tokens(without_skill_timing):
                wo_summary["tokens"] = _mean_tokens(without_skill_timing)
        if with_skill_timing is not None and without_skill_timing is not None:
            delta["time_seconds"] = ws_summary["time_seconds"] - wo_summary["time_seconds"]
            if "tokens" in ws_summary and "tokens" in wo_summary:
                delta["tokens"] = ws_summary["tokens"] - wo_summary["tokens"]
        run_summary["without_skill"] = wo_summary
        run_summary["delta"] = delta

    return {"run_summary": run_summary}


# --- version-over-version benchmark history (ADR 0047) ------------------------
# An append-only list of {component, model, mean, stddev, n}. Keyed by (component, model) because
# Tier-2 is model-dependent — a regression check only compares same-model runs.


def make_record(component: str, model: str, benchmark: dict[str, Any]) -> dict[str, Any]:
    """A history record extracted from a benchmark mapping (the `with_skill` pass-rate stats)."""
    ws = (benchmark.get("run_summary") or {}).get("with_skill") or {}
    pr = ws.get("pass_rate") or {}
    return {
        "component": component,
        "model": model,
        "mean": float(pr.get("mean", 0.0)),
        "stddev": float(pr.get("stddev", 0.0)),
        "n": int(ws.get("n", 0)),
    }


def prior_record(
    history: list[dict[str, Any]], component: str, model: str
) -> dict[str, Any] | None:
    """The most recent record for ``(component, model)`` (the prior version's baseline), or None."""
    for record in reversed(history):
        if record.get("component") == component and record.get("model") == model:
            return record
    return None


def load_history(path: str | Path) -> list[dict[str, Any]]:
    """Load the benchmark history list (``[]`` if absent or unreadable — a fresh baseline)."""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_history(path: str | Path, history: list[dict[str, Any]]) -> None:
    """Persist the benchmark history (creating the parent dir)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(history, indent=2), encoding="utf-8")
