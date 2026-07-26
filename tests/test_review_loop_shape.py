"""The shared review-loop shape is a GATE, not a convention (ADR 0067).

Every skill below claims the same contract: fork a reviewer, run the external lens on **its own**
criteria, and exit through `handoff.review_loop_decision`. Nothing enforced that, and the gap has
already shipped twice — `product` was told to call the external reviewer while its `allowed-tools`
had no `Bash` (ADR 0060 §4), then `research` and `ux-design` the same way (ADR 0061). Both were
found by a human sweep, because Tier-0 checks structure, Tier-1 checks routing, and five of the
seven declare no Tier-2 at all.

The mapping is spelled out rather than derived: a skill silently passing the *wrong* kind would
fall back to the CODE criteria (`external_review.KINDS.get(kind, KINDS["code"])`) with every gate
still green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forge import external_review
from agentic_forge.frontmatter import parse as parse_frontmatter

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

# skill -> the external-reviewer kind it must use.
REVIEW_LOOP_SKILLS = {
    "research": "research",
    "product": "product",
    "architecture": "technical",
    "plan": "plan",
    "ux-design": "ux",
    "develop": "code",
    "marketing": "marketing",
}


def _skill(name: str) -> tuple[dict[str, object], str]:
    raw = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    fm, body = parse_frontmatter(raw)
    return fm, " ".join(body.split())  # normalise wrapping: the body wraps mid-sentence


@pytest.mark.parametrize("skill", sorted(REVIEW_LOOP_SKILLS))
def test_skill_can_reach_the_tools_its_body_calls(skill: str) -> None:
    # `allowed-tools` is a real restriction: without Bash the library calls in the body are dead
    # instructions, and without Task the loop cannot fork a reviewer.
    tools = str(_skill(skill)[0].get("allowed-tools", ""))
    assert "Bash" in tools, f"{skill} calls lib functions but cannot run them"
    assert "Task" in tools, f"{skill} must fork a reviewer"


@pytest.mark.parametrize("skill", sorted(REVIEW_LOOP_SKILLS))
def test_skill_exits_through_the_shared_rule(skill: str) -> None:
    body = _skill(skill)[1]
    assert "review_loop_decision" in body, f"{skill} does not use the shared exit criterion"
    assert "escalate" in body, f"{skill} does not describe the escalate exit"


@pytest.mark.parametrize(("skill", "kind"), sorted(REVIEW_LOOP_SKILLS.items()))
def test_skill_passes_its_own_external_reviewer_kind(skill: str, kind: str) -> None:
    body = _skill(skill)[1]
    assert kind in external_review.KINDS, f"{kind} is not a real KINDS key"
    assert f'"{kind}"' in body, f"{skill} must call external_review.review(..., {kind!r})"
    assert f"--kind {kind}" in body, f"{skill} must document the repo-side --kind {kind}"


def test_every_kind_is_claimed_by_exactly_one_skill() -> None:
    # A kind nobody uses is dead criteria; two skills sharing one means a phase is reviewed on
    # another phase's failure modes.
    assert sorted(REVIEW_LOOP_SKILLS.values()) == sorted(external_review.KINDS)
