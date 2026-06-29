"""Shared helpers for the dev/ eval-runner CLIs (run_agent/skill/tier1_evals)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol

from agentic_forge import agent_eval, benchmark, diagnostics, gate

_API_KEY_WARNING = (
    "warning: ANTHROPIC_API_KEY is set; the claude CLI uses it before the subscription token. "
    "Unset it to bill this run to your Claude subscription."
)


def warn_if_api_key_set(runner: str) -> None:
    """Warn on stderr when the ``claude`` runner is chosen but ``ANTHROPIC_API_KEY`` is set — it
    takes precedence over the subscription token, so the run would bill per token."""
    if runner == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        print(_API_KEY_WARNING, file=sys.stderr)


def build_runners(
    runner: str, *, allowed_tools: str, model: str
) -> tuple[agent_eval.Runner, agent_eval.Runner]:
    """Build (component_runner, grader_runner) for the chosen transport — the one construction
    site shared by the agent and skill Tier-2 CLIs. `claude` keeps the component run and the
    grading on the `claude` CLI (subscription auth, no API key), giving the grader read-only tools
    and a generous turn cap so it can verify on-disk artifacts (level-2) without ever modifying
    them; `api` uses the Anthropic Messages SDK for both (per-token billing). The caller resolves
    `allowed_tools` (a role's or skill's tools) before delegating here."""
    if runner == "api":
        api = agent_eval.api_runner(model)
        return api, api
    if runner == "claude":
        component_fn = agent_eval.claude_cli_runner(
            allowed_tools=allowed_tools, model=model, max_turns=40
        )
        grader_fn = agent_eval.claude_cli_runner(
            allowed_tools="Read,Grep,Glob", model=model, max_turns=20
        )
        return component_fn, grader_fn
    raise ValueError(f"unknown runner {runner!r}")


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
