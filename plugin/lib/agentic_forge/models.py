"""Model tiering (ADR 0043): resolve which model a component runs on.

Cheaper models (sonnet / haiku) for simpler work, the strongest (opus) for hard work. Tiering is
**opt-in** via ``settings.models`` and **validated by the eval gates** — Tier-1 / Tier-2 are
model-dependent, so a downgrade only ships where the component still passes its gate at the cheaper
tier. With an empty ``settings.models`` every component resolves to the global ``default`` (no
behaviour change).
"""

from __future__ import annotations

__all__ = ["TIERS", "model_for"]

# Tier name -> model id. Model ids per the environment: Opus 4.8 / Sonnet 4.6 / Haiku 4.5.
TIERS: dict[str, str] = {
    "default": "claude-opus-4-8",
    "simple": "claude-sonnet-4-6",
    "cheap": "claude-haiku-4-5-20251001",
}


def model_for(component: str, models: dict[str, str], *, default: str) -> str:
    """The model id for ``component``: a per-component entry in ``models`` wins — its value is a
    **tier name** (resolved via :data:`TIERS`) or a **model id** (used as-is) — otherwise the global
    ``default`` (e.g. the runner's ``--model``). Unknown component -> ``default``."""
    value = models.get(component)
    if not value:  # unset or empty -> the global default (self-defensive: never return "")
        return default
    return TIERS.get(value, value)
