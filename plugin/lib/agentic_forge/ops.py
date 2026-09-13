"""Operations adapter seam + deterministic assessment for the ``deploy-watch`` and
``incident-response`` skills (Stage 4; see docs/architecture/quality-ops.md).

External state — CI/CD pipeline status and monitoring alerts — arrives through provider-agnostic
**sources** (:class:`PipelineSource`, :class:`AlertSource`). Real connectors (MCP / ``gh`` /
provider APIs) implement them behind the seam; the ``InMemoryPipeline`` / ``InMemoryAlerts``
fakes back the tests and the eval fixtures, so Stage-4 Tier-2 runs with no live infra. The
assessment — rollout health, alert triage, incident-severity classification — is pure and fully
tested; the skills wire a real source to it and render the result into the handoff artifact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .handoff import INCIDENT_SEVERITIES

__all__ = [
    "Deploy",
    "Alert",
    "PipelineSource",
    "AlertSource",
    "InMemoryPipeline",
    "InMemoryAlerts",
    "HEALTH",
    "HEALTH_UNKNOWN",
    "ALERT_SEVERITIES",
    "SourceUnavailable",
    "rollout_health",
    "triage_alerts",
    "recommended_action",
    "deploy_status",
    "classify_incident",
]

# Rollout health, best to worst. Drives recommended_action.
HEALTH: tuple[str, ...] = ("healthy", "degraded", "failing")
# The health :func:`deploy_status` reports when a source could not answer and nothing known says
# worse: NOT one of the assessed levels above, and never spelled "healthy" — zero data from a
# failed fetch is not zero problems.
HEALTH_UNKNOWN = "unknown"
# Monitoring alert severities (provider-normalised), most to least serious.
ALERT_SEVERITIES: tuple[str, ...] = ("critical", "warning", "info")


class SourceUnavailable(RuntimeError):
    """A source could not answer — the fetch failed, timed out, or returned something that is not
    its data (a login page, a rate-limit error). Distinct from an empty answer: a connector raises
    this instead of degrading to ``[]``, so :func:`deploy_status` can say *unknown* rather than
    read "no runs, no alerts" as *healthy*. The message is the human-readable reason."""


@dataclass(frozen=True)
class Deploy:
    """One deploy/pipeline run in an environment."""

    sha: str
    status: str  # "passing" | "failing" | "running" | "queued"
    environment: str
    at: str = ""


@dataclass(frozen=True)
class Alert:
    """One active monitoring alert."""

    severity: str  # one of ALERT_SEVERITIES
    summary: str
    source: str = ""


@runtime_checkable
class PipelineSource(Protocol):
    """A CI/CD provider: the recent deploys for an environment, newest first. An implementation
    raises :class:`SourceUnavailable` when it cannot answer; ``[]`` means "no runs"."""

    def recent_deploys(self, environment: str) -> list[Deploy]: ...


@runtime_checkable
class AlertSource(Protocol):
    """A monitoring provider: the active alerts for an environment. An implementation raises
    :class:`SourceUnavailable` when it cannot answer; ``[]`` means "no active alerts"."""

    def active_alerts(self, environment: str) -> list[Alert]: ...


@dataclass
class InMemoryPipeline:
    """A :class:`PipelineSource` fake (tests + eval fixtures), keyed by environment."""

    deploys: dict[str, list[Deploy]]

    def recent_deploys(self, environment: str) -> list[Deploy]:
        return list(self.deploys.get(environment, []))


@dataclass
class InMemoryAlerts:
    """An :class:`AlertSource` fake (tests + eval fixtures), keyed by environment."""

    alerts: dict[str, list[Alert]]

    def active_alerts(self, environment: str) -> list[Alert]:
        return list(self.alerts.get(environment, []))


def rollout_health(deploys: list[Deploy], alerts: list[Alert]) -> str:
    """Classify rollout health from the latest deploy and the active alerts.

    ``failing`` when the latest deploy failed or any ``critical`` alert is active; ``degraded``
    when the latest deploy is still in flight (``running``/``queued``) or a ``warning`` is active;
    otherwise ``healthy``.
    """
    latest = deploys[0] if deploys else None
    severities = {a.severity for a in alerts}
    if (latest is not None and latest.status == "failing") or "critical" in severities:
        return "failing"
    if (latest is not None and latest.status in {"running", "queued"}) or "warning" in severities:
        return "degraded"
    return "healthy"


def triage_alerts(alerts: list[Alert]) -> dict[str, int]:
    """Count active alerts by severity, in :data:`ALERT_SEVERITIES` order (zeros omitted)."""
    counts = Counter(a.severity for a in alerts)
    return {sev: counts[sev] for sev in ALERT_SEVERITIES if counts[sev]}


def recommended_action(health: str) -> str:
    """The default next action for a rollout-health level."""
    return {
        "failing": "roll back or halt the rollout; page the on-call owner",
        "degraded": "hold the rollout and investigate before promoting",
        "healthy": "none — continue monitoring",
        HEALTH_UNKNOWN: "investigate: health could not be assessed (a source is unavailable)",
    }.get(health, "investigate: unknown health state")


def deploy_status(
    pipeline: PipelineSource, alerts: AlertSource, environment: str
) -> dict[str, object]:
    """Assemble the ``deploy-status`` header data for an environment (health + triage + action).

    Provider-agnostic: pass real sources or the in-memory fakes. The returned mapping matches the
    ``deploy-status`` handoff schema.

    A source that raises :class:`SourceUnavailable` is reported, not hidden: its reason lands
    under ``unavailable`` (``{"pipeline": why}`` / ``{"alerts": why}``), and the health is
    :data:`HEALTH_UNKNOWN` unless what *was* readable already says worse — a failing deploy is
    still failing when the alert source is down, but "no runs, no alerts" from a rate-limited
    ``gh`` or a Grafana login page is never *healthy*.
    """
    unavailable: dict[str, str] = {}
    deploys: list[Deploy] = []
    active: list[Alert] = []
    try:
        deploys = pipeline.recent_deploys(environment)
    except SourceUnavailable as exc:
        unavailable["pipeline"] = str(exc)
    try:
        active = alerts.active_alerts(environment)
    except SourceUnavailable as exc:
        unavailable["alerts"] = str(exc)
    health = rollout_health(deploys, active)
    if unavailable and health == "healthy":
        health = HEALTH_UNKNOWN
    status: dict[str, object] = {
        "environment": environment,
        "pipeline": health,
        "deploys": [{"sha": d.sha, "status": d.status, "at": d.at} for d in deploys],
        "alerts": triage_alerts(active),
        "action": recommended_action(health),
    }
    if unavailable:
        status["unavailable"] = unavailable
    return status


def classify_incident(
    *,
    outage: bool = False,
    data_loss: bool = False,
    degraded: bool = False,
    workaround: bool = False,
) -> str:
    """Map incident signals to a severity (:data:`~agentic_forge.handoff.INCIDENT_SEVERITIES`).

    ``sev1`` outage or data loss; ``sev2`` degraded with no workaround; ``sev3`` degraded with a
    workaround; ``sev4`` otherwise (cosmetic / latent — anything not outage/degraded).
    """
    if outage or data_loss:
        return "sev1"
    if degraded:
        return "sev3" if workaround else "sev2"
    return "sev4"


# Guard: the severities this module emits must stay a subset of the handoff vocabulary.
assert set(INCIDENT_SEVERITIES) == {"sev1", "sev2", "sev3", "sev4"}
