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
    "passed_value",
    "pass_rate_of",
    "summarize",
    "make_record",
    "prior_record",
    "SETUP_FIELDS",
    "run_setup",
    "ab_counterpart",
    "load_history",
    "save_history",
]


def passed_value(value: object) -> bool:
    """Whether a grader's ``passed`` field says the assertion held. ``True`` — and the spellings a
    model reaches for when it ignores the JSON instruction: ``"true"``, ``"pass"``, ``"passed"``
    (case-insensitive). Anything else, ``"false"`` included, is a fail: a grader must never inflate
    a score by being sloppy, and ``"PASS"`` used to be scored as a fail for the same sloppiness
    (eval audit, C5)."""
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in ("true", "pass", "passed")


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
    hits = sum(1 for r in results if passed_value(r.get("passed")))
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


def _mean_of(rows: list[dict[str, Any]], key: str) -> float | None:
    """Mean of ``key`` over the rows that report it, or None when none does (not a fake 0.0)."""
    values = [float(r[key]) for r in rows if key in r]
    return statistics.fmean(values) if values else None


def _add_usage_means(summary: dict[str, Any], sessions: dict[str, Any]) -> None:
    """Per run, from the runner's ``sessions["spend"]`` (every run with an answered role session,
    graded or not): ``answered_sessions``, and ``prompt_tokens`` (cached input included) and
    ``cost_usd`` when reported. They show what a CLAUDE.md costs, which ``tokens`` cannot: the file
    sits in the cached prompt prefix and the CLI's ``input_tokens`` leaves that out (ADR 0113,
    amended)."""
    spend = sessions.get("spend") or []
    for key, out in (("answered", "answered_sessions"), ("prompt_tokens", "prompt_tokens"),
                     ("cost_usd", "cost_usd")):
        mean = _mean_of(spend, key)
        if mean is not None:
            summary[out] = mean


def _mean_seconds(timing: list[dict[str, Any]]) -> float:
    values = [float(t.get("duration_ms", 0)) / 1000.0 for t in timing]
    return statistics.fmean(values) if values else 0.0


# How many failing assertions the benchmark keeps. Enough to see the pattern, not the whole
# grading: the point is to say WHICH assertion to look at without paying for another run.
MAX_FAILED_ASSERTIONS = 5


