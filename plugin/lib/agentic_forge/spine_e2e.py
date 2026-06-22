"""Tier-3 end-to-end scenario for the SDLC spine thin slice.

Carry one feature (`task-priorities`) through `architecture -> develop -> code-review` on an
**isolated copy** of the taskstore fixture repo, checking per-phase handoff artifacts and that
the implemented code passes the repo's own tests. The model/agent call is a seam
(:data:`agent_eval.Runner`) so the orchestration + checkpoints are unit-tested with stubs; the
real run drives each phase with the `claude` CLI.

Fidelity note: in this environment the plugin's subagents are not registered, so each phase is
approximated as a single CLI call seeded with the phase skill's body (rather than the skill
forking its roles). The checkpoints validate the *artifacts and code*, which is what the Tier-3
scenario gates.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import handoff
from .agent_eval import Runner
from .frontmatter import parse as parse_frontmatter

FEATURE_SLUG = "task-priorities"
FIXTURE_REPO = "eval/fixtures/spine/target-repo"
PRD = "eval/fixtures/spine/prd.md"
PLAN = "eval/fixtures/spine/plan.md"
PHASES = ("research", "product", "architecture", "plan", "develop", "code-review")


@dataclass
class Checkpoint:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        mark = "ok " if self.passed else "FAIL"
        suffix = f" — {self.detail}" if self.detail else ""
        return f"  [{mark}] {self.name}{suffix}"


@dataclass
class PhaseResult:
    phase: str
    checkpoints: list[Checkpoint] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checkpoints) and all(c.passed for c in self.checkpoints)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def prepare_workspace(plugin_dir: Path, dest: Path, *, seed: tuple[str, ...] = ()) -> Path:
    """Copy the fixture repo into ``dest/repo`` and git-init it.

    The full six-phase run seeds nothing — `research` starts from the repo's `FEATURE_REQUEST.md`
    and each phase produces the artifact the next consumes. ``seed`` optionally pre-places
    fixture artifacts (by basename) under ``docs/sdlc/<slug>/`` to start a partial run.
    """
    repo = dest / "repo"
    if repo.exists():  # allow re-running against the same --workspace (a natural debugging move)
        shutil.rmtree(repo)
    shutil.copytree(plugin_dir / FIXTURE_REPO, repo)
    if seed:
        sdlc = repo / "docs" / "sdlc" / FEATURE_SLUG
        sdlc.mkdir(parents=True, exist_ok=True)
        for rel in seed:
            (sdlc / Path(rel).name).write_text(
                (plugin_dir / rel).read_text(encoding="utf-8"), encoding="utf-8"
            )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(
        repo, "-c", "user.email=e2e@local", "-c", "user.name=e2e",
        "commit", "-q", "-m", "baseline",
    )
    return repo


def _valid(path: Path, artifact_type: str) -> bool:
    try:
        handoff.load_artifact(path, expected_type=artifact_type)
        return True
    except handoff.HandoffError:
        return False


def check_architecture(repo: Path) -> list[Checkpoint]:
    sdlc = repo / "docs" / "sdlc" / FEATURE_SLUG
    td = sdlc / "tech-design.md"
    adrs = sorted(sdlc.glob("adr-*.md"))
    return [
        Checkpoint(
            "tech-design.md exists and validates", td.is_file() and _valid(td, "tech-design")
        ),
        Checkpoint("at least one ADR", len(adrs) >= 1, f"{len(adrs)} ADR(s)"),
    ]


def repo_tests_pass(repo: Path) -> bool:
    result = subprocess.run(
        ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def check_develop(repo: Path, *, run_tests: bool = True) -> list[Checkpoint]:
    src = repo / "taskstore.py"
    code = (src.read_text(encoding="utf-8") if src.is_file() else "").lower()
    # An implementation marker, not a bare mention — the baseline docstring says "no notion of
    # priority", which must NOT count as implemented.
    has_priority = any(m in code for m in ("priority=", "priority:", ".priority"))
    cps = [Checkpoint("priority implemented in taskstore", has_priority)]
    if run_tests:
        cps.append(Checkpoint("repo test suite passes", repo_tests_pass(repo)))
    return cps


def check_code_review(repo: Path) -> list[Checkpoint]:
    rv = repo / "docs" / "sdlc" / FEATURE_SLUG / "review.md"
    valid = rv.is_file() and _valid(rv, "review")
    cps = [Checkpoint("review.md exists and validates", valid)]
    if valid:
        verdict = handoff.load_artifact(rv, expected_type="review").header.get("verdict")
        cps.append(Checkpoint("verdict present", verdict in handoff.VERDICTS, str(verdict)))
    return cps


def _artifact_checkpoint(repo: Path, filename: str, artifact_type: str) -> Checkpoint:
    path = repo / "docs" / "sdlc" / FEATURE_SLUG / filename
    ok = path.is_file() and _valid(path, artifact_type)
    return Checkpoint(f"{filename} exists and validates", ok)


def check_research(repo: Path) -> list[Checkpoint]:
    return [_artifact_checkpoint(repo, "research-brief.md", "research-brief")]


def check_product(repo: Path) -> list[Checkpoint]:
    return [_artifact_checkpoint(repo, "prd.md", "prd")]


def check_plan(repo: Path) -> list[Checkpoint]:
    return [_artifact_checkpoint(repo, "plan.md", "plan")]


CHECKS = {
    "research": check_research,
    "product": check_product,
    "architecture": check_architecture,
    "plan": check_plan,
    "develop": check_develop,
    "code-review": check_code_review,
}


def skill_body(plugin_dir: Path, name: str) -> str:
    text = (plugin_dir / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    _, body = parse_frontmatter(text)
    return body.strip()


def _phase_prompt(phase: str) -> str:
    sdlc = f"docs/sdlc/{FEATURE_SLUG}/"
    prompts = {
        "research": (
            f"Your working directory is a checkout of the target repo. Read FEATURE_REQUEST.md and "
            f"the code, research the feature (prior art / options / feasibility), and write "
            f"{sdlc}research-brief.md (frontmatter type: research-brief, feature, status, date, "
            "sources[]) with synthesized findings and a recommendation. No code changes."
        ),
        "product": (
            f"Read {sdlc}research-brief.md and the code. Write the product spec to {sdlc}prd.md "
            "(frontmatter type: prd, feature, status, goals[], non_goals[], metrics[], "
            "acceptance[]) with user stories. Requirements only — no design or code."
        ),
        "architecture": (
            f"Read {sdlc}prd.md and the code, and produce the technical design: write "
            f"{sdlc}tech-design.md (frontmatter type: tech-design, feature, status, decisions, "
            "components, risks) and at least one adr-*.md (Context/Decision/Alternatives/"
            "Consequences) in that directory. Design only — no code changes."
        ),
        "plan": (
            f"Read {sdlc}tech-design.md. Write the work plan to {sdlc}plan.md (frontmatter "
            "type: plan, feature, status, tasks[] with id+deps, checkpoints[], deferred[]). "
            "A plan only — no code."
        ),
        "develop": (
            f"Read {sdlc}plan.md and {sdlc}tech-design.md. Implement the feature in taskstore.py "
            "(priority on add(); list() sorted by priority; preserve existing behavior) and add "
            "tests to test_taskstore.py. Run `python -m pytest -q` and make the whole suite green. "
            "Stay within this working directory."
        ),
        "code-review": (
            f"Review the change to taskstore.py / test_taskstore.py (run `git diff`). Write a "
            f"verdict to {sdlc}review.md with frontmatter: type: review, target, iteration: 1, "
            "verdict (approve|changes), findings[]. Do not modify the code."
        ),
    }
    return prompts[phase]


def run_e2e(plugin_dir: Path, *, run_phase: Runner, workspace: Path) -> list[PhaseResult]:
    """Run the three-phase scenario in an isolated copy and return per-phase checkpoint results."""
    repo = prepare_workspace(plugin_dir, workspace)
    results: list[PhaseResult] = []
    for phase in PHASES:
        run_phase(skill_body(plugin_dir, phase), _phase_prompt(phase), repo)
        results.append(PhaseResult(phase, CHECKS[phase](repo)))
    return results


def all_passed(results: list[PhaseResult]) -> bool:
    return bool(results) and all(r.passed for r in results)


def check_wiring(plugin_dir: Path) -> list[str]:
    """Return setup problems without running anything (the dry-run check)."""
    problems: list[str] = []
    for phase in PHASES:
        if not (plugin_dir / "skills" / phase / "SKILL.md").is_file():
            problems.append(f"missing skill: {phase}")
    for rel in (FIXTURE_REPO, PRD, PLAN):
        if not (plugin_dir / rel).exists():
            problems.append(f"missing fixture: {rel}")
    return problems
