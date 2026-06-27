from __future__ import annotations

import re
from pathlib import Path

from agentic_forge import release
from agentic_forge.spine_e2e import (
    SCENARIOS,
    Phase,
    Scenario,
    SeedItem,
    all_passed,
    check_deploy_status,
    check_incident,
    check_release,
    check_security_review,
    check_test_strategy,
    prepare_scenario,
    run_scenario,
    scenario_wiring,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

TEST_STRATEGY = """---
type: test-strategy
feature: task-priorities
status: draft
test_levels:
  - unit
  - integration
risks:
  - invalid priority value must be rejected
cases:
  - reject an invalid priority
---
# Test strategy
Priority ordering and invalid-priority handling.
"""

SECURITY_REVIEW = """---
type: review
target: user_lookup.py
iteration: 1
verdict: changes
findings:
  - severity: major
    location: user_lookup.py:find_user
    issue: SQL injection via string concatenation
---
# Security review
SQLi in find_user.
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

DEPLOY_STATUS = """---
type: deploy-status
environment: production
pipeline: failing
deploys: []
alerts: {}
action: roll back or halt
---
# Deploy status
Latest deploy failed.
"""

INCIDENT = """---
type: incident
severity: sev1
status: mitigating
impact: checkout returns 503 for all users
timeline:
  - 10:02 alert fired
remediation:
  - roll back the bad deploy
---
# Incident
Total outage.
"""

# A priority-bearing taskstore that keeps the target-repo's existing suite green (mirrors the
# spine guard fixture), so quality-gate's `develop` checkpoint passes.
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


def _sdlc_dir(user: str, repo: Path) -> Path:
    m = re.search(r"docs/sdlc/([\w-]+)/", user)
    assert m, f"no sdlc slug in prompt: {user[:80]}"
    d = repo / "docs" / "sdlc" / m.group(1)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _good_phase(system: str, user: str, repo: Path) -> str:
    """Stub Runner: write the correct artifact for whichever domain phase the prompt describes."""
    if "type: test-strategy" in user:
        (_sdlc_dir(user, repo) / "test-strategy.md").write_text(TEST_STRATEGY, encoding="utf-8")
    elif "security-review.md" in user:
        (_sdlc_dir(user, repo) / "security-review.md").write_text(SECURITY_REVIEW, encoding="utf-8")
    elif "Implement the feature in taskstore.py" in user:
        (repo / "taskstore.py").write_text(PRIORITY_TASKSTORE, encoding="utf-8")
    elif "type: review" in user:  # code-review (after the security-review branch)
        (_sdlc_dir(user, repo) / "review.md").write_text(REVIEW_MD, encoding="utf-8")
    elif "type: release" in user:
        sdlc = _sdlc_dir(user, repo)
        msgs = release.commits_since(repo, "v1.0.0")
        version = release.summarize("1.0.0", msgs).version if msgs else "1.0.1"
        body = (
            "---\ntype: release\nfeature: task-priorities\nstatus: draft\n"
            f"version: {version}\nchangelog:\n  - Added: priority\n---\n# Release {version}\n"
        )
        (sdlc / "release.md").write_text(body, encoding="utf-8")
    elif "type: deploy-status" in user:
        (_sdlc_dir(user, repo) / "deploy-status.md").write_text(DEPLOY_STATUS, encoding="utf-8")
    elif "type: incident" in user:
        (_sdlc_dir(user, repo) / "incident.md").write_text(INCIDENT, encoding="utf-8")
    return "done"


def _noop_phase(system: str, user: str, repo: Path) -> str:
    return "did nothing"


# --- direct checkpoint unit tests (fast, no git) -----------------------------


def _write(repo: Path, slug: str, name: str, text: str) -> None:
    d = repo / "docs" / "sdlc" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_check_test_strategy(tmp_path: Path) -> None:
    assert not check_test_strategy(tmp_path, "f")[0].passed  # missing
    _write(tmp_path, "f", "test-strategy.md", TEST_STRATEGY)
    cps = check_test_strategy(tmp_path, "f", risk_keywords=("invalid", "priorit"))
    assert all(c.passed for c in cps)
    assert [c.name for c in cps] == [
        "test-strategy.md valid",
        "test_levels non-empty",
        "risk area referenced",
    ]


def test_check_test_strategy_missing_risk_keyword(tmp_path: Path) -> None:
    _write(tmp_path, "f", "test-strategy.md", TEST_STRATEGY)
    cps = check_test_strategy(tmp_path, "f", risk_keywords=("nonexistent-keyword",))
    assert not cps[-1].passed  # the risk keyword is not referenced


def test_check_security_review(tmp_path: Path) -> None:
    assert not check_security_review(tmp_path, "f")[0].passed  # missing
    _write(tmp_path, "f", "security-review.md", SECURITY_REVIEW)
    cps = check_security_review(tmp_path, "f", sink_markers=("find_user", "sql"))
    assert all(c.passed for c in cps)
    bad = check_security_review(tmp_path, "f", sink_markers=("nowhere",))
    assert not bad[-1].passed  # the sink marker is not referenced


def test_check_release_exact_and_schema_only(tmp_path: Path) -> None:
    assert not check_release(tmp_path, "f")[0].passed  # missing
    # An artifact that isn't a valid release (deploy-status fields under a release type).
    _write(tmp_path, "f", "release.md", DEPLOY_STATUS.replace("deploy-status", "release"))
    assert not check_release(tmp_path, "f")[0].passed  # invalid as a release
    rel = (
        "---\ntype: release\nfeature: x\nstatus: draft\nversion: 1.2.0\n"
        "changelog:\n  - Added: y\n---\n# Release\n"
    )
    _write(tmp_path, "f", "release.md", rel)
    assert all(c.passed for c in check_release(tmp_path, "f"))  # schema-only: semver + changelog
    assert all(c.passed for c in check_release(tmp_path, "f", expected_version="1.2.0"))
    miss = check_release(tmp_path, "f", expected_version="9.9.9")
    assert not miss[1].passed  # version mismatch


def test_check_deploy_status_and_incident(tmp_path: Path) -> None:
    assert not check_deploy_status(tmp_path, "f", expected_health="failing")[0].passed
    _write(tmp_path, "f", "deploy-status.md", DEPLOY_STATUS)
    assert all(c.passed for c in check_deploy_status(tmp_path, "f", expected_health="failing"))
    assert not check_deploy_status(tmp_path, "f", expected_health="healthy")[-1].passed
    _write(tmp_path, "f", "incident.md", INCIDENT)
    assert all(c.passed for c in check_incident(tmp_path, "f", expected_sev="sev1"))
    assert not check_incident(tmp_path, "f", expected_sev="sev3")[-1].passed


# --- prepare_scenario --------------------------------------------------------


def test_prepare_scenario_seed_tag_commits(tmp_path: Path) -> None:
    scn = Scenario(
        name="t",
        slug="s",
        fixture=None,
        seed=(SeedItem("eval/fixtures/deploy-watch/prod-failing.json", "pipeline.json"),),
        tag="v1.0.0",
        commits=("feat: a", "fix: b"),
        phases=(),
    )
    repo = prepare_scenario(PLUGIN, tmp_path, scn)
    assert (repo / "pipeline.json").is_file()  # seeded to an arbitrary destination
    assert (repo / ".git").is_dir()
    msgs = release.commits_since(repo, "v1.0.0")  # tag + replayed commits are real history
    assert any("feat: a" in m for m in msgs) and any("fix: b" in m for m in msgs)


# --- run_scenario integration (stubbed phases) -------------------------------


def test_run_quality_gate_all_pass(tmp_path: Path) -> None:
    results = run_scenario(
        PLUGIN, SCENARIOS["quality-gate"], run_phase=_good_phase, workspace=tmp_path
    )
    assert [r.phase for r in results] == [
        "qa-test-strategy",
        "develop",
        "security-review",
        "code-review",
        "release",
    ]
    assert all_passed(results), [str(c) for r in results for c in r.checkpoints]


def test_run_ops_incident_all_pass(tmp_path: Path) -> None:
    results = run_scenario(
        PLUGIN, SCENARIOS["ops-incident"], run_phase=_good_phase, workspace=tmp_path
    )
    assert [r.phase for r in results] == ["deploy-watch", "incident-response", "release"]
    assert all_passed(results), [str(c) for r in results for c in r.checkpoints]


def test_run_scenario_fails_with_noop(tmp_path: Path) -> None:
    results = run_scenario(
        PLUGIN, SCENARIOS["ops-incident"], run_phase=_noop_phase, workspace=tmp_path
    )
    assert not all_passed(results)


# --- registry / wiring -------------------------------------------------------


def test_scenarios_registered() -> None:
    assert set(SCENARIOS) == {"spine", "quality-gate", "ops-incident"}
    for scn in SCENARIOS.values():
        assert isinstance(scn, Scenario) and scn.phases


def test_scenario_wiring_clean() -> None:
    for scn in SCENARIOS.values():
        assert scenario_wiring(PLUGIN, scn) == []


def test_scenario_wiring_reports_missing(tmp_path: Path) -> None:
    bad = Scenario(
        name="bad",
        slug="s",
        fixture="eval/fixtures/does-not-exist",
        seed=(SeedItem("eval/fixtures/missing.json", "x.json"),),
        phases=(Phase("no-such-skill", "p", lambda r: []),),
    )
    problems = scenario_wiring(PLUGIN, bad)
    assert any("missing skill" in p for p in problems)
    assert any("missing fixture" in p for p in problems)
    assert any("missing seed source" in p for p in problems)


def test_ops_incident_prompt_neutralizes_live_connector() -> None:
    # The deploy-watch phase must force the in-memory source so a runner-present gh can't shadow it.
    dw = next(p for p in SCENARIOS["ops-incident"].phases if p.skill == "deploy-watch")
    assert "do not use a live" in dw.prompt.lower()
    # And the wiring check enforces it:
    broken = Scenario(
        name="b", slug="s", fixture=None,
        phases=(Phase("deploy-watch", "read the data and write it", lambda r: []),),
    )
    assert any("neutralize live connectors" in p for p in scenario_wiring(PLUGIN, broken))
