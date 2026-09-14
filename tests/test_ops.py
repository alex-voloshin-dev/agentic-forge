from __future__ import annotations

import pytest

from agentic_forge import handoff, ops
from agentic_forge.ops import (
    Alert,
    AlertSource,
    Deploy,
    InMemoryAlerts,
    InMemoryPipeline,
    PipelineSource,
    classify_incident,
    deploy_status,
    recommended_action,
    rollout_health,
    triage_alerts,
)

# --- fakes / sources -----------------------------------------------------------------


def test_in_memory_pipeline_returns_per_env_and_empty_for_unknown() -> None:
    d = Deploy(sha="abc", status="passing", environment="prod")
    src = InMemoryPipeline({"prod": [d]})
    assert src.recent_deploys("prod") == [d]
    assert src.recent_deploys("staging") == []


def test_in_memory_alerts_returns_per_env_and_empty_for_unknown() -> None:
    a = Alert(severity="warning", summary="latency")
    src = InMemoryAlerts({"prod": [a]})
    assert src.active_alerts("prod") == [a]
    assert src.active_alerts("staging") == []


def test_fakes_satisfy_the_source_protocols() -> None:
    assert isinstance(InMemoryPipeline({}), PipelineSource)
    assert isinstance(InMemoryAlerts({}), AlertSource)


# --- rollout_health ------------------------------------------------------------------


def test_health_healthy_when_passing_and_no_alerts() -> None:
    deploys = [Deploy(sha="a", status="passing", environment="prod")]
    assert rollout_health(deploys, []) == "healthy"


def test_health_failing_on_failing_deploy() -> None:
    deploys = [Deploy(sha="a", status="failing", environment="prod")]
    assert rollout_health(deploys, []) == "failing"


def test_health_failing_on_critical_alert_even_if_deploy_passing() -> None:
    deploys = [Deploy(sha="a", status="passing", environment="prod")]
    alerts = [Alert(severity="critical", summary="5xx spike")]
    assert rollout_health(deploys, alerts) == "failing"


def test_health_degraded_on_in_flight_deploy() -> None:
    deploys = [Deploy(sha="a", status="running", environment="prod")]
    assert rollout_health(deploys, []) == "degraded"


def test_health_degraded_on_warning_alert() -> None:
    deploys = [Deploy(sha="a", status="passing", environment="prod")]
    alerts = [Alert(severity="warning", summary="latency")]
    assert rollout_health(deploys, alerts) == "degraded"


def test_health_healthy_with_no_deploys_and_no_alerts() -> None:
    assert rollout_health([], []) == "healthy"


# --- triage_alerts -------------------------------------------------------------------


def test_triage_counts_in_severity_order_and_omits_zeros() -> None:
    alerts = [
        Alert(severity="warning", summary="w1"),
        Alert(severity="critical", summary="c1"),
        Alert(severity="warning", summary="w2"),
    ]
    triaged = triage_alerts(alerts)
    assert list(triaged) == ["critical", "warning"]  # ALERT_SEVERITIES order; "info" omitted
    assert triaged == {"critical": 1, "warning": 2}


def test_triage_empty() -> None:
    assert triage_alerts([]) == {}


# --- recommended_action --------------------------------------------------------------


@pytest.mark.parametrize(
    "health,needle",
    [("failing", "roll back"), ("degraded", "hold"), ("healthy", "continue monitoring")],
)
def test_recommended_action_per_level(health: str, needle: str) -> None:
    assert needle in recommended_action(health)


def test_recommended_action_unknown() -> None:
    assert "unknown" in recommended_action("bogus")


# --- deploy_status (end to end + schema-valid) ---------------------------------------


def test_deploy_status_assembles_and_validates_against_handoff_schema() -> None:
    pipeline = InMemoryPipeline(
        {"prod": [Deploy(sha="abc123", status="failing", environment="prod", at="10:00")]}
    )
    alerts = InMemoryAlerts({"prod": [Alert(severity="critical", summary="5xx spike")]})
    status = deploy_status(pipeline, alerts, "prod")
    assert status["environment"] == "prod"
    assert status["pipeline"] == "failing"
    assert status["alerts"] == {"critical": 1}
    assert "roll back" in str(status["action"])
    # The assembled mapping must satisfy the deploy-status handoff schema.
    header = {"type": "deploy-status", **status}
    assert handoff.validate_header(header, expected_type="deploy-status") == []


def test_deploy_status_unknown_env_is_healthy_and_empty() -> None:
    status = deploy_status(InMemoryPipeline({}), InMemoryAlerts({}), "prod")
    assert status["pipeline"] == "healthy" and status["deploys"] == [] and status["alerts"] == {}


