"""Model tiering (ADR 0043): resolve which model a component runs on.

Cheaper models (sonnet / haiku) for simpler work, the strongest (opus) for hard work. Tiering is
**opt-in** via ``settings.models`` and **validated by the eval gates** — Tier-1 / Tier-2 are
model-dependent, so a downgrade only ships where the component still passes its gate at the cheaper
tier. With an empty ``settings.models`` every component resolves to the global ``default`` (no
behaviour change).
"""

import re

__all__ = [
    "TIERS",
    "VALIDATED_TIERS",
    "model_for",
    "frontmatter_model",
    "set_frontmatter_model",
]

# Tier name -> model id. Model ids per the environment: Opus 4.8 / Sonnet 4.6 / Haiku 4.5.
TIERS: dict[str, str] = {
    "default": "claude-opus-4-8",
    "simple": "claude-sonnet-4-6",
    "cheap": "claude-haiku-4-5-20251001",
}

# The committed runtime tier policy (ADR 0046): the gate-validated tier each subagent role runs at
# in LIVE `Task` delegation. It ships **all-`default`** (no downgrade); a role is promoted to a
# cheaper tier here only after it passes the eval gate at that tier (validate via settings.models +
# the eval gate -> edit here -> `dev/sync_models.py --apply` -> Tier-0 green). It ships with the
# agents, so a clean install is always self-consistent; `frontmatter_model` turns it into the
# `model:` frontmatter value Claude Code reads when delegating.
VALIDATED_TIERS: dict[str, str] = {
    "architect": "default",
    "grader": "default",
    "qa-engineer": "default",
    "reviewer": "default",
    "security-engineer": "default",
    "software-engineer": "default",
}

_MODEL_LINE = re.compile(r"^model:.*$", re.MULTILINE)
# The leading frontmatter block (open '---', the YAML, the closing '---', then the body). Used to
# scope model-line edits to the frontmatter so a `model:`-looking line in the BODY is never touched.
_FM_BLOCK = re.compile(r"\A(---[ \t]*\r?\n)(.*?)(\r?\n---[ \t]*\r?\n?)(.*)\Z", re.DOTALL)


def model_for(component: str, models: dict[str, str], *, default: str) -> str:
    """The model id for ``component``: a per-component entry in ``models`` wins — its value is a
    **tier name** (resolved via :data:`TIERS`) or a **model id** (used as-is) — otherwise the global
    ``default`` (e.g. the runner's ``--model``). Unknown component -> ``default``."""
    value = models.get(component)
    if not value:  # unset or empty -> the global default (self-defensive: never return "")
        return default
    return TIERS.get(value, value)


def frontmatter_model(role: str, tiers: dict[str, str] | None = None) -> str:
    """The ``model:`` frontmatter value for ``role`` under the runtime policy (ADR 0046).

    ``inherit`` when the policy tier is ``default`` (follow the session model — safe, and respects a
    user's ``/model``); else the concrete validated model id (same :data:`TIERS` as the eval path).
    ``tiers`` defaults to :data:`VALIDATED_TIERS`; an unknown role -> ``default`` -> ``inherit``."""
    policy = VALIDATED_TIERS if tiers is None else tiers
    tier = policy.get(role, "default")
    if tier == "default":
        return "inherit"
    return TIERS.get(tier, tier)


def set_frontmatter_model(text: str, value: str) -> str:
    """Return ``text`` with its **frontmatter** ``model:`` line set to ``value``. The edit is scoped
    to the leading frontmatter block, so a ``model:``-looking line in the *body* (e.g. a documented
    frontmatter example) is never rewritten. Raises ``ValueError`` if there is no frontmatter block,
    or no ``model:`` line within it (the sync tool surfaces the gap)."""
    block = _FM_BLOCK.match(text)
    if block is None:
        raise ValueError("no frontmatter block to set 'model:' in")
    opening, fm_yaml, closing, body = block.groups()
    new_fm, n = _MODEL_LINE.subn(f"model: {value}", fm_yaml, count=1)
    if n == 0:
        raise ValueError("no 'model:' frontmatter line to set")
    return f"{opening}{new_fm}{closing}{body}"
