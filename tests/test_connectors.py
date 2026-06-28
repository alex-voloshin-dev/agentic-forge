from __future__ import annotations

import json

import pytest

from agentic_forge import connectors, ops
from agentic_forge.connectors import (
    GhPipelineSource,
    GrafanaAlertSource,
    alert_source,
    parse_gh_runs,
    parse_grafana_alerts,
    pipeline_source,
)


def _runs(*runs: dict) -> str:
    return json.dumps(list(runs))


# --- parse_gh_runs: status mapping -----------------------------------------------------


@pytest.mark.parametrize(
    "run,expected",
    [
        ({"status": "completed", "conclusion": "success"}, "passing"),
        ({"status": "completed", "conclusion": "failure"}, "failing"),
        ({"status": "completed", "conclusion": "timed_out"}, "failing"),
        ({"status": "completed", "conclusion": "startup_failure"}, "failing"),
        ({"status": "completed", "conclusion": "cancelled"}, "passing"),  # not a failure
        ({"status": "completed", "conclusion": "skipped"}, "passing"),
        ({"status": "in_progress"}, "running"),
        ({"status": "queued"}, "queued"),
        ({"status": "waiting"}, "queued"),
        ({"status": "weird"}, "running"),  # unknown in-flight -> running
    ],
)
def test_parse_status_mapping(run: dict, expected: str) -> None:
    run = {"headSha": "abcdef0123", "createdAt": "2026-06-24T10:00:00Z", **run}
    deploys = parse_gh_runs(_runs(run), "production")
    assert len(deploys) == 1 and deploys[0].status == expected


def test_parse_fields_and_sha_shortened() -> None:
    payload = _runs({"headSha": "abcdef0123456789", "status": "completed", "conclusion": "success",
                     "createdAt": "2026-06-24T10:00:00Z"})
    d = parse_gh_runs(payload, "staging")[0]
    assert d.sha == "abcdef0" and d.environment == "staging" and d.at == "2026-06-24T10:00:00Z"


def test_parse_preserves_order() -> None:
    payload = _runs(
        {"headSha": "aaa", "status": "completed", "conclusion": "failure"},
        {"headSha": "bbb", "status": "completed", "conclusion": "success"},
    )
    deploys = parse_gh_runs(payload, "prod")
    assert [d.sha for d in deploys] == ["aaa", "bbb"]  # gh returns newest first; order kept


# --- parse_gh_runs: tolerance ----------------------------------------------------------


def test_parse_empty_list() -> None:
    assert parse_gh_runs("[]", "prod") == []


def test_parse_invalid_json_is_empty() -> None:
    assert parse_gh_runs("not json", "prod") == []


def test_parse_non_list_is_empty() -> None:
    assert parse_gh_runs('{"runs": 1}', "prod") == []


def test_parse_skips_non_dict_entries() -> None:
    good = {"headSha": "a", "status": "completed", "conclusion": "success"}
    payload = json.dumps([good, 42, "x"])
    assert len(parse_gh_runs(payload, "prod")) == 1


def test_parse_run_missing_fields() -> None:
    d = parse_gh_runs("[{}]", "prod")[0]
    assert d.sha == "" and d.status == "running" and d.at == ""


# --- GhPipelineSource.recent_deploys (seam monkeypatched) ------------------------------


def test_recent_deploys_parses_fetched_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _runs({"headSha": "abc1234", "status": "completed", "conclusion": "success"})
    monkeypatch.setattr(connectors, "_gh_run_list", lambda repo, limit: payload)
    deploys = GhPipelineSource("owner/repo").recent_deploys("prod")
    assert len(deploys) == 1 and deploys[0].status == "passing"


def test_recent_deploys_degrades_on_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(repo: str, limit: int) -> str:
        raise OSError("gh not found")

    monkeypatch.setattr(connectors, "_gh_run_list", boom)
    assert GhPipelineSource("owner/repo").recent_deploys("prod") == []


# --- pipeline_source selection ---------------------------------------------------------


def test_pipeline_source_uses_gh_when_available() -> None:
    src = pipeline_source("owner/repo", available=lambda: True)
    assert isinstance(src, GhPipelineSource)
    assert isinstance(src, ops.PipelineSource)  # satisfies the Protocol


def test_pipeline_source_falls_back_without_gh() -> None:
    src = pipeline_source("owner/repo", available=lambda: False)
    assert isinstance(src, ops.InMemoryPipeline)
    assert src.recent_deploys("prod") == []  # empty, graceful


