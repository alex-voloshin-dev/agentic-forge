"""Load and validate SDLC handoff artifacts (Markdown + YAML frontmatter).

Each phase of the SDLC spine writes an artifact that the next phase reads. The body is for
humans and Claude; the YAML frontmatter header carries the structured fields the next phase
parses. This module loads those artifacts (reusing :mod:`frontmatter`) and validates the
header against a small per-type JSON Schema, so a downstream phase can rely on the key
fields being present and well-typed.

Artifact types and their producers (see docs/architecture/engine.md):

- ``research-brief`` — Explore-based research phase.
- ``prd`` — product-spec phase.
- ``tech-design`` — architect role.
- ``plan`` — Plan-based work-planning phase.
- ``review`` — reviewer role (the unit the bounded review loop branches on); also produced by the
  ``security-review`` phase (security-lensed, same verdict + severity-tagged findings). The
  ``deep-review`` / multi-aspect reviews reuse the finding *shape* (adding ``evidence``) but emit no
  handoff artifact of their own.
- ``test-strategy`` — ``qa-test-strategy`` phase (test levels, risks, prioritized cases).
- ``release`` — ``release`` phase (semver version + Keep-a-Changelog groups).
- ``incident`` — ``incident-response`` phase (severity sev1–4, timeline, remediation).
- ``deploy-status`` — ``deploy-watch`` phase (environment, pipeline state, alerts, action).
- ``market-brief`` — ``marketing`` (market-research): segments, named competitors, cited sources.
- ``marketing-strategy`` — ``marketing`` (strategy): positioning, channels, messaging, metrics.
- ``ux-spec`` — ``ux-design`` phase: user flows, screens/states, accessibility, design-system refs.
- ``onboarding`` — ``repo-onboarding`` phase: components, entry points, conventions, risks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontmatter import FrontmatterError, parse

__all__ = [
    "STATUSES",
    "VERDICTS",
    "SEVERITIES",
    "INCIDENT_SEVERITIES",
    "SCHEMAS",
    "ARTIFACT_TYPES",
    "HandoffError",
    "Artifact",
    "schema_for",
    "validate_header",
    "parse_artifact",
    "load_artifact",
]

# Recommended status vocabulary for feature artifacts (documented guidance, NOT enforced — the
# schema accepts any non-empty status string, since real artifacts use varied lifecycle labels
# such as "complete"/"ready"). Downstream phases that branch on status should map liberally.
STATUSES = ["draft", "in-review", "approved", "final", "superseded"]

# Review verdict vocabulary. `approve` is the early-exit signal for the bounded review loop.
VERDICTS = ["approve", "changes"]

# Finding severities, ordered most to least serious. `blocker`/`major` block an `approve`.
SEVERITIES = ["blocker", "major", "minor", "nit"]

# Incident severities (operations), most to least serious — distinct from review-finding
# SEVERITIES: sev1 = critical (outage / data loss), sev2 = major (degraded, no workaround),
# sev3 = minor (degraded, workaround exists), sev4 = low (cosmetic / latent). See quality-ops.md.
INCIDENT_SEVERITIES = ["sev1", "sev2", "sev3", "sev4"]

_DRAFT7 = "http://json-schema.org/draft-07/schema#"
# A list entry may be a bare string OR a structured object — real artifacts carry both (a
# decision as {id, title, adr}, a component as {name, change}, a risk as {risk, mitigation}),
# which is richer than a bare string and just as valid.
_ENTRY: dict[str, Any] = {"type": ["string", "object"]}
_LIST: dict[str, Any] = {"type": "array", "items": _ENTRY}
_NONEMPTY_LIST: dict[str, Any] = {"type": "array", "minItems": 1, "items": _ENTRY}

# A plan task: an id plus optional dependency ids and a title.
_TASKS: dict[str, Any] = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["id"],
        "additionalProperties": True,
        "properties": {
            "id": {"type": ["string", "integer"]},
            "deps": {"type": "array", "items": {"type": ["string", "integer"]}},
            "title": {"type": "string"},
        },
    },
}

# A review finding: a severity and a location, with an optional suggested fix.
_FINDINGS: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["severity", "location"],
        "additionalProperties": True,
        "properties": {
            "severity": {"enum": SEVERITIES},
            "location": {"type": "string"},
            "issue": {"type": "string"},
            "suggestion": {"type": "string"},
        },
    },
}


def _feature_schema(
    type_id: str,
    *,
    required_extra: list[str],
    properties_extra: dict[str, Any],
) -> dict[str, Any]:
    """Build a header schema for a feature-scoped artifact (type + feature + status)."""
    properties: dict[str, Any] = {
        "type": {"const": type_id},
        "feature": {"type": "string", "minLength": 1},
        # Any non-empty status string — real artifacts use labels beyond the recommended set.
        "status": {"type": "string", "minLength": 1},
    }
    properties.update(properties_extra)
    return {
        "$schema": _DRAFT7,
        "type": "object",
        "required": ["type", "feature", "status", *required_extra],
        "additionalProperties": True,
        "properties": properties,
    }


SCHEMAS: dict[str, dict[str, Any]] = {
    "research-brief": _feature_schema(
        "research-brief",
        required_extra=[],
        properties_extra={"date": {}, "sources": _LIST},
    ),
    "prd": _feature_schema(
        "prd",
        required_extra=["goals", "acceptance"],
        properties_extra={
            "goals": _NONEMPTY_LIST,
            "non_goals": _LIST,
            "metrics": _LIST,
            "acceptance": _NONEMPTY_LIST,
        },
    ),
    "tech-design": _feature_schema(
        "tech-design",
        required_extra=["decisions", "components"],
        properties_extra={
            "decisions": _NONEMPTY_LIST,
            "components": _NONEMPTY_LIST,
            "risks": _LIST,
        },
    ),
    "plan": _feature_schema(
        "plan",
        required_extra=["tasks"],
        properties_extra={
            "tasks": _TASKS,
            "checkpoints": _LIST,
            "deferred": _LIST,
        },
    ),
    "review": {
        "$schema": _DRAFT7,
        "type": "object",
        "required": ["type", "target", "iteration", "verdict"],
        "additionalProperties": True,
        "properties": {
            "type": {"const": "review"},
            "target": {"type": "string", "minLength": 1},
            "iteration": {"type": "integer", "minimum": 1},
            "verdict": {"enum": VERDICTS},
            "findings": _FINDINGS,
        },
    },
    "test-strategy": _feature_schema(
        "test-strategy",
        required_extra=["test_levels"],
        properties_extra={
            "scope": {"type": "string"},
            "risks": _LIST,
            "test_levels": _NONEMPTY_LIST,  # unit / integration / e2e / perf / security …
            "cases": _LIST,
        },
    ),
    "release": _feature_schema(
        "release",
        required_extra=["version", "changelog"],
        properties_extra={
            "version": {"type": "string", "minLength": 1},  # semver
            "changelog": _NONEMPTY_LIST,  # Keep-a-Changelog groups (Added/Changed/Fixed/Removed)
            "breaking": _LIST,
            "date": {},
        },
    ),
    "incident": {
        "$schema": _DRAFT7,
        "type": "object",
        "required": ["type", "severity", "status", "impact", "timeline"],
        "additionalProperties": True,
        "properties": {
            "type": {"const": "incident"},
            "severity": {"enum": INCIDENT_SEVERITIES},
            "status": {"type": "string", "minLength": 1},
            "impact": {"type": "string", "minLength": 1},
            "timeline": _NONEMPTY_LIST,  # ≥1 entry (at least the detection event)
            "remediation": _LIST,
            "action_items": _LIST,
        },
    },
    "deploy-status": {
        "$schema": _DRAFT7,
        "type": "object",
        "required": ["type", "environment", "pipeline"],
        "additionalProperties": True,
        "properties": {
            "type": {"const": "deploy-status"},
            "environment": {"type": "string", "minLength": 1},
            "pipeline": {"type": ["string", "object"]},  # state label or structured pipeline info
            "deploys": _LIST,
            "alerts": {"type": ["array", "object"]},  # a raw list or a severity→count triage dict
            "action": {"type": "string"},
        },
    },
    "market-brief": _feature_schema(
        "market-brief",
        required_extra=["competitors"],
        properties_extra={
            "segments": _LIST,
            "competitors": _NONEMPTY_LIST,  # named competitors, not "various players"
            "sizing": {"type": ["string", "object"]},
            "sources": _LIST,  # citations backing the claims
        },
    ),
    "marketing-strategy": _feature_schema(
        "marketing-strategy",
        required_extra=["positioning", "channels"],
        properties_extra={
            "positioning": {"type": "string", "minLength": 1},
            "segments": _LIST,
            "channels": _NONEMPTY_LIST,
            "messaging": _LIST,
            "metrics": _LIST,
        },
    ),
    "ux-spec": _feature_schema(
        "ux-spec",
        required_extra=["flows"],
        properties_extra={
            "flows": _NONEMPTY_LIST,  # user flows (specs, not pixels)
            "screens": _LIST,  # screens + their states (empty/loading/error/success)
            "accessibility": _LIST,  # WCAG: keyboard, contrast, semantics/ARIA
            "design_system": _LIST,  # referenced components/tokens
        },
    ),
    "onboarding": _feature_schema(
        "onboarding",
        required_extra=["components"],
        properties_extra={
            "components": _NONEMPTY_LIST,  # the real modules/components found
            "entry_points": _LIST,
            "conventions": _LIST,
            "risks": _LIST,
        },
    ),
}

ARTIFACT_TYPES: tuple[str, ...] = tuple(SCHEMAS)


class HandoffError(ValueError):
    """Raised when a handoff artifact cannot be read, parsed, or validated."""


@dataclass
class Artifact:
    """A parsed, validated handoff artifact."""

    type: str
    header: dict[str, Any]
    body: str


def schema_for(artifact_type: str) -> dict[str, Any]:
    """Return the JSON Schema for an artifact type, or raise HandoffError if unknown."""
    try:
        return SCHEMAS[artifact_type]
    except KeyError:
        raise HandoffError(
            f"unknown artifact type {artifact_type!r}; expected one of {sorted(SCHEMAS)}"
        ) from None


def validate_header(
    header: dict[str, Any], *, expected_type: str | None = None
) -> list[str]:
    """Return a list of header-validation messages. Empty list means valid.

    The type validated against is ``expected_type`` when given, otherwise the header's own
    ``type`` field. Each schema pins ``type`` with ``const``, so a header whose declared
    type disagrees with ``expected_type`` fails with a clear message.
    """
    target_type = expected_type if expected_type is not None else header.get("type")
    if not target_type:
        return ["header is missing the required 'type' field"]
    if target_type not in SCHEMAS:
        return [f"unknown artifact type {target_type!r}; expected one of {sorted(SCHEMAS)}"]

    try:
        import jsonschema  # lazy: keeps the hook import path (diagnostics -> handoff) stdlib-only
    except ImportError:
        return []  # no validator available (bare env) — skip header validation rather than crash

    validator = jsonschema.Draft7Validator(SCHEMAS[target_type])
    errors = []
    for err in sorted(validator.iter_errors(header), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{location}: {err.message}")
    return errors


def parse_artifact(text: str, *, expected_type: str | None = None) -> Artifact:
    """Parse artifact text into a validated Artifact, or raise HandoffError."""
    try:
        header, body = parse(text)
    except FrontmatterError as exc:
        raise HandoffError(str(exc)) from exc
    errors = validate_header(header, expected_type=expected_type)
    if errors:
        raise HandoffError("; ".join(errors))
    return Artifact(type=str(header["type"]), header=header, body=body)


def load_artifact(path: Path | str, *, expected_type: str | None = None) -> Artifact:
    """Load and validate a handoff artifact from a file, or raise HandoffError."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoffError(f"cannot read {path}: {exc}") from exc
    return parse_artifact(text, expected_type=expected_type)
