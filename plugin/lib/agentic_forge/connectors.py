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
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .ops import Deploy, InMemoryPipeline, PipelineSource

__all__ = ["parse_gh_runs", "GhPipelineSource", "gh_available", "pipeline_source"]

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