# --- classify_incident ---------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"outage": True}, "sev1"),
        ({"data_loss": True}, "sev1"),
        ({"degraded": True}, "sev2"),
        ({"degraded": True, "workaround": True}, "sev3"),
        ({}, "sev4"),  # no flags -> sev4 (the former inert `cosmetic=` param was removed)
        ({"outage": True, "workaround": True}, "sev1"),  # outage dominates
    ],
)
def test_classify_incident(kwargs: dict[str, bool], expected: str) -> None:
    assert classify_incident(**kwargs) == expected


def test_classify_incident_outputs_are_valid_severities() -> None:
    cases = ({"outage": True}, {"degraded": True}, {"degraded": True, "workaround": True}, {})
    for kwargs in cases:
        assert classify_incident(**kwargs) in handoff.INCIDENT_SEVERITIES


def test_module_exposes_vocabularies() -> None:
    assert ops.HEALTH == ("healthy", "degraded", "failing")
    assert ops.ALERT_SEVERITIES[0] == "critical"


# --- SourceUnavailable: a source that cannot answer is never "healthy" ----------------


class _Down:
    """A source that raises — a rate-limited ``gh``, a Grafana login page."""

    def __init__(self, why: str) -> None:
        self.why = why

    def recent_deploys(self, environment: str) -> list[Deploy]:
        raise ops.SourceUnavailable(self.why)

    def active_alerts(self, environment: str) -> list[Alert]:
        raise ops.SourceUnavailable(self.why)


def test_deploy_status_unavailable_pipeline_is_unknown_not_healthy() -> None:
    status = deploy_status(_Down("gh run list timed out after 60s"), InMemoryAlerts({}), "prod")
    assert status["pipeline"] == ops.HEALTH_UNKNOWN == "unknown"
    assert status["unavailable"] == {"pipeline": "gh run list timed out after 60s"}
    assert status["deploys"] == [] and status["alerts"] == {}
    assert "investigate" in str(status["action"]) and "unavailable" in str(status["action"])
    header = {"type": "deploy-status", **status}
    assert handoff.validate_header(header, expected_type="deploy-status") == []  # still valid


def test_deploy_status_keeps_a_worse_verdict_when_the_other_source_is_down() -> None:
    # A failing deploy is still failing when the alert source is down: the outage is reported
    # alongside, never allowed to soften (or hide) what the pipeline says.
    pipeline = InMemoryPipeline({"prod": [Deploy(sha="a", status="failing", environment="prod")]})
    status = deploy_status(pipeline, _Down("grafana fetch failed: 401"), "prod")
    assert status["pipeline"] == "failing" and "roll back" in str(status["action"])
    assert status["unavailable"] == {"alerts": "grafana fetch failed: 401"}


def test_deploy_status_both_sources_down_names_both() -> None:
    status = deploy_status(_Down("gh: rate limited"), _Down("grafana: login page"), "prod")
    assert status["pipeline"] == "unknown"
    assert status["unavailable"] == {
        "pipeline": "gh: rate limited", "alerts": "grafana: login page"
    }


def test_deploy_status_has_no_unavailable_key_when_sources_answer() -> None:
    status = deploy_status(InMemoryPipeline({}), InMemoryAlerts({}), "prod")
    assert "unavailable" not in status and status["pipeline"] == "healthy"  # empty != unavailable


def test_unknown_health_is_outside_the_assessed_levels() -> None:
    assert ops.HEALTH_UNKNOWN not in ops.HEALTH  # not a rung on the healthy..failing ladder
    assert "investigate" in recommended_action(ops.HEALTH_UNKNOWN)
    assert issubclass(ops.SourceUnavailable, RuntimeError)


# --- a configured source that cannot answer (ADR 0095) ---------------------------------


def test_unavailable_pipeline_raises_instead_of_reading_empty() -> None:
    """`gh` on PATH in a checkout with no GitHub remote is not "no provider configured" — it is a
    provider that cannot answer. Returning `[]` made the digest read healthy from no data."""
    src = ops.UnavailablePipeline("no GitHub 'origin' remote in /tmp/x")
    assert isinstance(src, ops.PipelineSource)
    with pytest.raises(ops.SourceUnavailable, match="origin"):
        src.recent_deploys("prod")
    status = deploy_status(src, InMemoryAlerts({}), "prod")
    assert status["pipeline"] == "unknown" and "origin" in status["unavailable"]["pipeline"]