# --- parse_grafana_alerts --------------------------------------------------------------


def _alerts(*items: dict) -> str:
    return json.dumps(list(items))


@pytest.mark.parametrize(
    "label_sev,expected",
    [("critical", "critical"), ("page", "critical"), ("warning", "warning"),
     ("high", "warning"), ("info", "info"), ("mystery", "warning"), ("", "warning")],
)
def test_grafana_severity_mapping(label_sev: str, expected: str) -> None:
    payload = _alerts({"labels": {"severity": label_sev, "alertname": "X"}})
    alerts = parse_grafana_alerts(payload, "production")
    assert len(alerts) == 1 and alerts[0].severity == expected and alerts[0].source == "grafana"


def test_grafana_summary_prefers_annotation_then_alertname() -> None:
    a = parse_grafana_alerts(_alerts({"labels": {"alertname": "HighCPU"},
                                      "annotations": {"summary": "CPU > 90%"}}), "prod")[0]
    assert a.summary == "CPU > 90%"
    b = parse_grafana_alerts(_alerts({"labels": {"alertname": "HighCPU"}}), "prod")[0]
    assert b.summary == "HighCPU"
    c = parse_grafana_alerts(_alerts({"labels": {}}), "prod")[0]
    assert c.summary == "alert"


def test_grafana_skips_non_active() -> None:
    payload = _alerts(
        {"labels": {"severity": "critical"}, "status": {"state": "resolved"}},
        {"labels": {"severity": "warning"}, "status": {"state": "active"}},
        {"labels": {"severity": "info"}},  # no status -> treated as active
    )
    sevs = [a.severity for a in parse_grafana_alerts(payload, "prod")]
    assert sevs == ["warning", "info"]


def test_grafana_environment_filter() -> None:
    payload = _alerts(
        {"labels": {"severity": "critical", "environment": "staging"}},
        {"labels": {"severity": "warning", "environment": "production"}},
        {"labels": {"severity": "info"}},  # no env label -> kept
    )
    sevs = [a.severity for a in parse_grafana_alerts(payload, "production")]
    assert sevs == ["warning", "info"]


def test_grafana_tolerates_bad_shapes() -> None:
    assert parse_grafana_alerts("not json", "p") == []
    assert parse_grafana_alerts('{"x": 1}', "p") == []  # non-list
    # non-dict entries and non-dict labels/annotations are tolerated
    payload = json.dumps([42, {"labels": "nope", "annotations": "nope"}])
    out = parse_grafana_alerts(payload, "p")
    assert len(out) == 1 and out[0].summary == "alert" and out[0].severity == "warning"


# --- GrafanaAlertSource + alert_source -------------------------------------------------


def test_grafana_source_parses_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _alerts({"labels": {"severity": "critical"}, "annotations": {"summary": "down"}})
    monkeypatch.setattr(connectors, "_grafana_alerts", lambda url, token: payload)
    alerts = GrafanaAlertSource("https://g.example", "tok").active_alerts("prod")
    assert len(alerts) == 1 and alerts[0].severity == "critical"


def test_grafana_source_degrades_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, token: str) -> str:
        raise OSError("network")

    monkeypatch.setattr(connectors, "_grafana_alerts", boom)
    assert GrafanaAlertSource("https://g.example").active_alerts("prod") == []


def test_grafana_source_refuses_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    # a file:// (or other non-http) GRAFANA_URL must NOT be fetched (SSRF / token-leak guard):
    # the seam returns [] without ever calling the fetch.
    called = False

    def spy(url: str, token: str) -> str:
        nonlocal called
        called = True
        return "[]"

    monkeypatch.setattr(connectors, "_grafana_alerts", spy)
    assert GrafanaAlertSource("file:///etc/passwd", "tok").active_alerts("prod") == []
    assert not called  # short-circuited before the fetch


def test_alert_source_grafana_when_url_set() -> None:
    env = {"GRAFANA_URL": "https://g.example", "GRAFANA_TOKEN": "tok"}
    src = alert_source(env=env.get)
    assert isinstance(src, GrafanaAlertSource)
    assert isinstance(src, ops.AlertSource) and src.base_url == "https://g.example"


def test_alert_source_falls_back_without_url() -> None:
    src = alert_source(env=lambda _: None)
    assert isinstance(src, ops.InMemoryAlerts)
    assert src.active_alerts("prod") == []
