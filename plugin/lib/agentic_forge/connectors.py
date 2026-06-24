"""Real provider connectors — concrete implementations of the ``ops.py`` seams (ADR 0025).

Phase 1: :class:`GhPipelineSource` — GitHub Actions workflow runs (``gh run list --json``) as a
:class:`~agentic_forge.ops.PipelineSource`. The parsing (:func:`parse_gh_runs`) is pure and fully
tested against fixture ``gh`` JSON; the ``gh`` call (:func:`_gh_run_list`) is a thin seam
(``# pragma: no cover``). :func:`pipeline_source` auto-detects ``gh`` on PATH and otherwise falls
back to an empty in-memory source, so callers degrade gracefully. See
docs/architecture/connectors.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .ops import (
    Alert,
    AlertSource,
    Deploy,
    InMemoryAlerts,
    InMemoryPipeline,
    PipelineSource,
)

__all__ = [
    "parse_gh_runs",
    "GhPipelineSource",
    "gh_available",
    "pipeline_source",
    "parse_grafana_alerts",
    "GrafanaAlertSource",
    "alert_source",
]

# A completed run's ``conclusion`` -> Deploy.status. Only success and the failure family are
# decisive for rollout health; other conclusions (cancelled/skipped/neutral) are *not* failures.
_CONCLUSION: dict[str, str] = {
    "success": "passing",
    "failure": "failing",
    "timed_out": "failing",
    "startup_failure": "failing",
}
# An in-flight run's ``status`` -> Deploy.status.
_INFLIGHT: dict[str, str] = {
    "queued": "queued",
    "requested": "queued",
    "waiting": "queued",
    "pending": "queued",
    "in_progress": "running",
}


def _run_status(run: dict[str, Any]) -> str:
    """Map a GitHub Actions run's status/conclusion onto Deploy's vocabulary."""
    status = str(run.get("status", ""))
    if status == "completed":
        return _CONCLUSION.get(str(run.get("conclusion", "")), "passing")
    return _INFLIGHT.get(status, "running")


def parse_gh_runs(payload: str, environment: str) -> list[Deploy]:
    """Parse ``gh run list --json ...`` output into Deploys (newest first, as ``gh`` returns).

    Pure and tolerant: invalid JSON or a non-list yields ``[]``; non-dict entries are skipped. The
    status maps GitHub's status/conclusion onto Deploy's vocabulary
    (``passing`` / ``failing`` / ``running`` / ``queued``).
    """
    try:
        runs = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(runs, list):
        return []
    out: list[Deploy] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        out.append(
            Deploy(
                sha=str(run.get("headSha", ""))[:7],
                status=_run_status(run),
                environment=environment,
                at=str(run.get("createdAt", "")),
            )
        )
    return out


def _gh_run_list(repo: str, limit: int) -> str:  # pragma: no cover
    """Fetch recent workflow runs as JSON via the ``gh`` CLI (thin seam)."""
    result = subprocess.run(
        [
            "gh", "run", "list", "--repo", repo, "--limit", str(limit),
            "--json", "headSha,status,conclusion,createdAt,workflowName",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@dataclass
class GhPipelineSource:
    """A :class:`~agentic_forge.ops.PipelineSource` over GitHub Actions runs (the ``gh`` CLI).

    ``repo`` is the GitHub ``owner/name``. GitHub runs aren't environment-tagged by default, so
    ``environment`` is carried onto the Deploys for the report; the assessment uses the latest run.
    """

    repo: str
    limit: int = 20

    def recent_deploys(self, environment: str) -> list[Deploy]:
        try:
            payload = _gh_run_list(self.repo, self.limit)
        except (subprocess.SubprocessError, OSError):
            return []  # fetch failed -> degrade to "no data", never raise into the assessment
        return parse_gh_runs(payload, environment)


def gh_available() -> bool:  # pragma: no cover
    """True if the ``gh`` CLI is on PATH."""
    return shutil.which("gh") is not None


def pipeline_source(repo: str, *, available: Callable[[], bool] = gh_available) -> PipelineSource:
    """Select a PipelineSource: :class:`GhPipelineSource` when ``gh`` is available, else an empty
    in-memory source (graceful fallback). ``available`` is injectable for testing."""
    if available():
        return GhPipelineSource(repo)
    return InMemoryPipeline({})


# --- Grafana alerts (AlertSource) --------------------------------------------
# MCP-first by policy (ADR 0025): the skills prefer the Grafana MCP tool when present; this REST
# adapter is the deterministic fallback and the tested core.

# Grafana alert ``severity`` label -> ops alert severity. An unknown *firing* alert defaults to
# ``warning`` (degraded) — never silently dropped.
_GRAFANA_SEVERITY: dict[str, str] = {
    "critical": "critical",
    "crit": "critical",
    "page": "critical",
    "warning": "warning",
    "warn": "warning",
    "high": "warning",
    "info": "info",
    "information": "info",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_grafana_alerts(payload: str, environment: str) -> list[Alert]:
    """Parse Grafana Alertmanager-style alert JSON into Alerts (pure, tolerant).

    Reads the array from ``GET /api/alertmanager/grafana/api/v2/alerts``: each alert's
    ``labels.severity`` maps onto ops severities and ``annotations.summary`` (or the alert name) is
    the summary. Skips non-active alerts and alerts whose ``environment``/``env`` label doesn't
    match ``environment`` (alerts lacking that label are kept — they can't be filtered). Invalid
    JSON or a non-list yields ``[]``.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[Alert] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if _as_dict(item.get("status")).get("state") not in (None, "active"):
            continue  # resolved / suppressed
        labels = _as_dict(item.get("labels"))
        env = labels.get("environment") or labels.get("env")
        if env and str(env) != environment:
            continue
        severity = _GRAFANA_SEVERITY.get(str(labels.get("severity", "")).lower(), "warning")
        summary = (
            _as_dict(item.get("annotations")).get("summary")
            or labels.get("alertname")
            or "alert"
        )
        out.append(Alert(severity=severity, summary=str(summary), source="grafana"))
    return out


def _grafana_alerts(base_url: str, token: str) -> str:  # pragma: no cover
    """Fetch active alerts from Grafana's Alertmanager-compatible endpoint (thin seam)."""
    import urllib.request

    url = base_url.rstrip("/") + "/api/alertmanager/grafana/api/v2/alerts"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return str(resp.read().decode("utf-8"))


@dataclass
class GrafanaAlertSource:
    """An :class:`~agentic_forge.ops.AlertSource` over Grafana alerting (REST; the MCP server is the
    preferred path per ADR 0025). ``base_url`` is the Grafana root; ``token`` an API token from
    env/config — never committed."""

    base_url: str
    token: str = ""

    def active_alerts(self, environment: str) -> list[Alert]:
        try:
            payload = _grafana_alerts(self.base_url, self.token)
        except OSError:
            return []  # fetch failed -> no data, never raise into the assessment
        return parse_grafana_alerts(payload, environment)


def alert_source(*, env: Callable[[str], str | None] = os.environ.get) -> AlertSource:
    """Select an AlertSource: :class:`GrafanaAlertSource` when ``GRAFANA_URL`` is set, else an empty
    in-memory source (graceful fallback). ``env`` is injectable for testing."""
    url = env("GRAFANA_URL")
    if url:
        return GrafanaAlertSource(url, env("GRAFANA_TOKEN") or "")
    return InMemoryAlerts({})
