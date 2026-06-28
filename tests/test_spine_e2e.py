from __future__ import annotations

from pathlib import Path

from agentic_forge import spine_e2e, stacks
from agentic_forge.spine_e2e import (
    PHASES,
    SPINE,
    Checkpoint,
    PhaseResult,
    all_passed,
    check_architecture,
    check_code_review,
    check_develop,
    check_plan,
    check_product,
    check_research,
    prepare_scenario,
    repo_tests_pass,
    run_scenario,
    skill_body,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

TECH_DESIGN = """---
type: tech-design
feature: task-priorities
status: approved
decisions:
  - Ordered priority enum mapped to a sort rank
components:
  - Task
  - TaskStore.add
risks:
  - Reordering list() could surprise callers
---
# Tech design
"""

REVIEW_MD = """---
type: review
target: taskstore.py
iteration: 1
verdict: approve
findings: []
---
# Review
LGTM.
"""

ADR = "# ADR 1\n## Context\nc\n## Decision\nd\n## Alternatives considered\na\n## Consequences\nq\n"

RESEARCH_BRIEF = """---
type: research-brief
feature: task-priorities
status: final
date: "2026-06-21"
sources:
  - https://example.com/x
---
# Research brief
findings + recommendation
"""

PRD_MD = """---
type: prd
feature: task-priorities
status: approved
goals:
  - Assign a priority to a task
non_goals:
  - Per-user default priorities
metrics:
  - Tasks can be ordered by priority
acceptance:
  - add() accepts a priority, default normal
---
# PRD
As a user, I want priorities.
"""

PLAN_MD = """---
type: plan
feature: task-priorities
status: approved
tasks:
  - id: T1
    title: Add priority
checkpoints:
  - tests green
deferred:
  - per-user defaults
---
# Plan
"""

PRIORITY_TASKSTORE = '''"""taskstore with priority."""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import count

_RANK = {"low": 0, "normal": 1, "high": 2}


@dataclass
class Task:
    id: int
    title: str
    priority: str = "normal"
    done: bool = False


@dataclass
class TaskStore:
    _tasks: list = field(default_factory=list)
    _ids: count = field(default_factory=lambda: count(1))

    def add(self, title, priority="normal"):
        if not title or not title.strip():
            raise ValueError("title must be non-empty")
        if priority not in _RANK:
            raise ValueError("invalid priority")
        t = Task(id=next(self._ids), title=title.strip(), priority=priority)
        self._tasks.append(t)
        return t.id

    def complete(self, task_id):
        for t in self._tasks:
            if t.id == task_id:
                t.done = True
                return
        raise KeyError(task_id)

    def list(self, include_done=False):
        items = [t for t in self._tasks if include_done or not t.done]
        return sorted(items, key=lambda t: -_RANK[t.priority])
'''


def _good_phase(system: str, user: str, repo: Path) -> str:
    """Stub Runner: materialize correct artifacts for whichever phase the prompt describes."""
    sdlc = repo / "docs" / "sdlc" / "task-priorities"
    sdlc.mkdir(parents=True, exist_ok=True)
    if "research-brief.md (frontmatter" in user:
        (sdlc / "research-brief.md").write_text(RESEARCH_BRIEF, encoding="utf-8")
    elif "prd.md (frontmatter" in user:
        (sdlc / "prd.md").write_text(PRD_MD, encoding="utf-8")
    elif "tech-design.md (frontmatter" in user:
        (sdlc / "tech-design.md").write_text(TECH_DESIGN, encoding="utf-8")
        (sdlc / "adr-001-priority.md").write_text(ADR, encoding="utf-8")
    elif "plan.md (frontmatter" in user:
        (sdlc / "plan.md").write_text(PLAN_MD, encoding="utf-8")
    elif "Implement the feature in taskstore.py" in user:
        (repo / "taskstore.py").write_text(PRIORITY_TASKSTORE, encoding="utf-8")
    elif "Write a verdict" in user:
        (sdlc / "review.md").write_text(REVIEW_MD, encoding="utf-8")
    return "done"


def _noop_phase(system: str, user: str, repo: Path) -> str:
    return "did nothing"


# --- spine workspace (prepare_scenario for the SPINE scenario) ---------------


def test_spine_workspace_copies_and_git_inits(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    assert (repo / "taskstore.py").is_file()
    assert (repo / "FEATURE_REQUEST.md").is_file()  # research's starting input
    assert not (repo / "docs" / "sdlc" / "task-priorities" / "prd.md").exists()  # not seeded
    assert (repo / ".git").is_dir()


def test_spine_workspace_reusable(tmp_path: Path) -> None:
    # Re-running against the same dest must not crash (rmtree the prior repo first).
    prepare_scenario(PLUGIN, tmp_path, SPINE)
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    assert (repo / "taskstore.py").is_file()


def test_spine_workspace_detects_python(tmp_path: Path) -> None:
    # By-stack (ADR 0015): the E2E target repo must be detected as the stack the spine
    # implements, so develop/code-review load python-patterns + the right toolchain.
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    profile = stacks.primary(repo)
    assert profile.stack_id == "python"
    assert profile.pack == "python-patterns"


def test_check_research_product_plan(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    sdlc = repo / "docs" / "sdlc" / "task-priorities"
    sdlc.mkdir(parents=True, exist_ok=True)
    assert not check_research(repo)[0].passed
    assert not check_product(repo)[0].passed
    assert not check_plan(repo)[0].passed
    (sdlc / "research-brief.md").write_text(RESEARCH_BRIEF, encoding="utf-8")
    (sdlc / "prd.md").write_text(PRD_MD, encoding="utf-8")
    (sdlc / "plan.md").write_text(PLAN_MD, encoding="utf-8")
    assert check_research(repo)[0].passed
    assert check_product(repo)[0].passed
    assert check_plan(repo)[0].passed


# --- checkpoints -------------------------------------------------------------


def test_check_architecture_pass_and_fail(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    assert not PhaseResult("a", check_architecture(repo)).passed  # nothing produced yet
    sdlc = repo / "docs" / "sdlc" / "task-priorities"
    sdlc.mkdir(parents=True, exist_ok=True)
    (sdlc / "tech-design.md").write_text(TECH_DESIGN, encoding="utf-8")
    (sdlc / "adr-001.md").write_text(ADR, encoding="utf-8")
    assert all(c.passed for c in check_architecture(repo))


def test_check_develop_pass_and_fail(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    # baseline has no priority -> fail; tests still run
    cps = check_develop(repo)
    assert not cps[0].passed  # no 'priority' yet
    (repo / "taskstore.py").write_text(PRIORITY_TASKSTORE, encoding="utf-8")
    cps = check_develop(repo)
    assert all(c.passed for c in cps)  # priority present + existing suite passes


def test_check_develop_failing_suite(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    # Has the priority marker but is broken Python -> import fails -> suite fails.
    broken = "def add(priority='x'):\n    return (  # broken\n"
    (repo / "taskstore.py").write_text(broken, encoding="utf-8")
    cps = check_develop(repo)
    assert cps[0].passed  # priority= marker present
    assert not cps[1].passed  # suite is broken


def test_check_develop_skip_tests(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    cps = check_develop(repo, run_tests=False)
    assert [c.name for c in cps] == ["priority implemented in taskstore"]


def test_repo_tests_pass_true(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    assert repo_tests_pass(repo) is True


def test_check_code_review_missing_invalid_and_valid(tmp_path: Path) -> None:
    repo = prepare_scenario(PLUGIN, tmp_path, SPINE)
    sdlc = repo / "docs" / "sdlc" / "task-priorities"
    assert not check_code_review(repo)[0].passed  # missing (dir absent)
    sdlc.mkdir(parents=True, exist_ok=True)
    (sdlc / "review.md").write_text("not an artifact", encoding="utf-8")
    assert not check_code_review(repo)[0].passed  # invalid
    (sdlc / "review.md").write_text(REVIEW_MD, encoding="utf-8")
    cps = check_code_review(repo)
    assert len(cps) == 2 and all(c.passed for c in cps)  # valid + verdict


# --- run_scenario (spine) ---------------------------------------------------


def test_run_scenario_spine_all_pass_with_good_stub(tmp_path: Path) -> None:
    results = run_scenario(PLUGIN, SPINE, run_phase=_good_phase, workspace=tmp_path)
    assert [r.phase for r in results] == list(PHASES)
    assert all_passed(results), [str(c) for r in results for c in r.checkpoints]


def test_run_scenario_spine_fails_with_noop_stub(tmp_path: Path) -> None:
    results = run_scenario(PLUGIN, SPINE, run_phase=_noop_phase, workspace=tmp_path)
    assert not all_passed(results)


# --- helpers / wiring --------------------------------------------------------


def test_skill_body_strips_frontmatter() -> None:
    body = skill_body(PLUGIN, "architecture")
    assert "Architecture" in body and "name:" not in body.splitlines()[0]


def test_all_passed_empty_is_false() -> None:
    assert all_passed([]) is False
    assert PhaseResult("x", []).passed is False


def test_checkpoint_str() -> None:
    assert "[ok ]" in str(Checkpoint("a", True))
    assert "[FAIL]" in str(Checkpoint("b", False, "why"))
    assert "why" in str(Checkpoint("b", False, "why"))


def test_phase_prompts_cover_all_phases() -> None:
    # _phase_prompt is exercised via run_e2e, but assert each phase has distinct guidance.
    prompts = {ph: spine_e2e._phase_prompt(ph) for ph in PHASES}
    assert "research-brief.md (frontmatter" in prompts["research"]
    assert "prd.md (frontmatter" in prompts["product"]
    assert "tech-design.md (frontmatter" in prompts["architecture"]
    assert "plan.md (frontmatter" in prompts["plan"]
    assert "Implement the feature in taskstore.py" in prompts["develop"]
    assert "Write a verdict" in prompts["code-review"]


def test_expected_release_version_from_real_git_history(tmp_path: Path) -> None:
    # de-tautologised (H4): build the quality-gate's git history and assert the LITERAL bump,
    # not a value recomputed via release.summarize (as check_release's own test does).
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    spine_e2e._git(repo, "init", "-q", "-b", "main")
    spine_e2e._git(repo, "add", "-A")
    spine_e2e._commit(repo, "baseline")
    spine_e2e._git(repo, "tag", "v1.0.0")
    # no commits since the tag -> no release
    assert spine_e2e.expected_release_version(repo, "1.0.0", "v1.0.0") is None
    # a feat after the tag -> minor bump 1.0.0 -> 1.1.0 (independent of summarize being re-run here)
    spine_e2e._commit(repo, "feat: add task priority", allow_empty=True)
    spine_e2e._commit(repo, "fix: clamp invalid priority", allow_empty=True)
    assert spine_e2e.expected_release_version(repo, "1.0.0", "v1.0.0") == "1.1.0"


def test_check_develop_rejects_comment_only_marker(tmp_path: Path) -> None:
    # H5: a `# priority=` comment must NOT satisfy the implementation marker (it's not code).
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "taskstore.py").write_text(
        "# priority= TODO wire this up later\nclass TaskStore:\n    pass\n", encoding="utf-8"
    )
    cps = spine_e2e.check_develop(repo, run_tests=False)
    assert cps[0].name == "priority implemented in taskstore" and not cps[0].passed


def test_check_develop_accepts_code_marker_with_trailing_comment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "taskstore.py").write_text(
        "def add(self, t):\n    self.priority = t  # store the priority\n", encoding="utf-8"
    )
    cps = spine_e2e.check_develop(repo, run_tests=False)
    assert cps[0].passed  # `.priority` on a real code line counts despite the trailing comment
