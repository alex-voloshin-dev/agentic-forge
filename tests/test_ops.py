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
        ({"cosmetic": True}, "sev4"),
        ({}, "sev4"),
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
