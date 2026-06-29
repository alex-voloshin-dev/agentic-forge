from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "dev"))

import audit_digest  # noqa: E402
import diagnostics_digest  # noqa: E402
import external_review as external_review_cli  # noqa: E402
import pr_watch as pr_watch_cli  # noqa: E402
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


def test_run_skill_evals_empty_discovery_returns_1(monkeypatch: pytest.MonkeyPatch) -> None:
    # nothing to evaluate must NOT be a vacuous exit 0 (a rename emptying discovery would hide it).
    monkeypatch.setattr(run_skill_evals.skill_eval, "discover_skills_with_tier2", lambda d: [])
    assert run_skill_evals.main(["run", "--runner", "dry"]) == 1


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


# --- external_review CLI (ADR 0042) ------------------------------------------

_CHANGES = {"verdict": "changes", "findings": [
    {"severity": "major", "location": "a:1", "issue": "bug", "suggestion": "fix"},
    {"severity": "nit", "location": "b:2", "issue": "style"},  # no suggestion -> render branch
]}
_APPROVE = {"verdict": "approve", "findings": []}


def _target(tmp_path: Path) -> Path:
    t = tmp_path / "diff.txt"
    t.write_text("some code", encoding="utf-8")
    return t


def _ext(monkeypatch: pytest.MonkeyPatch, *, available: bool, result: object) -> None:
    monkeypatch.setattr(external_review_cli.external_review, "is_available", lambda c: available)
    monkeypatch.setattr(external_review_cli.external_review, "review", lambda *a, **k: result)


def _run_ext(tmp_path: Path, *extra: str) -> int:
    argv = ["x", "--repo", str(tmp_path), "--target", str(_target(tmp_path)), *extra]
    return external_review_cli.main(argv)


