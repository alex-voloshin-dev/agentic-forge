"""Real provider connectors — concrete implementations of the ``ops.py`` seams (ADR 0025).

Two seams are backed by a real provider:

- :class:`GhPipelineSource` — GitHub Actions workflow runs (``gh run list --json``) as a
  :class:`~agentic_forge.ops.PipelineSource` (parser :func:`parse_gh_runs`, factory
  :func:`pipeline_source`).
- :class:`GrafanaAlertSource` — Grafana alert rules as an :class:`~agentic_forge.ops.AlertSource`
  (parser :func:`parse_grafana_alerts`, factory :func:`alert_source`).

Each follows the same shape: the parsing is pure and fully tested against fixture JSON; the live
call (:func:`_gh_run_list` / the Grafana fetch) is a thin seam (``# pragma: no cover``); and the
factory auto-detects the provider and otherwise falls back to an empty in-memory source, so callers
degrade gracefully when nothing is configured. A *configured* source that cannot answer — the
fetch failed or timed out, or the body is not its JSON (a login page, a rate-limit error) — raises
:class:`~agentic_forge.ops.SourceUnavailable` rather than degrading to ``[]``: zero data from a
failed fetch must not be read as zero problems. See docs/architecture/connectors.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ops import (
    Alert,
    AlertSource,
    Deploy,
    InMemoryAlerts,
    InMemoryPipeline,
    PipelineSource,
    SourceUnavailable,
    UnavailablePipeline,
)

__all__ = [
    "parse_gh_runs",
    "GhPipelineSource",
    "gh_available",
    "slug_from_remote_url",
    "remote_slug",
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


def _json_list(payload: str, what: str) -> list[Any]:
    """The JSON array in ``payload``, or :class:`SourceUnavailable` naming ``what`` answered with
    something else — a login page, an error object, an empty body. The tolerant public parsers
    return ``[]`` for the same input; a live source must not, because there "nothing" would be
    read as "no runs / no alerts"."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        head = " ".join(str(payload).split())[:80] or "<empty>"
        raise SourceUnavailable(f"{what} returned non-JSON output: {head!r}") from exc
    if not isinstance(data, list):
        raise SourceUnavailable(f"{what} returned {type(data).__name__}, not a list")
    return data


def _deploys_from(runs: list[Any], environment: str) -> list[Deploy]:
    """Deploys from decoded ``gh run list`` entries (non-dict entries skipped)."""
    out: list[Deploy] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        out.append(
            Deploy(
                sha=str(run.get("headSha") or "")[:7],  # `or ""` so an explicit JSON null -> ""
                status=_run_status(run),
                environment=environment,
                at=str(run.get("createdAt") or ""),
            )
        )
    return out


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
    return _deploys_from(runs, environment)


# How long one `gh run list` may take. It runs on the daily deploy-digest path of the scheduled
# runner: unbounded, a stalled `gh` (a hung network call, an interactive auth prompt) blocked the
# whole scheduled run and its state was never saved.
GH_TIMEOUT_SECONDS = 60


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
        timeout=GH_TIMEOUT_SECONDS,
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
        """The recent runs, or :class:`SourceUnavailable` when ``gh`` could not answer (exited
        non-zero — rate-limited, unauthenticated —, timed out, is missing, or returned non-JSON).
        This used to degrade to ``[]``, which the assessment read as *healthy*."""
        try:
            payload = _gh_run_list(self.repo, self.limit)
        except subprocess.TimeoutExpired as exc:
            raise SourceUnavailable(f"gh run list timed out after {exc.timeout:.0f}s") from exc
        except subprocess.CalledProcessError as exc:
            err = " ".join(str(exc.stderr or "").split())[-160:]
            raise SourceUnavailable(
                f"gh run list exited {exc.returncode}" + (f": {err}" if err else "")
            ) from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise SourceUnavailable(f"gh run list failed: {exc}") from exc
        return _deploys_from(_json_list(payload, "gh run list"), environment)


def gh_available() -> bool:  # pragma: no cover
    """True if the ``gh`` CLI is on PATH."""
    return shutil.which("gh") is not None


