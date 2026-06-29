"""Shared helpers for the dev/ eval-runner CLIs (run_agent/skill/tier1_evals)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol

from agentic_forge import benchmark, diagnostics, gate

_API_KEY_WARNING = (
    "warning: ANTHROPIC_API_KEY is set; the claude CLI uses it before the subscription token. "
    "Unset it to bill this run to your Claude subscription."
)


def warn_if_api_key_set(runner: str) -> None:
    """Warn on stderr when the ``claude`` runner is chosen but ``ANTHROPIC_API_KEY`` is set — it
    takes precedence over the subscription token, so the run would bill per token."""
    if runner == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        print(_API_KEY_WARNING, file=sys.stderr)


def record_failure(
    component: str, message: str, *, kind: str = "error", severity: str = "major"
) -> None:
    """Emit a pipeline diagnostic for a runner crash (``error``) or a gate FAIL (``anomaly``) —
    opt-in (``AGENTIC_FORGE_DIAGNOSTICS``), non-blocking, written to ``./.agentic-forge/`` (ADR
    0039). A no-op when capture is off, so normal runs are unaffected."""
    diagnostics.emit(".", kind=kind, component=component, message=message, severity=severity)


class _Report(Protocol):
    benchmark: dict[str, Any]
    thresholds: dict[str, Any]

    @property
    def passed(self) -> bool: ...


def version_check(
    report: _Report,
    *,
    component: str,
    model: str,
    history_path: str | Path,
    record: bool,
) -> gate.GateResult | None:
    """Version-over-version A/B (ADR 0047): compare ``report`` against the latest same-model record
    in the benchmark history and, if ``record``, append this run — but only when it is **healthy**
    (it passed ``tier2_quality`` *and* did not regress), so a failing/regressed run never poisons
    the baseline. Returns the regression :class:`gate.GateResult`, or ``None`` when there is no
    prior / no ``max_regression`` threshold (the check is opt-in)."""
    history = benchmark.load_history(history_path)
    prior = benchmark.prior_record(history, component, model)
    result = gate.version_regression(report.benchmark, prior, report.thresholds)
    healthy = report.passed and (result is None or result.passed)
    if record and healthy:
        history.append(benchmark.make_record(component, model, report.benchmark))
        benchmark.save_history(history_path, history)
    return result
