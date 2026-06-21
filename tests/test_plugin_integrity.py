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

# Stage 1 engine deliverables.
ENGINE_ROLES = ["reviewer", "grader", "implementer", "architect"]
ENGINE_PATTERNS = ["handoff.md", "review-loop.md", "worktree.md"]


def test_plugin_passes_tier0() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.render()


def test_skill_factory_is_complete() -> None:
    sf = PLUGIN / "skills" / "skill-factory"
    missing = [rel for rel in SKILL_FACTORY_FILES if not (sf / rel).is_file()]
    assert not missing, f"skill-factory missing files: {missing}"


def test_engine_roles_present_and_gated() -> None:
    agents = PLUGIN / "agents"
    for role in ENGINE_ROLES:
        assert (agents / f"{role}.md").is_file(), f"missing role file: {role}.md"
        contract = agents / "evals" / f"{role}.evals.json"
        assert contract.is_file(), f"missing agent eval contract: {role}.evals.json"


def test_engine_patterns_present() -> None:
    patterns = PLUGIN / "patterns"
    missing = [p for p in ENGINE_PATTERNS if not (patterns / p).is_file()]
    assert not missing, f"missing pattern references: {missing}"
