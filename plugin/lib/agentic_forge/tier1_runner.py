"""Tier-1 trigger eval runner on LIVE skill descriptions (ADR 0016).

Build the real always-on skill listing — every **model-invocable** skill's ``name`` +
``description`` (``disable-model-invocation`` skills are off-listing and excluded) — and, for
each skill that declares ``tier1_trigger``, ask the router to classify each of its trigger
prompts against that live listing. Grading is deterministic: a ``should_trigger`` prompt must
select the skill (recall); a ``should_not_trigger`` prompt must NOT (specificity).
**Majority-of-N** sampling (default 5) absorbs router stochasticity. Gated through the shared
pure functions :func:`gate.trigger_metrics` + :func:`gate.tier1_trigger` (recall/specificity
≥ 0.9 from the contract).

The model call is a seam (:data:`agent_eval.Runner` — reused so there is no second transport):
``system`` carries the router instruction + the rendered live listing, ``user`` is the trigger
prompt, and the reply is parsed to a skill name. Orchestration + grading are unit-tested with
stub runners; the real run classifies via the ``claude`` CLI (subscription) or the API.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_forge import gate
from agentic_forge.agent_eval import Runner
from agentic_forge.frontmatter import parse as parse_frontmatter

__all__ = [
    "DEFAULT_RUNS",
    "SkillCard",
    "SkillTrigger",
    "Tier1Report",
    "load_listing",
    "render_listing",
    "build_router_system",
    "parse_selection",
    "majority_selection",
    "load_triggers",
    "eval_skill",
    "run_tier1",
    "check_wiring",
    "all_passed",
]

DEFAULT_RUNS = 5

ROUTER_INSTRUCTION = (
    "You are the skill router for Claude Code. Skills auto-load by how well their description "
    "matches the user's request. Given the available skills and a request, decide which ONE "
    "skill should auto-load. Pick the single best match; if no skill clearly applies, answer "
    "none."
)
ANSWER_FORMAT = (
    "Reply with exactly one skill name from the list above, or the word none. No other text."
)


@dataclass(frozen=True)
class SkillCard:
    """One row of the live router listing."""

    name: str
    description: str


@dataclass(frozen=True)
class SkillTrigger:
    """A skill's Tier-1 contract: its thresholds and trigger prompts."""

    name: str
    thresholds: dict[str, Any]
    should_trigger: list[str]
    should_not_trigger: list[str]
    off_listing: bool = False


@dataclass
class Tier1Report:
    skill: str
    recall: float | None
    specificity: float | None
    passed: bool
    reasons: list[str] = field(default_factory=list)
    should_trigger_hits: list[bool] = field(default_factory=list)
    should_not_trigger_wrong: list[bool] = field(default_factory=list)

    def summary_line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        rc = "n/a" if self.recall is None else f"{self.recall:.3f}"
        sp = "n/a" if self.specificity is None else f"{self.specificity:.3f}"
        suffix = "" if self.passed else "  (" + "; ".join(self.reasons) + ")"
        return f"[{self.skill}] {status}  recall={rc} specificity={sp}{suffix}"


# --- live listing ------------------------------------------------------------


def _frontmatter(md_path: Path) -> dict[str, Any]:
    fm, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    return fm


def _is_off_listing(fm: dict[str, Any]) -> bool:
    return str(fm.get("disable-model-invocation", "")).strip().lower() == "true"


def load_listing(plugin_dir: Path) -> list[SkillCard]:
    """The live always-on listing: model-invocable skills' name+description, sorted by name."""
    cards: list[SkillCard] = []
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return cards
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        fm = _frontmatter(md)
        if _is_off_listing(fm):
            continue
        name = str(fm.get("name") or skill_dir.name)
        cards.append(SkillCard(name, str(fm.get("description") or "").strip()))
    return cards


def render_listing(cards: list[SkillCard]) -> str:
    return "\n".join(f"- {c.name}: {c.description}" for c in cards)


def build_router_system(cards: list[SkillCard]) -> str:
    return f"{ROUTER_INSTRUCTION}\n\nAvailable skills:\n{render_listing(cards)}\n\n{ANSWER_FORMAT}"


# --- routing + grading -------------------------------------------------------


