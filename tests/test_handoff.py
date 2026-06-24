from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from agentic_forge import handoff
from agentic_forge.handoff import (
    ARTIFACT_TYPES,
    SCHEMAS,
    Artifact,
    HandoffError,
    load_artifact,
    parse_artifact,
    schema_for,
    validate_header,
)

# --- valid headers per artifact type -------------------------------------------------

VALID_HEADERS: dict[str, dict] = {
    "research-brief": {
        "type": "research-brief",
        "feature": "search",
        "status": "draft",
        "date": "2026-06-20",
        "sources": ["https://example.com/a", "https://example.com/b"],
    },
    "prd": {
        "type": "prd",
        "feature": "search",
        "status": "approved",
        "goals": ["Find results fast"],
        "non_goals": ["Personalization"],
        "metrics": ["p95 < 200ms"],
        "acceptance": ["Query returns ranked results"],
    },
    "tech-design": {
        "type": "tech-design",
        "feature": "search",
        "status": "in-review",
        "decisions": ["Use an inverted index"],
        "components": ["indexer", "query-api"],
        "risks": ["Index staleness"],
    },
    "plan": {
        "type": "plan",
        "feature": "search",
        "status": "approved",
        "tasks": [
            {"id": "T1", "title": "Build indexer"},
            {"id": "T2", "deps": ["T1"], "title": "Build query API"},
        ],
        "checkpoints": ["Indexer green"],
        "deferred": ["Faceted search"],
    },
    "review": {
        "type": "review",
        "target": "docs/sdlc/search/tech-design.md",
        "iteration": 1,
        "verdict": "changes",
        "findings": [
            {"severity": "major", "location": "tech-design.md#cache", "suggestion": "Add TTL"}
        ],
    },
    "test-strategy": {
        "type": "test-strategy",
        "feature": "search",
        "status": "draft",
        "scope": "The new ranking parameter",
        "risks": ["Ranking regressions", {"risk": "latency", "mitigation": "cache"}],
        "test_levels": ["unit", "integration", "e2e"],
        "cases": ["empty query", "huge query"],
    },
    "release": {
        "type": "release",
        "feature": "search",
        "status": "final",
        "version": "1.4.0",
        "changelog": [{"group": "Added", "items": ["Ranking param"]}, "Fixed: cache TTL"],
        "breaking": [],
        "date": "2026-06-24",
    },
    "incident": {
        "type": "incident",
        "severity": "sev2",
        "status": "mitigating",
        "impact": "Search latency p95 > 2s for 8% of users",
        "timeline": [{"at": "10:02", "event": "alert fired"}, "10:15 mitigation applied"],
        "remediation": ["Roll back ranking change"],
        "action_items": ["Add a latency canary"],
    },
    "deploy-status": {
        "type": "deploy-status",
        "environment": "production",
        "pipeline": "passing",
        "deploys": [{"sha": "abc123", "at": "10:00"}],
        "alerts": [],
        "action": "none — healthy",
    },
}


def _artifact_text(header_lines: str, body: str = "Body text.\n") -> str:
    return f"---\n{header_lines}\n---\n{body}"


# --- schema_for ----------------------------------------------------------------------


def test_artifact_types_match_schemas() -> None:
    assert set(ARTIFACT_TYPES) == set(SCHEMAS)


def test_schema_for_known() -> None:
    schema = schema_for("review")
    assert schema["properties"]["type"]["const"] == "review"


def test_schema_for_unknown_raises() -> None:
    with pytest.raises(HandoffError, match="unknown artifact type"):
        schema_for("nope")


# --- validate_header: valid cases ----------------------------------------------------


@pytest.mark.parametrize("artifact_type", list(VALID_HEADERS))
def test_valid_headers_pass(artifact_type: str) -> None:
    assert validate_header(VALID_HEADERS[artifact_type]) == []


def test_review_approve_without_findings_is_valid() -> None:
    header = {"type": "review", "target": "diff", "iteration": 2, "verdict": "approve"}
    assert validate_header(header) == []


# --- validate_header: invalid cases --------------------------------------------------


def test_missing_type_field() -> None:
    errors = validate_header({"feature": "x", "status": "draft"})
    assert errors == ["header is missing the required 'type' field"]


def test_unknown_type_field() -> None:
    errors = validate_header({"type": "mystery"})
    assert len(errors) == 1
    assert "unknown artifact type" in errors[0]


def test_missing_required_field_reports_root() -> None:
    # prd without goals/acceptance: required errors are reported at <root>.
    errors = validate_header({"type": "prd", "feature": "x", "status": "draft"})
    assert any("<root>" in e and "goals" in e for e in errors)
    assert any("acceptance" in e for e in errors)


def test_status_accepts_free_string() -> None:
    # Real artifacts use labels beyond the recommended set (e.g. "complete") — accept any string.
    assert validate_header({**VALID_HEADERS["prd"], "status": "complete"}) == []


def test_bad_status_type() -> None:
    # ...but a non-string (or empty) status is still rejected.
    errors = validate_header({**VALID_HEADERS["prd"], "status": 123})
    assert any(e.startswith("status:") for e in errors)


def test_research_brief_accepts_date_object() -> None:
    # YAML parses an unquoted ISO date into a date object; the schema must tolerate it.
    header = {**VALID_HEADERS["research-brief"], "date": datetime.date(2026, 6, 21)}
    assert validate_header(header) == []


