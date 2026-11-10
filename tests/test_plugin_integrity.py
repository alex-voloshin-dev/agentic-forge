"""Dogfood: the real plugin must always pass its own Tier-0 gate.

Any committed component that violates the standard or lacks an evals contract fails
here, so CI catches it without a manual validate run.
"""

from __future__ import annotations

from pathlib import Path

from agentic_forge.validation import (
    maintainer_skills_dir,
    validate_maintainer_skills,
    validate_plugin,
)

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"

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
ENGINE_ROLES = [
    "reviewer",
    "grader",
    "software-engineer",
    "architect",
    "security-engineer",
    "qa-engineer",
]
ENGINE_PATTERNS = ["handoff.md", "review-loop.md", "worktree.md"]


def test_plugin_passes_tier0() -> None:
    report = validate_plugin(PLUGIN)
    assert report.ok, report.render()


def test_validated_tiers_match_the_agent_set() -> None:
    # The runtime tier policy (ADR 0046) must name exactly the real agents: a missing entry lets a
    # new agent default silently; a stale entry is dead config nothing else flags.
    from agentic_forge import models

    stems = {p.stem for p in (PLUGIN / "agents").glob("*.md")}
    assert set(models.VALIDATED_TIERS) == stems


def test_maintainer_skills_pass_tier0() -> None:
    report = validate_maintainer_skills(REPO, PLUGIN)
    assert report.ok, report.render()


def test_skill_factory_is_complete() -> None:
    sf = maintainer_skills_dir(REPO) / "skill-factory"
    missing = [rel for rel in SKILL_FACTORY_FILES if not (sf / rel).is_file()]
    assert not missing, f"skill-factory missing files: {missing}"


def test_skill_factory_is_a_maintainer_skill_and_does_not_ship() -> None:
    """ADR 0105: it builds THIS repository's components, so it lives in `.claude/skills/` and
    is in no user's listing."""
    assert (maintainer_skills_dir(REPO) / "skill-factory" / "SKILL.md").is_file()
    assert not (PLUGIN / "skills" / "skill-factory").exists()


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
