from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "dev"))

import audit_digest  # noqa: E402
import run_agent_evals  # noqa: E402
import run_scheduled  # noqa: E402
import run_skill_evals  # noqa: E402
import run_spine_e2e  # noqa: E402
import run_tier1_evals  # noqa: E402
import validate as validate_cli  # noqa: E402


def test_validate_cli_main_ok() -> None:
    # The real plugin passes Tier-0.
    assert validate_cli.main(["validate"]) == 0


def test_validate_cli_missing_dir() -> None:
    assert validate_cli.main(["validate", "/no/such/plugin/dir"]) == 1


def test_run_agent_evals_dry_ok() -> None:
    assert run_agent_evals.main(["run", "--runner", "dry"]) == 0


def test_run_spine_e2e_dry_ok() -> None:
    assert run_spine_e2e.main(["run", "--runner", "dry"]) == 0


def test_run_tier1_evals_dry_ok() -> None:
    # The real plugin's live listing + triggers are well-formed.
    assert run_tier1_evals.main(["run", "--runner", "dry"]) == 0


def test_run_skill_evals_dry_ok() -> None:
    # Every tier2 skill (packs + engineering-standards + deep-review/skill-factory) is wired.
    assert run_skill_evals.main(["run", "--runner", "dry"]) == 0


def test_run_skill_evals_unknown_skill_warns(capsys) -> None:
    # An unknown --skill warns, then dry wiring-checks it (missing files) -> NOT READY -> exit 1.
    assert run_skill_evals.main(["run", "--runner", "dry", "--skill", "does-not-exist"]) == 1
    assert "no tier2_quality contract" in capsys.readouterr().err


def test_build_runners_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown runner"):
        run_agent_evals._build_runners("bogus", "reviewer", _REPO / "plugin", "m")


def test_tier1_build_router_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown runner"):
        run_tier1_evals._build_router("bogus", "m")


def test_skill_build_runners_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown runner"):
        run_skill_evals._build_runners("bogus", "python-patterns", _REPO / "plugin", "m")


def test_run_scheduled_dry_lists_due_jobs(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # A fresh project has no last-run state, so every job is due; --dry runs nothing.
    assert run_scheduled.main(["run", "--repo", str(tmp_path), "--dry"]) == 0
    out = capsys.readouterr().out
    assert "Due jobs:" in out and "kb-maintenance" in out
    assert not (tmp_path / "schedule-state.json").exists()  # dry wrote no state


def test_run_scheduled_force_runs_and_records(tmp_path: Path) -> None:
    # --force runs every job (actions degrade gracefully on an empty repo) and records the run.
    assert run_scheduled.main(["run", "--repo", str(tmp_path), "--force"]) == 0
    assert (tmp_path / ".agentic-forge" / "schedule-state.json").is_file()


def test_run_scheduled_returns_1_when_a_job_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a failing action must make the CLI exit non-zero so a cron/CI gating on it sees the failure.
    def boom(repo: Path) -> str:
        raise RuntimeError("action failed")

    monkeypatch.setitem(run_scheduled._ACTIONS, "kb_maintenance", boom)
    assert run_scheduled.main(["run", "--repo", str(tmp_path), "--force"]) == 1
    assert (tmp_path / ".agentic-forge" / "schedule-state.json").is_file()  # still records outcomes


def test_run_scheduled_none_due_after_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run_scheduled.main(["run", "--repo", str(tmp_path), "--force"])  # records all jobs now
    assert run_scheduled.main(["run", "--repo", str(tmp_path)]) == 0  # nothing due yet
    assert "No jobs due." in capsys.readouterr().out


def test_audit_digest_cli_empty(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert audit_digest.main(["audit", "--repo", str(tmp_path)]) == 0
    assert "no tool-use records" in capsys.readouterr().out


# --- real-runner aggregation / exit-code paths (stubbed transport; no model calls) -----------
# These cover each runner's pass/fail/error aggregation loop — the gate-decision logic that the
# dry-run path does NOT exercise (ultra-review MAJOR: the runners decide ship/no-ship).


class _FakeReport:
    def __init__(self, passed: bool) -> None:
        self.passed = passed

    def summary_line(self) -> str:
        return "fake summary"


class _FakePhase:
    def __init__(self, passed: bool) -> None:
        self.phase = "develop"
        self.passed = passed
        self.checkpoints: list = []


def test_run_skill_evals_real_path_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")  # also covers the subscription warning branch
    monkeypatch.setattr(run_skill_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_skill_evals.skill_eval, "run_skill", lambda *a, **k: _FakeReport(True))
    assert run_skill_evals.main(["run", "--runner", "claude", "--skill", "python-patterns"]) == 0


def test_run_skill_evals_real_path_fail_then_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_skill_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_skill_evals.skill_eval, "run_skill", lambda *a, **k: _FakeReport(False))
    assert run_skill_evals.main(["run", "--runner", "claude", "--skill", "python-patterns"]) == 1

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(run_skill_evals.skill_eval, "run_skill", boom)  # the per-skill ERROR branch
    assert run_skill_evals.main(["run", "--runner", "claude", "--skill", "python-patterns"]) == 1


def test_run_agent_evals_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_agent_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", lambda *a, **k: _FakeReport(True))
    assert run_agent_evals.main(["run", "--runner", "claude"]) == 0
    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", lambda *a, **k: _FakeReport(False))
    assert run_agent_evals.main(["run", "--runner", "claude"]) == 1


def test_run_agent_evals_real_path_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_agent_evals, "_build_runners", lambda *a, **k: (object(), object()))

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", boom)
    assert run_agent_evals.main(["run", "--runner", "claude"]) == 1


def test_run_tier1_evals_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_tier1_evals, "_build_router", lambda *a, **k: object())
    monkeypatch.setattr(
        run_tier1_evals.tier1_runner, "run_tier1", lambda *a, **k: [_FakeReport(True)]
    )
    assert run_tier1_evals.main(["run", "--runner", "claude"]) == 0
    monkeypatch.setattr(
        run_tier1_evals.tier1_runner, "run_tier1", lambda *a, **k: [_FakeReport(False)]
    )
    assert run_tier1_evals.main(["run", "--runner", "claude"]) == 1


def test_run_spine_e2e_real_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        run_spine_e2e.agent_eval, "claude_cli_runner", lambda *a, **k: (lambda *x, **y: "")
    )
    monkeypatch.setattr(
        run_spine_e2e.spine_e2e, "run_scenario", lambda *a, **k: [_FakePhase(True)]
    )
    assert run_spine_e2e.main(["run", "--runner", "claude", "--scenario", "spine"]) == 0
    monkeypatch.setattr(
        run_spine_e2e.spine_e2e, "run_scenario", lambda *a, **k: [_FakePhase(False)]
    )
    assert run_spine_e2e.main(["run", "--runner", "claude", "--scenario", "spine"]) == 1
