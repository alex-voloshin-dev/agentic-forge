"""Dogfood: the real plugin must always pass its own Tier-0 gate.

Any committed component that violates the standard or lacks an evals contract fails
here, so CI catches it without a manual validate run.
"""

from __future__ import annotations

from pathlib import Path

from agentic_forge.validation import validate_plugin

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

SKILL_FACTORY_FILES = [
    "SKILL.md",
    "evals/evals.json",
    "references/skill.md",
    "references/agent.md",
    "references/script.md",
    "references/eval-loop.md",
    "assets/SKILL.template.md",
    "assets/evals.template.json",
    "assets/agent.template.md",
]


def test_plugin_passes_tier0() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.render()


def test_skill_factory_is_complete() -> None:
    sf = PLUGIN / "skills" / "skill-factory"
    missing = [rel for rel in SKILL_FACTORY_FILES if not (sf / rel).is_file()]
    assert not missing, f"skill-factory missing files: {missing}"