def parse_selection(reply: str, names: list[str]) -> str:
    """Normalize a router reply to a skill name in ``names`` or ``"none"``.

    Scans left to right and returns the first token that is a known skill name or the word
    ``none`` — so "research", "`research`", and "the research skill" all map to ``research``,
    and an empty/unknown reply maps to ``none`` (a non-trigger).
    """
    known = {n.lower(): n for n in names}
    for token in re.findall(r"[a-z0-9-]+", reply.lower()):
        if token in known:
            return known[token]
        if token == "none":
            return "none"
    return "none"


def majority_selection(
    run_fn: Runner, system: str, prompt: str, names: list[str], runs: int, workdir: Path
) -> str:
    """The modal router choice for ``prompt`` over ``runs`` calls (absorbs stochasticity)."""
    picks = [parse_selection(run_fn(system, prompt, workdir), names) for _ in range(runs)]
    return Counter(picks).most_common(1)[0][0]


def load_triggers(plugin_dir: Path) -> list[SkillTrigger]:
    """Every skill that declares a ``tier1_trigger`` threshold, with its trigger prompts."""
    out: list[SkillTrigger] = []
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return out
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        evals_path = skill_dir / "evals" / "evals.json"
        if not evals_path.is_file():
            continue
        data = json.loads(evals_path.read_text(encoding="utf-8"))
        thresholds = data.get("thresholds") or {}
        if "tier1_trigger" not in thresholds:
            continue
        triggers = data.get("triggers") or {}
        md = skill_dir / "SKILL.md"
        off = md.is_file() and _is_off_listing(_frontmatter(md))
        out.append(
            SkillTrigger(
                name=str(data.get("skill_name") or skill_dir.name),
                thresholds=thresholds,
                should_trigger=list(triggers.get("should_trigger") or []),
                should_not_trigger=list(triggers.get("should_not_trigger") or []),
                off_listing=bool(off),
            )
        )
    return out


def eval_skill(
    trig: SkillTrigger,
    names: list[str],
    run_fn: Runner,
    system: str,
    runs: int,
    workdir: Path,
) -> Tier1Report:
    """Measure recall/specificity for one skill against the live listing and gate it."""
    st_hits = [
        majority_selection(run_fn, system, p, names, runs, workdir) == trig.name
        for p in trig.should_trigger
    ]
    sn_wrong = [
        majority_selection(run_fn, system, p, names, runs, workdir) == trig.name
        for p in trig.should_not_trigger
    ]
    measured = gate.trigger_metrics(st_hits, sn_wrong)
    result = gate.tier1_trigger(measured, trig.thresholds)
    return Tier1Report(
        skill=trig.name,
        recall=measured["recall"],
        specificity=measured["specificity"],
        passed=result.passed,
        reasons=result.reasons,
        should_trigger_hits=st_hits,
        should_not_trigger_wrong=sn_wrong,
    )


def run_tier1(
    plugin_dir: Path,
    run_fn: Runner,
    *,
    skills: list[str] | None = None,
    runs: int = DEFAULT_RUNS,
    workdir: Path | None = None,
) -> list[Tier1Report]:
    """Run Tier-1 for the on-listing skills (optionally a subset) against the live listing."""
    if runs <= 0:
        raise ValueError(f"runs must be >= 1, got {runs}")
    cards = load_listing(plugin_dir)
    names = [c.name for c in cards]
    system = build_router_system(cards)
    work = workdir or plugin_dir
    triggers = [t for t in load_triggers(plugin_dir) if skills is None or t.name in skills]
    return [eval_skill(t, names, run_fn, system, runs, work) for t in triggers]


def check_wiring(plugin_dir: Path) -> list[str]:
    """Dry-run readiness: triggers present, on-listing, and the listing is well-formed."""
    problems: list[str] = []
    cards = load_listing(plugin_dir)
    listing_names = {c.name for c in cards}
    if not cards:
        problems.append("live listing is empty (no model-invocable skills found)")
    for card in cards:
        if not card.description:
            problems.append(f"{card.name}: empty description (router can't route on it)")
    for trig in load_triggers(plugin_dir):
        if trig.off_listing:
            problems.append(
                f"{trig.name}: declares tier1_trigger but is disable-model-invocation (off-listing)"
            )
        elif trig.name not in listing_names:
            problems.append(f"{trig.name}: declares tier1_trigger but is not in the live listing")
        if not trig.should_trigger:
            problems.append(f"{trig.name}: no should_trigger prompts")
        if not trig.should_not_trigger:
            problems.append(f"{trig.name}: no should_not_trigger prompts")
    return problems


def all_passed(reports: list[Tier1Report]) -> bool:
    return bool(reports) and all(r.passed for r in reports)