def test_external_review_disabled_skips(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert _run_ext(tmp_path) == 0  # off by default, no --force
    assert "disabled" in capsys.readouterr().out


def test_external_review_cli_absent_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _ext(monkeypatch, available=False, result=None)
    assert _run_ext(tmp_path, "--force") == 0
    assert "not found" in capsys.readouterr().out


def test_external_review_verdict_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ext(monkeypatch, available=True, result=_APPROVE)
    assert _run_ext(tmp_path, "--force") == 0  # approve -> 0
    _ext(monkeypatch, available=True, result=_CHANGES)
    assert _run_ext(tmp_path, "--force") == 1  # changes -> 1


def test_external_review_unparseable_returns_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ext(monkeypatch, available=True, result=None)
    assert _run_ext(tmp_path, "--force") == 1


def test_external_review_writes_valid_review_md(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agentic_forge import handoff

    _ext(monkeypatch, available=True, result=_CHANGES)
    out = tmp_path / "review.md"
    assert _run_ext(tmp_path, "--out", str(out), "--force") == 1
    art = handoff.load_artifact(out, expected_type="review")  # the emitted handoff is schema-valid
    assert art.header["verdict"] == "changes"
    assert art.header["findings"] and art.header["findings"][0]["severity"] == "major"  # in header


def test_external_review_missing_target_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    missing = str(tmp_path / "nope.txt")
    rc = external_review_cli.main(["x", "--repo", str(tmp_path), "--target", missing, "--force"])
    assert rc == 1 and "not found" in capsys.readouterr().err  # graceful, no crash


def test_external_review_command_override_reaches_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, str] = {}

    def fake_review(target: str, kind: str, *, command: str, workdir: object) -> object:
        seen["command"] = command
        return _APPROVE

    monkeypatch.setattr(external_review_cli.external_review, "is_available", lambda c: True)
    monkeypatch.setattr(external_review_cli.external_review, "review", fake_review)
    assert _run_ext(tmp_path, "--command", "my-reviewer", "--force") == 0
    assert seen["command"] == "my-reviewer"


def test_diagnostics_digest_cli_empty(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert diagnostics_digest.main(["diag", "--repo", str(tmp_path)]) == 0
    assert "no events" in capsys.readouterr().out


def test_runner_records_diagnostic_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With the flag on, a runner crash is captured into ./.agentic-forge/diagnostics.jsonl.
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    monkeypatch.chdir(tmp_path)  # so the emitter's "." resolves to an isolated dir
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_skill_evals, "_build_runners", lambda *a, **k: (object(), object()))

    def boom(*a: object, **k: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(run_skill_evals.skill_eval, "run_skill", boom)
    assert run_skill_evals.main(["run", "--runner", "claude", "--skill", "python-patterns"]) == 1
    log = tmp_path / ".agentic-forge" / "diagnostics.jsonl"
    assert log.is_file() and "kaboom" in log.read_text()  # the crash was recorded


def test_review_scan_action(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    assert "converged (or none found)" in run_scheduled._review_scan(tmp_path)  # empty -> no events
    feat = tmp_path / "docs" / "sdlc" / "feat"
    feat.mkdir(parents=True)
    (feat / "review.md").write_text(
        "---\ntype: review\ntarget: feat.py\niteration: 3\nverdict: changes\n---\nx\n",
        encoding="utf-8",
    )
    assert "recorded 1" in run_scheduled._review_scan(tmp_path)  # non-converged loop captured
    assert (tmp_path / ".agentic-forge" / "diagnostics.jsonl").is_file()


# --- real-runner aggregation / exit-code paths (stubbed transport; no model calls) -----------
# These cover each runner's pass/fail/error aggregation loop — the gate-decision logic that the
# dry-run path does NOT exercise (ultra-review MAJOR: the runners decide ship/no-ship).


class _FakeReport:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        # Mirror the real report contract the runners read on a FAIL (diagnostics, ADR 0039):
        # role/skill reports expose `gate.reasons`; tier1 reports expose `reasons` + `skill`.
        self.reasons = ["fake reason"]
        self.skill = "fake-skill"
        self.gate = types.SimpleNamespace(reasons=["fake reason"])

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


def test_run_tier1_evals_crash_returns_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_tier1_evals, "_build_router", lambda *a, **k: object())

    def boom(*a: object, **k: object) -> object:
        raise RuntimeError("mis-wired plugin")

    monkeypatch.setattr(run_tier1_evals.tier1_runner, "run_tier1", boom)
    assert run_tier1_evals.main(["run", "--runner", "claude"]) == 1  # crash -> recorded -> fail


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


# --- model tiering wired into the runners (ADR 0043) -------------------------


def test_agent_eval_uses_model_tier_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentic_forge import models as models_lib

    seen: dict[str, str] = {}
    # settings assigns the reviewer the "simple" tier -> the runner must build it on sonnet
    monkeypatch.setattr(
        run_agent_evals.settings,
        "resolve",
        lambda *a, **k: types.SimpleNamespace(models={"reviewer": "simple"}),
    )

    def fake_build(runner: str, role: str, plugin_dir: object, model: str) -> tuple[object, object]:
        seen[role] = model
        return (object(), object())

    monkeypatch.setattr(run_agent_evals, "_build_runners", fake_build)
    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", lambda *a, **k: _FakeReport(True))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_agent_evals.main(["x", "--runner", "claude", "--role", "reviewer"])
    assert seen["reviewer"] == models_lib.TIERS["simple"]  # the configured tier was applied


def test_tier1_eval_uses_router_tier_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentic_forge import models as models_lib

    seen: dict[str, str] = {}
    # settings assigns the router the "cheap" tier -> the Tier-1 run must use haiku
    monkeypatch.setattr(
        run_tier1_evals.settings,
        "resolve",
        lambda *a, **k: types.SimpleNamespace(models={"router": "cheap"}),
    )

    def fake_router(runner: str, model: str) -> object:
        seen["model"] = model
        return object()

    monkeypatch.setattr(run_tier1_evals, "_build_router", fake_router)
    monkeypatch.setattr(
        run_tier1_evals.tier1_runner, "run_tier1", lambda *a, **k: [_FakeReport(True)]
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_tier1_evals.main(["x", "--runner", "claude"])
    assert seen["model"] == models_lib.TIERS["cheap"]  # the router tier reached _build_router


# --- pr_watch CLI (ADR 0044) -------------------------------------------------

_PR_DATA = {"data": {"repository": {"pullRequest": {
    "number": 42, "mergeable": "MERGEABLE", "headRefName": "feat-x",
    "reviewThreads": {"nodes": [{"id": "T1", "isResolved": False, "comments": {"nodes": [
        {"body": "fix", "path": "a.py", "line": 5, "author": {"login": "rev"}}]}}]},
}}}}


def _pr_fetch(*a: object, **k: object) -> dict:
    return _PR_DATA


def test_pr_watch_dry_plans(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42"], fetch=_pr_fetch
    )
    out = capsys.readouterr().out
    assert rc == 0 and "actionable thread(s)" in out and "T1" in out  # dry plan, no writes


def test_pr_watch_apply_disabled_by_default(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42", "--apply"],
        fetch=_pr_fetch,
    )
    assert rc == 0 and "disabled" in capsys.readouterr().out  # pr_watcher.enabled false by default


def test_pr_watch_apply_runs_when_enabled(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text('{"pr_watcher": {"enabled": true}}', encoding="utf-8")
    pushed: list[bool] = []
    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42", "--apply"],
        fetch=_pr_fetch,
        fixer=lambda t: ("fixed", "done"),
        gh_exec=lambda argv: None,
        push=lambda: pushed.append(True),
    )
    out = capsys.readouterr().out
    assert rc == 0 and "fixed 1" in out and pushed == [True]  # the gated live loop ran


def test_pr_watch_apply_refuses_fork(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text('{"pr_watcher": {"enabled": true}}', encoding="utf-8")
    fork = {"data": {"repository": {"pullRequest": {
        "number": 7, "mergeable": "MERGEABLE", "headRefName": "f", "baseRefName": "main",
        "isCrossRepository": True, "reviewThreads": {"nodes": []},
    }}}}
    pushed: list[bool] = []
    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "7", "--apply"],
        fetch=lambda *a, **k: fork,
        fixer=lambda t: ("fixed", "done"), gh_exec=lambda argv: None,
        push=lambda: pushed.append(True),
    )
    out = capsys.readouterr().out
    assert rc == 0 and "fork" in out and pushed == []  # fork PRs are refused on the apply path


def test_pr_watch_fetch_error_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    def boom(*a: object, **k: object) -> dict:
        raise RuntimeError("gh down")

    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42"], fetch=boom
    )
    assert rc == 1 and "could not fetch" in capsys.readouterr().err  # graceful, no crash


# --- pr-watch scheduled action (1b, ADR 0045) --------------------------------


def test_pr_watch_job_disabled(tmp_path: Path) -> None:
    assert "disabled" in run_scheduled._pr_watch(tmp_path)  # off by default


def test_pr_watch_job_no_repos(tmp_path: Path) -> None:
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text('{"pr_watcher": {"enabled": true}}', encoding="utf-8")
    assert "no repos" in run_scheduled._pr_watch(tmp_path)  # enabled but nothing configured


def test_pr_watch_job_runs_live_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(
        '{"pr_watcher": {"enabled": true, "repos": ["o/r"]}}', encoding="utf-8"
    )
    monkeypatch.setattr(
        run_scheduled, "_run_pr_watch_live", lambda repo, specs: f"ran {len(specs)}"
    )
    assert run_scheduled._pr_watch(tmp_path) == "ran 1"  # enabled + repos -> live branch