def slug_from_remote_url(url: str) -> str | None:
    """``owner/name`` from a GitHub remote URL, or None when it is not one.

    Handles the three spellings a checkout can carry — ``git@github.com:owner/name.git``,
    ``https://github.com/owner/name(.git)``, ``ssh://git@github.com/owner/name.git`` — and is
    deliberately strict about the host: a GitLab or Bitbucket remote is *not* a slug ``gh`` can
    read, and guessing one would send the digest to a repository that is not ours."""
    text = url.strip()
    if not text:
        return None
    for prefix in ("git@github.com:", "ssh://git@github.com/", "git://github.com/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    else:
        for prefix in ("https://github.com/", "http://github.com/"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        else:
            return None
    text = text[: -len(".git")] if text.endswith(".git") else text
    parts = [p for p in text.strip("/").split("/") if p]
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _git_remote_url(repo: Path | str) -> str:  # pragma: no cover -- thin seam
    result = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS,
    )
    return result.stdout if result.returncode == 0 else ""


def remote_slug(
    repo: Path | str, *, read_url: Callable[[Path | str], str] = _git_remote_url
) -> str | None:
    """The ``owner/name`` of ``repo``'s ``origin`` remote, or None (no remote, not GitHub, no git).

    The daily digest used to hand `gh --repo` the repository *path*, which `gh` rejects — so the
    scheduled job could not read the pipeline at all (ADR 0095)."""
    try:
        return slug_from_remote_url(read_url(repo))
    except (subprocess.SubprocessError, OSError):
        return None


def pipeline_source(
    repo: Path | str,
    *,
    available: Callable[[], bool] = gh_available,
    slug: Callable[[Path | str], str | None] = remote_slug,
) -> PipelineSource:
    """Select a PipelineSource for ``repo`` — a local checkout path *or* an ``owner/name`` slug.

    :class:`GhPipelineSource` when ``gh`` is available and a slug is known; an
    :class:`~agentic_forge.ops.UnavailablePipeline` when ``gh`` is there but the checkout has no
    GitHub remote (a *configured* source that cannot answer — never silently empty); otherwise an
    empty in-memory source, the graceful no-provider fallback. ``available`` and ``slug`` are
    injectable for testing."""
    if not available():
        return InMemoryPipeline({})
    name = slug(repo) if Path(repo).is_dir() else str(repo)
    if not name:
        return UnavailablePipeline(f"no GitHub 'origin' remote in {repo}")
    return GhPipelineSource(name)


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
    return _alerts_from(data, environment)


def _alerts_from(data: list[Any], environment: str) -> list[Alert]:
    """Alerts from decoded Alertmanager entries (see :func:`parse_grafana_alerts`)."""
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
        """The active alerts, or :class:`SourceUnavailable` when Grafana could not answer (a
        refused URL scheme, a network / HTTP error, a timeout, or a body that is not the alert
        JSON — typically a login page). This used to degrade to ``[]``, read as *no alerts*."""
        from urllib.parse import urlparse

        # Only fetch over http(s): refuse file://, ftp://, etc. so a misconfigured GRAFANA_URL
        # cannot turn the seam into an SSRF / local-file read or leak the Bearer token elsewhere.
        scheme = urlparse(self.base_url).scheme
        if scheme not in ("http", "https"):
            raise SourceUnavailable(f"GRAFANA_URL scheme {scheme or '<none>'!r} is not http(s)")
        try:
            payload = _grafana_alerts(self.base_url, self.token)
        except OSError as exc:  # URLError / HTTPError / socket.timeout are all OSErrors
            raise SourceUnavailable(f"grafana fetch failed: {exc}") from exc
        return _alerts_from(_json_list(payload, "grafana alerts"), environment)


def alert_source(*, env: Callable[[str], str | None] = os.environ.get) -> AlertSource:
    """Select an AlertSource: :class:`GrafanaAlertSource` when ``GRAFANA_URL`` is set, else an empty
    in-memory source (graceful fallback). ``env`` is injectable for testing."""
    url = env("GRAFANA_URL")
    if url:
        return GrafanaAlertSource(url, env("GRAFANA_TOKEN") or "")
    return InMemoryAlerts({})
