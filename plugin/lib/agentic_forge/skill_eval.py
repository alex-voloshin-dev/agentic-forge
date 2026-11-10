"""Automated skill Tier-2 quality runner (ADR 0017).

Run Tier-2 (pass-rate lower bound ``mean - stddev >= 0.8`` over N >= 5 runs) for every skill that
declares ``tier2_quality``. Reuses the agent runner's eval core
(:func:`agent_eval.run_eval_cases`): run the component on its cases, grade each output against the
case assertions with the ``grader`` role, aggregate with ``benchmark``, gate with ``gate``.

Two execution modes:

- **Off-listing knowledge skills** (``engineering-standards``, ``*-patterns``) have no behaviour
  of their own, so they are executed *as the* ``software-engineer`` *with the knowledge loaded*:
  the system prompt is the software-engineer body + ``engineering-standards`` body (+ the pack
  body for a ``*-patterns`` skill), the software-engineer's tools, isolated (it writes code). This
  is the "exercised through the software-engineer's Tier-2" path, made real.
- **On-listing skills** (``deep-review``, ``skill-factory``) are executed directly: the system
  prompt is the skill body, with the skill's own ``allowed-tools``, isolated iff it writes.

A skill is resolved in the plugin first, then in each extra ``skill_roots`` directory — the
repository's maintainer skills, ``<repo>/.claude/skills`` (ADR 0105), where ``skill-factory`` lives
since it stopped shipping (:func:`resolve_skill_dir`). Everything else a run needs — the base role,
``engineering-standards``, the grader, the eval cases' ``files`` — is resolved in the plugin.

The model call is the shared :data:`agent_eval.Runner` seam, so the orchestration is unit-tested
with stub runners; the real run uses the ``claude`` CLI (subscription) or the API.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentic_forge import agent_eval, gate
from agentic_forge.evals import eval_case_problems, load_evals
from agentic_forge.frontmatter import parse as parse_frontmatter

__all__ = [
    "BASE_ROLE",
    "STANDARDS_SKILL",
    "SkillReport",
    "discover_skills_with_tier2",
    "resolve_skill_dir",
    "is_off_listing",
    "build_skill_system",
    "build_skill_baseline_system",
    "skill_tools",
    "is_write_skill",
    "run_skill",
    "check_wiring",
]

BASE_ROLE = "software-engineer"
STANDARDS_SKILL = "engineering-standards"
_DEFAULT_ROLE_TOOLS = "Read, Write, Edit, Bash, Grep, Glob"


@dataclass
class SkillReport:
    """The Tier-2 outcome for one skill (mirrors agent_eval.RoleReport)."""

    skill: str
    runs: int
    benchmark: dict[str, Any]
    gate: gate.GateResult
    gradings: list[dict[str, Any]] = field(default_factory=list)
    thresholds: dict[str, Any] = field(default_factory=dict)  # for the version-over-version check

    @property
    def passed(self) -> bool:
        return self.gate.passed

    def summary_line(self) -> str:
        return gate.format_tier2_summary(
            self.skill, passed=self.passed, benchmark=self.benchmark, reasons=self.gate.reasons
        )

    def evidence_lines(self) -> list[str]:
        """The sessions that produced no measurement, one line each — see
        ``gate.tier2_evidence_lines``."""
        return gate.tier2_evidence_lines(self.benchmark)


def resolve_skill_dir(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> Path:
    """The skill's directory: ``<plugin>/skills/<skill>`` when it has a SKILL.md, else the first
    ``<root>/<skill>`` that does, else the plugin path (so a missing skill is reported where a
    shipped one would be). Plugin first: a shipped skill is never shadowed by a namesake — and
    Tier-0 forbids the namesake (``validation.validate_maintainer_skills``)."""
    shipped = plugin_dir / "skills" / skill
    if (shipped / "SKILL.md").is_file():
        return shipped
    for root in skill_roots:
        if (root / skill / "SKILL.md").is_file():
            return root / skill
    return shipped


def _skill_md(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> Path:
    return resolve_skill_dir(plugin_dir, skill, skill_roots) / "SKILL.md"


def _skill_evals(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> Path:
    return resolve_skill_dir(plugin_dir, skill, skill_roots) / "evals" / "evals.json"


def _role_md(plugin_dir: Path, role: str) -> Path:
    return plugin_dir / "agents" / f"{role}.md"


def _frontmatter(md_path: Path) -> dict[str, Any]:
    fm, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    return fm


def _body(md_path: Path) -> str:
    _, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    return body.strip()


def is_off_listing(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> bool:
    """True if the skill is a loaded-on-demand knowledge skill (``disable-model-invocation``)."""
    md = _skill_md(plugin_dir, skill, skill_roots)
    if not md.is_file():
        return False
    return str(_frontmatter(md).get("disable-model-invocation", "")).strip().lower() == "true"


def discover_skills_with_tier2(plugin_dir: Path, skill_roots: Sequence[Path] = ()) -> list[str]:
    """Every skill (by dir name, sorted) whose contract declares a ``tier2_quality`` threshold —
    in the plugin and in each extra ``skill_roots`` directory (a name counted once)."""
    out: set[str] = set()
    for skills_dir in (plugin_dir / "skills", *skill_roots):
        out.update(_tier2_in(skills_dir))
    return sorted(out)


def _tier2_in(skills_dir: Path) -> list[str]:
    out: list[str] = []
    if not skills_dir.is_dir():
        return out
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        evals_path = skill_dir / "evals" / "evals.json"
        if not evals_path.is_file():
            continue
        try:
            data = load_evals(evals_path)
        except Exception:  # an unloadable contract is a Tier-0 failure, not this runner's job
            continue
        if "tier2_quality" in (data.get("thresholds") or {}):
            out.append(skill_dir.name)
    return out


def build_skill_system(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> str:
    """The system prompt that executes the skill under test (see the module docstring)."""
    if is_off_listing(plugin_dir, skill, skill_roots):
        parts = [
            _body(_role_md(plugin_dir, BASE_ROLE)),
            _body(_skill_md(plugin_dir, STANDARDS_SKILL)),
        ]
        if skill != STANDARDS_SKILL:
            parts.append(_body(_skill_md(plugin_dir, skill, skill_roots)))
        return "\n\n".join(parts)
    return _body(_skill_md(plugin_dir, skill, skill_roots))


def build_skill_baseline_system(
    plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()
) -> str:
    """The without-skill A-B baseline (ADR 0036): the SAME executor with the skill under test
    removed, so the with/without delta isolates the skill's marginal contribution rather than a
    model swap. For an off-listing knowledge skill that's the base role (+ engineering-standards,
    unless the skill under test *is* engineering-standards); for an on-listing skill it's the bare
    base model (empty system)."""
    if is_off_listing(plugin_dir, skill, skill_roots):
        parts = [_body(_role_md(plugin_dir, BASE_ROLE))]
        if skill != STANDARDS_SKILL:
            parts.append(_body(_skill_md(plugin_dir, STANDARDS_SKILL)))
        return "\n\n".join(parts)
    return ""


def skill_tools(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> str:
    """The tools the executing component needs (software-engineer's for knowledge skills)."""
    if is_off_listing(plugin_dir, skill, skill_roots):
        return str(_frontmatter(_role_md(plugin_dir, BASE_ROLE)).get("tools", _DEFAULT_ROLE_TOOLS))
    fm = _frontmatter(_skill_md(plugin_dir, skill, skill_roots))
    return str(fm.get("allowed-tools", "Read, Grep, Glob"))


def is_write_skill(plugin_dir: Path, skill: str, skill_roots: Sequence[Path] = ()) -> bool:
    """True if executing the skill writes files (so it MUST run isolated, never the real repo)."""
    if is_off_listing(plugin_dir, skill, skill_roots):
        return True  # runs the software-engineer, which writes code
    tools = skill_tools(plugin_dir, skill, skill_roots)
    return "Write" in tools or "Edit" in tools


def check_wiring(skill: str, plugin_dir: Path, skill_roots: Sequence[Path] = ()) -> list[str]:
    """Return setup problems for a skill without invoking any model. Empty list means ready."""
    problems: list[str] = []
    md = _skill_md(plugin_dir, skill, skill_roots)
    evals_path = _skill_evals(plugin_dir, skill, skill_roots)
    if not md.is_file():
        problems.append(f"missing SKILL.md: {md}")
    if not evals_path.is_file():
        problems.append(f"missing contract: {evals_path}")
    if not _role_md(plugin_dir, "grader").is_file():
        problems.append("missing grader role: agents/grader.md")
    if problems:
        return problems
    contract = load_evals(evals_path)
    if "tier2_quality" not in (contract.get("thresholds") or {}):
        problems.append(f"{skill}: no tier2_quality threshold")
    problems += eval_case_problems(skill, contract.get("evals") or [], plugin_dir)
    if is_off_listing(plugin_dir, skill, skill_roots):
        # A knowledge skill is executed as the base role with engineering-standards loaded.
        if not _body(md):
            problems.append(f"{skill}: empty SKILL.md body (nothing to load into the executor)")
        if not _role_md(plugin_dir, BASE_ROLE).is_file():
            problems.append(f"{skill}: base role {BASE_ROLE}.md missing (needed to execute it)")
        if not _skill_md(plugin_dir, STANDARDS_SKILL).is_file():
            problems.append(f"{skill}: {STANDARDS_SKILL} skill missing (loaded by the base role)")
    return problems


def run_skill(
    skill: str,
    plugin_dir: Path,
    *,
    run_skill_fn: agent_eval.Runner,
    run_grader_fn: agent_eval.Runner,
    runs: int | None = None,
    workdir: Path | None = None,
    isolate: bool = False,
    with_baseline: bool = False,
    skill_roots: Sequence[Path] = (),
) -> SkillReport:
    """Run a skill's Tier-2 eval: N runs over its cases, graded, aggregated, and gated.

    Isolation is **forced on** for skills whose execution writes (every off-listing knowledge
    skill — it runs the software-engineer — and any on-listing skill with Write/Edit), so a run
    can never touch the real repo, regardless of the caller's ``isolate`` flag.

    ``with_baseline`` (opt-in, ~2x cost) additionally runs each case under the without-skill
    baseline (:func:`build_skill_baseline_system`) so the benchmark carries the A-B pass-rate lift
    and the time-overhead delta, which the contract can gate via ``min_lift`` /
    ``max_overhead_seconds`` (ADR 0036).

    ``skill_roots``: where to look for the skill after the plugin (:func:`resolve_skill_dir`).
    """
    contract = load_evals(_skill_evals(plugin_dir, skill, skill_roots))
    system = build_skill_system(plugin_dir, skill, skill_roots)
    grader_body = _body(_role_md(plugin_dir, "grader"))
    if not isolate and is_write_skill(plugin_dir, skill, skill_roots):
        isolate = True
    thresholds = contract.get("thresholds") or {}
    if runs is not None and runs <= 0:
        raise ValueError("runs must be a positive integer")
    contract_runs = (thresholds.get("tier2_quality") or {}).get("runs") or agent_eval.DEFAULT_RUNS
    n = runs if runs is not None else contract_runs
    cases = contract.get("evals") or []
    baseline = (
        build_skill_baseline_system(plugin_dir, skill, skill_roots) if with_baseline else None
    )
    bench, result, gradings = agent_eval.run_eval_cases(
        system_body=system,
        grader_body=grader_body,
        cases=cases,
        thresholds=thresholds,
        plugin_dir=plugin_dir,
        run_fn=run_skill_fn,
        grader_fn=run_grader_fn,
        runs=n,
        isolate=isolate,
        workdir=workdir,
        baseline_system_body=baseline,
    )
    return SkillReport(
        skill=skill, runs=n, benchmark=bench, gate=result, gradings=gradings, thresholds=thresholds
    )
