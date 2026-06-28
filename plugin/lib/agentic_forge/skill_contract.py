"""Guards on skill bodies (ADR 0032 / ADR 0033).

The live Tier-3 sweep showed skills whose body lists the domain fields but omits the
schema-required identity fields (`ux-design` had `flows`/`screens` but not `feature`/`status`), so
the model emits an artifact `handoff.load_artifact` rejects. This module:

- maps each artifact-producing skill to the handoff `type`(s) it produces and checks the body
  documents every required field of each type (`handoff_contract_problems`, ADR 0032);
- checks each SDLC spine phase links the knowledge-recall step (`recall_problems`, ADR 0033).

Both are deterministic floors against skill-body ↔ contract drift, not proofs of correct usage
(that is the eval tiers' job). See docs/architecture/quality-hardening.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import handoff
from .frontmatter import FrontmatterError, parse

__all__ = [
    "SKILL_HANDOFF",
    "SPINE_SKILLS",
    "required_fields",
    "handoff_contract_problems",
    "recall_problems",
]

_BACKTICK_SPAN = re.compile(r"`([^`]*)`")

# Skill name -> the handoff `type`(s) it produces (a tuple when a skill emits more than one). An
# artifact-producing skill missing here is a deliberate, reviewable omission (the guard test
# asserts the map's skills exist + validate). `develop`/`knowledge`/`deep-review` emit no artifact.
SKILL_HANDOFF: dict[str, str | tuple[str, ...]] = {
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
    "marketing": ("market-brief", "marketing-strategy"),
    "ux-design": "ux-spec",
    "repo-onboarding": "onboarding",
}


def required_fields(artifact_type: str) -> list[str]:
    """The handoff type's schema-required fields, excluding the implicit ``type`` discriminator."""
    schema = handoff.SCHEMAS[artifact_type]
    required = schema.get("required", [])
    return [f for f in required if f != "type"]


def _documents(body_lower: str, field: str) -> bool:
    """A field is documented when the body names it as a frontmatter token: as a whole word inside
    a backtick span (covers ``field``, ``field[]``, and comma-lists like ``type, feature, status``)
    or as ``field:`` at the **start of a line** (a YAML/list context). Not satisfied by bare prose
    or a hyphenated path token (``feature-slug``), so the common words ``feature``/``status`` aren't
    matched incidentally."""
    f = re.escape(field.lower())
    backticked = " ".join(m.group(1) for m in _BACKTICK_SPAN.finditer(body_lower))
    # whole word, but not a hyphenated form like `feature-slug`; `_` stays a word char, so
    # `test_levels` still won't match `levels`.
    if re.search(rf"\b{f}\b(?![-\w])", backticked):
        return True
    return bool(re.search(rf"(?m)^\s*{f}:", body_lower))


def handoff_contract_problems(
    plugin_dir: Path | str, mapping: dict[str, str | tuple[str, ...]] | None = None
) -> list[str]:
    """Return a problem per skill whose body omits a required field of a handoff type it produces
    (empty = clean). ``mapping`` defaults to :data:`SKILL_HANDOFF`."""
    plugin = Path(plugin_dir)
    mapping = SKILL_HANDOFF if mapping is None else mapping
    problems: list[str] = []
    for skill, value in sorted(mapping.items(), key=lambda kv: kv[0]):
        skill_md = plugin / "skills" / skill / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{skill}: SKILL.md not found")
            continue
        try:
            _, body = parse(skill_md.read_text(encoding="utf-8"))
        except FrontmatterError as exc:
            problems.append(f"{skill}: {exc}")
            continue
        body_lower = body.lower()
        types = (value,) if isinstance(value, str) else tuple(value)
        for artifact_type in types:
            if artifact_type not in handoff.SCHEMAS:
                problems.append(f"{skill}: unknown handoff type {artifact_type!r}")
                continue
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
# The exact link a spine body must carry — a markdown link to the pattern, not a bare substring
# (so a mention in a comment or the frontmatter description can't satisfy the guard).
_RECALL_LINK = "](../../patterns/knowledge-recall.md)"


def recall_problems(plugin_dir: Path | str, skills: tuple[str, ...] = SPINE_SKILLS) -> list[str]:
    """Return a problem per spine skill whose **body** does not link the knowledge-recall pattern
    (ADR 0033)."""
    plugin = Path(plugin_dir)
    problems: list[str] = []
    for skill in skills:
        skill_md = plugin / "skills" / skill / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{skill}: SKILL.md not found")
            continue
        try:
            _, body = parse(skill_md.read_text(encoding="utf-8"))
        except FrontmatterError as exc:
            problems.append(f"{skill}: {exc}")
            continue
        if _RECALL_LINK not in body:
            problems.append(f"{skill}: body does not link the knowledge-recall pattern")
    return problems
