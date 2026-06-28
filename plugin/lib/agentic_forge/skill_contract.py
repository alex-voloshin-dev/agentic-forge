"""Guard: every artifact-producing skill's SKILL.md must document the frontmatter fields its
handoff schema requires (ADR 0032).

The live Tier-3 sweep showed skills whose body lists the domain fields but omits the
schema-required identity fields (`ux-design` had `flows`/`screens` but not `feature`/`status`), so
the model emits an artifact `handoff.load_artifact` rejects. This module maps each skill to the
handoff `type` it produces and checks the body documents every required field of that type — a
deterministic floor against skill-body ↔ schema drift, not a proof of correct usage (that is the
eval tiers' job). See docs/architecture/quality-hardening.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import handoff
from .frontmatter import FrontmatterError, parse

_BACKTICK_SPAN = re.compile(r"`([^`]*)`")

__all__ = [
    "SKILL_HANDOFF",
    "SPINE_SKILLS",
    "required_fields",
    "handoff_contract_problems",
    "recall_problems",
]

# Skill name -> the handoff `type` it produces. An artifact-producing skill missing from this map
# is a deliberate, reviewable omission (the guard test asserts the map's skills exist + validate).
SKILL_HANDOFF: dict[str, str] = {
    "research": "research-brief",
    "product": "prd",
    "architecture": "tech-design",
    "plan": "plan",
    "code-review": "review",
    "security-review": "review",
    "qa-test-strategy": "test-strategy",
    "release": "release",
    "deploy-watch": "deploy-status",
    "incident-response": "incident",
    "marketing": "market-brief",
    "ux-design": "ux-spec",
    "repo-onboarding": "onboarding",
}


def required_fields(artifact_type: str) -> list[str]:
    """The handoff type's schema-required fields, excluding the implicit ``type`` discriminator."""
    schema = handoff.SCHEMAS[artifact_type]
    required = schema.get("required", [])
    return [f for f in required if f != "type"]


def _documents(body_lower: str, field: str) -> bool:
    """A field is documented when the body names it as a frontmatter token — as a word inside a
    backtick span (covers ``field``, ``field[]``, and comma-lists like ``type, feature, status``)
    or as ``field:`` — not merely in prose, so the common words ``feature``/``status`` aren't
    satisfied by an incidental mention."""
    f = field.lower()
    backticked = " ".join(m.group(1) for m in _BACKTICK_SPAN.finditer(body_lower))
    if re.search(rf"\b{re.escape(f)}\b", backticked):
        return True
    return f"{f}:" in body_lower


def handoff_contract_problems(
    plugin_dir: Path | str, mapping: dict[str, str] | None = None
) -> list[str]:
    """Return a problem per skill whose body omits a required field of its handoff type (empty =
    clean). ``mapping`` defaults to :data:`SKILL_HANDOFF`; tests pass a custom map + plugin dir."""
    plugin = Path(plugin_dir)
    mapping = SKILL_HANDOFF if mapping is None else mapping
    problems: list[str] = []
    for skill, artifact_type in sorted(mapping.items()):
        skill_md = plugin / "skills" / skill / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{skill}: SKILL.md not found")
            continue
        if artifact_type not in handoff.SCHEMAS:
            problems.append(f"{skill}: unknown handoff type {artifact_type!r}")
            continue
        try:
            _, body = parse(skill_md.read_text(encoding="utf-8"))
        except FrontmatterError as exc:
            problems.append(f"{skill}: {exc}")
            continue
        body_lower = body.lower()
        missing = [f for f in required_fields(artifact_type) if not _documents(body_lower, f)]
        if missing:
            problems.append(
                f"{skill} ({artifact_type}): body omits required field(s): {', '.join(missing)}"
            )
    return problems


# The SDLC spine phases that must recall vault context before acting (ADR 0033).
SPINE_SKILLS: tuple[str, ...] = (
    "research",
    "product",
    "architecture",
    "plan",
    "develop",
    "code-review",
)
_RECALL_MARKER = "knowledge-recall"  # the pattern each spine phase must link


def recall_problems(plugin_dir: Path | str, skills: tuple[str, ...] = SPINE_SKILLS) -> list[str]:
    """Return a problem per spine skill whose body does not reference the knowledge-recall step
    (ADR 0033). A presence check: the body must link the ``knowledge-recall`` pattern."""
    plugin = Path(plugin_dir)
    problems: list[str] = []
    for skill in skills:
        skill_md = plugin / "skills" / skill / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{skill}: SKILL.md not found")
        elif _RECALL_MARKER not in skill_md.read_text(encoding="utf-8"):
            problems.append(f"{skill}: body does not reference the knowledge-recall step")
    return problems