def failed_assertions(gradings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assertions that failed at least once, worst first: ``{text, failed, total}``.

    A Tier-2 FAIL used to print a pass-rate and nothing else, so finding out *which* assertion
    slipped cost a second paid run — the rule ADR 0084 set for discarded router calls ("every
    discarded call is reported, pass or fail") applied to the tier that costs the most to repeat.
    """
    tally: dict[str, list[int]] = {}
    for grading in gradings:
        for result in grading.get("assertion_results") or []:
            if not isinstance(result, dict):
                continue
            text = str(result.get("text") or "").strip()
            if not text:
                continue
            counts = tally.setdefault(text, [0, 0])
            counts[1] += 1
            if not passed_value(result.get("passed")):
                counts[0] += 1
    worst = [(failed, text, total) for text, (failed, total) in tally.items() if failed]
    worst.sort(key=lambda row: (-row[0], row[1]))
    return [
        {"text": text, "failed": failed, "total": total}
        for failed, text, total in worst[:MAX_FAILED_ASSERTIONS]
    ]


def summarize(
    with_skill: list[dict[str, Any]],
    without_skill: list[dict[str, Any]] | None = None,
    *,
    with_skill_timing: list[dict[str, Any]] | None = None,
    without_skill_timing: list[dict[str, Any]] | None = None,
    with_skill_sessions: dict[str, Any] | None = None,
    without_skill_sessions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a benchmark.json-shaped mapping from grading.json (and optional timing.json) lists.

    Pass `*_timing` lists of `{duration_ms}` (with an optional `total_tokens`) to populate the
    time/token means and the with-vs-without overhead delta that `gate.tier2_quality` checks.
    ``tokens`` is reported only when a count is present — transports that report usage supply it
    (ADR 0038); a text-only reply omits it (ADR 0036). ``*_sessions`` is the runner's tally of
    sessions that produced no measurement (``{total, undetermined, ungraded, subtypes, events}``,
    see ``agent_eval._run_passes``); it rides along under ``sessions`` so the gate can cap it and
    the summary line can print it, and its ``spend`` gives the per-run ``answered_sessions``,
    ``prompt_tokens`` and ``cost_usd`` means.
    """
    ws = _stats([pass_rate_of(g) for g in with_skill])
    ws_summary: dict[str, Any] = {
        "pass_rate": {"mean": ws["mean"], "stddev": ws["stddev"]},
        "n": ws["n"],
    }
    failed = failed_assertions(with_skill)
    if failed:
        ws_summary["failed_assertions"] = failed
    if with_skill_timing is not None:
        ws_summary["time_seconds"] = _mean_seconds(with_skill_timing)
        if _has_tokens(with_skill_timing):
            ws_summary["tokens"] = _mean_tokens(with_skill_timing)
    if with_skill_sessions is not None:
        ws_summary["sessions"] = with_skill_sessions
        _add_usage_means(ws_summary, with_skill_sessions)

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
        if without_skill_sessions is not None:
            wo_summary["sessions"] = without_skill_sessions
            _add_usage_means(wo_summary, without_skill_sessions)
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

# What a run was set up with beyond (component, model, judge): whether the role and the judge
# loaded CLAUDE.md, which workspace file they were given (ADR 0113, amended), and the transport. A
# record without them predates `run_agent_evals` recording them: both sessions could load CLAUDE.md,
# no file was placed, the runner went unrecorded — that is what their absence means. The skill
# runner records none of them, so its records keep comparing as before.
SETUP_FIELDS: dict[str, str | None] = {
    "omit_claude_md": "off",
    "grader_omit_claude_md": "off",
    "claude_md": None,
    "runner": None,
}
# Recorded beside the setup but not part of it: the `claude --version` that ran the sessions (an
# A/B's two arms must share it — :func:`ab_counterpart`; a release baseline need not, or every CLI
# update would reset it), and the per-run prompt tokens and cost an A/B reads its saving from.
_RECORDED_EXTRAS = ("claude_version",)
_RECORDED_USAGE = ("prompt_tokens", "cost_usd", "answered_sessions")


def run_setup(mapping: dict[str, Any]) -> dict[str, Any]:
    """The setup of a benchmark or a history record, absent fields read as legacy."""
    return {key: mapping.get(key, legacy) for key, legacy in SETUP_FIELDS.items()}


def make_record(component: str, model: str, benchmark: dict[str, Any]) -> dict[str, Any]:
    """A history record extracted from a benchmark mapping (the `with_skill` pass-rate stats).

    It names the judge (``grader_model``) when the benchmark does (ADR 0114): a record graded by
    another model is another instrument, and :func:`prior_record` keeps the two apart. It keeps the
    setup (:data:`SETUP_FIELDS`) for the same reason, and the ``claude_version`` and per-run
    ``prompt_tokens`` / ``cost_usd`` an ``omitClaudeMd`` A/B compares (:func:`ab_counterpart`)."""
    ws = (benchmark.get("run_summary") or {}).get("with_skill") or {}
    pr = ws.get("pass_rate") or {}
    record: dict[str, Any] = {
        "component": component,
        "model": model,
        "mean": float(pr.get("mean", 0.0)),
        "stddev": float(pr.get("stddev", 0.0)),
        "n": int(ws.get("n", 0)),
    }
    if benchmark.get("grader_model"):
        record["grader_model"] = str(benchmark["grader_model"])
    for key in (*SETUP_FIELDS, *_RECORDED_EXTRAS):  # what produced it (ADR 0113, amended)
        if benchmark.get(key) is not None:
            record[key] = str(benchmark[key])
    for key in _RECORDED_USAGE:
        if key in ws:
            record[key] = float(ws[key])
    return record


def judge_of(record: dict[str, Any]) -> Any:
    """The model that graded ``record``. A record from before ADR 0114 names none: the runners then
    graded on the component's own model, so its ``model`` was its judge."""
    return record.get("grader_model") or record.get("model")


def prior_record(
    history: list[dict[str, Any]],
    component: str,
    model: str,
    *,
    grader_model: str | None = None,
    setup: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The most recent record for ``(component, model)`` (the prior version's baseline), or None.

    With ``grader_model``, only a record graded by that same judge counts (ADR 0114); a legacy
    record's judge is its own ``model`` (:func:`judge_of`). With ``setup`` (a :func:`run_setup`),
    only a record made with that same setup counts."""
    record: dict[str, Any]
    for record in reversed(history):
        if record.get("component") != component or record.get("model") != model:
            continue
        if grader_model is not None and judge_of(record) != grader_model:
            continue
        if setup is None or run_setup(record) == setup:
            return record
    return None


def ab_counterpart(
    history: list[dict[str, Any]],
    component: str,
    model: str,
    *,
    grader_model: str | None,
    setup: dict[str, Any],
    claude_version: str | None,
    fingerprint: str | None,
) -> dict[str, Any] | None:
    """The latest record of the OTHER arm of an ``omitClaudeMd`` A/B: same component, model, judge,
    workspace file, runner, ``claude --version`` and input ``fingerprint`` (role, judge, contract,
    fixtures and file — ``agent_eval.input_fingerprint``), opposite ``omit_claude_md``; or None.
    Arms on another CLI or other inputs are never paired: only the switch may differ."""
    flipped = {**setup, "omit_claude_md": "off" if setup.get("omit_claude_md") == "on" else "on"}
    record: dict[str, Any]
    for record in reversed(history):
        if record.get("component") != component or record.get("model") != model:
            continue
        if grader_model is not None and judge_of(record) != grader_model:
            continue
        if run_setup(record) != flipped or record.get("claude_version") != claude_version:
            continue
        if fingerprint is not None and record.get("fingerprint") == fingerprint:
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