def test_wrong_field_type_reports_location() -> None:
    header = {**VALID_HEADERS["research-brief"], "sources": "not-a-list"}
    errors = validate_header(header)
    assert any(e.startswith("sources:") for e in errors)


def test_tech_design_accepts_structured_list_items() -> None:
    # Real artifacts carry structured entries (a decision/component/risk as an object), not just
    # bare strings — the schema must accept both.
    header = {
        "type": "tech-design",
        "feature": "search",
        "status": "draft",
        "decisions": [{"id": "ADR-001", "title": "Use an inverted index", "adr": "adr-001.md"}],
        "components": [{"name": "indexer", "change": "build it"}],
        "risks": [{"risk": "staleness", "mitigation": "ttl"}],
    }
    assert validate_header(header) == []


def test_prd_empty_goals_rejected() -> None:
    header = {**VALID_HEADERS["prd"], "goals": []}
    errors = validate_header(header)
    assert any(e.startswith("goals:") for e in errors)


def test_plan_task_missing_id() -> None:
    header = {**VALID_HEADERS["plan"], "tasks": [{"title": "no id"}]}
    errors = validate_header(header)
    assert any(e.startswith("tasks/0") for e in errors)


def test_review_bad_verdict() -> None:
    header = {**VALID_HEADERS["review"], "verdict": "maybe"}
    errors = validate_header(header)
    assert any(e.startswith("verdict:") for e in errors)


def test_review_bad_finding_severity() -> None:
    header = {
        **VALID_HEADERS["review"],
        "findings": [{"severity": "huge", "location": "x"}],
    }
    errors = validate_header(header)
    assert any(e.startswith("findings/0/severity") for e in errors)


def test_incident_bad_severity() -> None:
    errors = validate_header({**VALID_HEADERS["incident"], "severity": "sev9"})
    assert any(e.startswith("severity:") for e in errors)


def test_incident_empty_timeline_rejected() -> None:
    errors = validate_header({**VALID_HEADERS["incident"], "timeline": []})
    assert any(e.startswith("timeline:") for e in errors)


def test_release_empty_changelog_rejected() -> None:
    errors = validate_header({**VALID_HEADERS["release"], "changelog": []})
    assert any(e.startswith("changelog:") for e in errors)


def test_test_strategy_empty_levels_rejected() -> None:
    errors = validate_header({**VALID_HEADERS["test-strategy"], "test_levels": []})
    assert any(e.startswith("test_levels:") for e in errors)


def test_deploy_status_missing_environment_reports_root() -> None:
    errors = validate_header({"type": "deploy-status", "pipeline": "passing"})
    assert any("<root>" in e and "environment" in e for e in errors)


def test_expected_type_mismatch() -> None:
    # A valid-looking prd header validated against research-brief fails on the type const.
    header = {"type": "prd", "feature": "x", "status": "draft"}
    errors = validate_header(header, expected_type="research-brief")
    assert any(e.startswith("type:") for e in errors)


def test_validate_header_unknown_expected_type() -> None:
    errors = validate_header({"type": "prd"}, expected_type="bogus")
    assert errors == [
        "unknown artifact type 'bogus'; expected one of " + str(sorted(SCHEMAS))
    ]


# --- parse_artifact ------------------------------------------------------------------


def test_parse_artifact_returns_artifact() -> None:
    text = _artifact_text(
        "type: review\ntarget: diff\niteration: 1\nverdict: approve", body="All good.\n"
    )
    art = parse_artifact(text)
    assert isinstance(art, Artifact)
    assert art.type == "review"
    assert art.header["verdict"] == "approve"
    assert art.body == "All good.\n"


def test_parse_artifact_with_expected_type() -> None:
    text = _artifact_text("type: review\ntarget: diff\niteration: 1\nverdict: approve")
    art = parse_artifact(text, expected_type="review")
    assert art.type == "review"


def test_parse_artifact_malformed_frontmatter() -> None:
    with pytest.raises(HandoffError):
        parse_artifact("no frontmatter at all")


def test_parse_artifact_invalid_header() -> None:
    text = _artifact_text("type: prd\nfeature: x\nstatus: draft")  # missing goals/acceptance
    with pytest.raises(HandoffError, match="goals"):
        parse_artifact(text)


# --- load_artifact -------------------------------------------------------------------


def test_load_artifact_from_file(tmp_path: Path) -> None:
    path = tmp_path / "tech-design.md"
    path.write_text(
        _artifact_text(
            "type: tech-design\nfeature: search\nstatus: draft\n"
            "decisions:\n  - Use an index\ncomponents:\n  - indexer",
            body="# Design\n",
        ),
        encoding="utf-8",
    )
    art = load_artifact(path)
    assert art.type == "tech-design"
    assert art.header["components"] == ["indexer"]
    assert art.body == "# Design\n"


def test_load_artifact_accepts_str_path(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    path.write_text(
        _artifact_text("type: review\ntarget: diff\niteration: 1\nverdict: approve"),
        encoding="utf-8",
    )
    art = load_artifact(str(path))
    assert art.type == "review"


def test_load_artifact_missing_file(tmp_path: Path) -> None:
    with pytest.raises(HandoffError, match="cannot read"):
        load_artifact(tmp_path / "does-not-exist.md")


def test_module_exposes_vocabularies() -> None:
    assert handoff.VERDICTS == ["approve", "changes"]
    assert "blocker" in handoff.SEVERITIES
    assert "draft" in handoff.STATUSES
    assert handoff.INCIDENT_SEVERITIES == ["sev1", "sev2", "sev3", "sev4"]
