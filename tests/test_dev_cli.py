from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "dev"))
# The runtime CLIs moved into the SHIPPED tree (ADR 0072) — dev/ keeps only the maintainer
# and eval CLIs, which do not reach an installed user.
sys.path.insert(0, str(_REPO / "plugin" / "bin"))

import external_review as external_review_cli  # noqa: E402
import pr_watch as pr_watch_cli  # noqa: E402
import run_scheduled  # noqa: E402

import audit_digest  # noqa: E402
import diagnostics_bundle as diagnostics_bundle_cli  # noqa: E402
import diagnostics_digest  # noqa: E402
import ralph as ralph_cli  # noqa: E402
import run_agent_evals  # noqa: E402
import run_skill_evals  # noqa: E402
import run_spine_e2e  # noqa: E402
import run_tier1_evals  # noqa: E402
import sync_models as sync_models_cli  # noqa: E402
import validate as validate_cli  # noqa: E402
from agentic_forge import diagnostics, schedule  # noqa: E402


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
    assert (diagnostics.state_root(tmp_path) / schedule.STATE_FILE).is_file()


def test_run_scheduled_returns_1_when_a_job_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a failing action must make the CLI exit non-zero so a cron/CI gating on it sees the failure.
    def boom(repo: Path) -> str:
        raise RuntimeError("action failed")

    monkeypatch.setitem(run_scheduled._ACTIONS, "kb_maintenance", boom)
    assert run_scheduled.main(["run", "--repo", str(tmp_path), "--force"]) == 1
    assert (diagnostics.state_root(tmp_path) / schedule.STATE_FILE).is_file()  # records outcomes


def test_run_scheduled_none_due_after_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run_scheduled.main(["run", "--repo", str(tmp_path), "--force"])  # records all jobs now
    assert run_scheduled.main(["run", "--repo", str(tmp_path)]) == 0  # nothing due yet
    assert "No jobs due." in capsys.readouterr().out


def test_audit_digest_cli_empty(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert audit_digest.main(["audit", "--repo", str(tmp_path)]) == 0
    assert "no tool-use records" in capsys.readouterr().out


def test_diagnostics_bundle_cli_writes_zip(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    repo = tmp_path / "repo"
    (repo / ".agentic-forge").mkdir(parents=True)
    (repo / ".agentic-forge" / "audit.jsonl").write_text("", encoding="utf-8")
    out = tmp_path / "b.zip"
    rc = diagnostics_bundle_cli.main(
        ["diagnostics_bundle", "--repo", str(repo), "--out", str(out),
         "--home", str(tmp_path / "h"), "--days", "0"]
    )
    assert rc == 0 and out.is_file()
    assert "Wrote diagnostics bundle" in capsys.readouterr().out


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
    # On by default (ADR 0057); a repo config can opt out, and then the CLI skips without --force.
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir()
    (cfg / "config.json").write_text('{"external_reviewer": {"enabled": false}}', encoding="utf-8")
    assert _run_ext(tmp_path) == 0
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
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
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
    assert (diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE).is_file()


# --- real-runner aggregation / exit-code paths (stubbed transport; no model calls) -----------
# These cover each runner's pass/fail/error aggregation loop — the gate-decision logic that the
# dry-run path does NOT exercise (ultra-review MAJOR: the runners decide ship/no-ship).


class _FakeReport:
    def __init__(self, passed: bool, *, mean: float = 1.0, max_regression: float | None = None):
        self.passed = passed
        # Mirror the real report contract the runners read on a FAIL (diagnostics, ADR 0039):
        # role/skill reports expose `gate.reasons`; tier1 reports expose `reasons` + `skill`.
        self.reasons = ["fake reason"]
        self.skill = "fake-skill"
        # tier1 reports also expose the no-decision breakdown and its samples (ADR 0084).
        self.invalid_reasons: dict[str, int] = {}
        self.invalid_excerpts: list[str] = []
        self.lost_to: dict[str, int] = {}
        self.bare_collided = 0
        self.evidence_lines = list  # callable returning [] — no samples on a fake report
        self.gate = types.SimpleNamespace(reasons=["fake reason"])
        # version-over-version A/B (ADR 0047): empty thresholds -> version_check is a no-op here.
        self.benchmark = {"run_summary": {"with_skill": {"pass_rate": {"mean": mean}, "n": 5}}}
        tier2 = {} if max_regression is None else {"max_regression": max_regression}
        self.thresholds: dict = {"tier2_quality": tier2} if tier2 else {}

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


# --- sync_models CLI (runtime model routing, ADR 0046) -----------------------


def _agent_file(d: Path, role: str, model_line: str | None) -> Path:
    fm = f"---\nname: {role}\ndescription: x\ntools: Read\n"
    if model_line is not None:
        fm += f"model: {model_line}\n"
    fm += "---\nBody.\n"
    p = d / f"{role}.md"
    p.write_text(fm, encoding="utf-8")
    return p


def test_sync_models_check_clean_skips_malformed(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _agent_file(tmp_path, "grader", "inherit")  # matches policy (default -> inherit)
    (tmp_path / "broken.md").write_text("no frontmatter here", encoding="utf-8")  # skipped
    assert sync_models_cli.main(["sync"], agents_dir=tmp_path) == 0
    assert "all agents match" in capsys.readouterr().out


def test_sync_models_check_reports_drift(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _agent_file(tmp_path, "grader", "claude-opus-4-8")  # drift: policy expects inherit
    assert sync_models_cli.main(["sync"], agents_dir=tmp_path) == 1  # check fails on drift
    assert "drift grader" in capsys.readouterr().err


def test_sync_models_apply_rewrites(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    p = _agent_file(tmp_path, "grader", "claude-opus-4-8")
    assert sync_models_cli.main(["sync", "--apply"], agents_dir=tmp_path) == 0
    assert "model: inherit" in p.read_text(encoding="utf-8")  # rewritten to the policy value
    assert "synced grader" in capsys.readouterr().out


def test_sync_models_apply_without_model_line_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _agent_file(tmp_path, "grader", None)  # no model: line -> drift (None != inherit)
    assert sync_models_cli.main(["sync", "--apply"], agents_dir=tmp_path) == 1
    assert "no 'model:' line" in capsys.readouterr().err


def test_sync_models_apply_never_corrupts_body(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    # frontmatter lacks model:, the body documents one -> --apply must NOT rewrite the body and must
    # report failure (exit 1), not a false "synced" (regression for the ADR 0046 review MAJOR).
    p = tmp_path / "grader.md"
    p.write_text(
        "---\nname: grader\ndescription: x\n---\nExample:\nmodel: cheap\n", encoding="utf-8"
    )
    assert sync_models_cli.main(["sync", "--apply"], agents_dir=tmp_path) == 1
    assert "model: cheap" in p.read_text(encoding="utf-8")  # body line intact, not corrupted
    assert "no 'model:' line" in capsys.readouterr().err


# --- version-over-version A/B helper (ADR 0047) ------------------------------

import _eval_cli  # noqa: E402


class _FakeRep:
    """Minimal stand-in for a Role/Skill report (benchmark + thresholds + passed)."""

    def __init__(self, mean: float, *, passed: bool, max_regression: float | None) -> None:
        self.benchmark = {
            "run_summary": {"with_skill": {"pass_rate": {"mean": mean, "stddev": 0.0}, "n": 5}}
        }
        tier2 = {} if max_regression is None else {"max_regression": max_regression}
        self.thresholds = {"tier2_quality": tier2}
        self.passed = passed


def _prior(path: Path, mean: float) -> None:
    from agentic_forge import benchmark

    benchmark.save_history(
        path, [{"component": "reviewer", "model": "opus", "mean": mean, "stddev": 0.0, "n": 5}]
    )


def _hist(path: Path) -> list:
    from agentic_forge import benchmark

    return benchmark.load_history(path)


def test_version_check_first_run_records_baseline(tmp_path: Path) -> None:
    h = tmp_path / "h.json"
    rep = _FakeRep(0.9, passed=True, max_regression=0.05)
    res = _eval_cli.version_check(
        rep, component="reviewer", model="opus", history_path=h, record=True
    )
    assert res is None  # no prior yet -> skip the check
    assert _hist(h)[0]["mean"] == 0.9  # but the healthy run is recorded as the baseline


def test_version_check_records_when_within_tolerance(tmp_path: Path) -> None:
    h = tmp_path / "h.json"
    _prior(h, 0.90)
    rep = _FakeRep(0.88, passed=True, max_regression=0.05)  # dropped 0.02 -> healthy
    res = _eval_cli.version_check(
        rep, component="reviewer", model="opus", history_path=h, record=True
    )
    assert res is not None and res.passed
    assert len(_hist(h)) == 2  # appended a second baseline


def test_version_check_regression_flagged_and_not_recorded(tmp_path: Path) -> None:
    h = tmp_path / "h.json"
    _prior(h, 0.90)
    rep = _FakeRep(0.70, passed=True, max_regression=0.05)  # dropped 0.20 -> regression
    res = _eval_cli.version_check(
        rep, component="reviewer", model="opus", history_path=h, record=True
    )
    assert res is not None and not res.passed
    assert len(_hist(h)) == 1  # a regressed run never becomes the new baseline


def test_version_check_tier2_failure_not_recorded(tmp_path: Path) -> None:
    h = tmp_path / "h.json"
    rep = _FakeRep(0.9, passed=False, max_regression=0.05)  # failed tier2
    _eval_cli.version_check(rep, component="reviewer", model="opus", history_path=h, record=True)
    assert _hist(h) == []  # a failing run never becomes the baseline


def test_version_check_record_flag_off_never_writes(tmp_path: Path) -> None:
    h = tmp_path / "h.json"
    rep = _FakeRep(0.9, passed=True, max_regression=0.05)
    _eval_cli.version_check(rep, component="reviewer", model="opus", history_path=h, record=False)
    assert _hist(h) == []  # --record off -> nothing persisted


def test_run_agent_evals_version_regression_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a cross-version regression must FAIL the run (exercises the runner's version-check block)
    from agentic_forge import benchmark

    h = tmp_path / "hist.json"
    benchmark.save_history(
        h,
        [{"component": "reviewer", "model": "claude-opus-4-8",
          "mean": 0.95, "stddev": 0.0, "n": 5}],
    )
    rep = _FakeReport(True, mean=0.5, max_regression=0.05)  # dropped 0.45 -> regression
    monkeypatch.setattr(run_agent_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", lambda *a, **k: rep)
    rc = run_agent_evals.main(
        ["run", "--runner", "claude", "--role", "reviewer", "--benchmark-history", str(h)]
    )
    assert rc == 1  # the regression flips an otherwise-passing run to fail


def test_run_skill_evals_version_clean_records_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # a healthy run that beats its prior passes the version check AND records the new baseline
    from agentic_forge import benchmark

    h = tmp_path / "hist.json"
    benchmark.save_history(
        h,
        [{"component": "python-patterns", "model": "claude-opus-4-8",
          "mean": 0.8, "stddev": 0.0, "n": 5}],
    )
    rep = _FakeReport(True, mean=0.95, max_regression=0.05)  # improved -> PASS
    monkeypatch.setattr(run_skill_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_skill_evals.skill_eval, "run_skill", lambda *a, **k: rep)
    rc = run_skill_evals.main(
        ["run", "--runner", "claude", "--skill", "python-patterns",
         "--record", "--benchmark-history", str(h)]
    )
    assert rc == 0
    assert len(benchmark.load_history(h)) == 2  # appended the new healthy baseline


# --- ralph CLI (Ralph loop, ADR 0048) ----------------------------------------


def _task(tmp_path: Path) -> Path:
    t = tmp_path / "TASK.md"
    t.write_text("do the thing", encoding="utf-8")
    return t


def test_ralph_dry_plans(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = ralph_cli.main(["x", "--repo", str(tmp_path), "--task", str(_task(tmp_path))])
    assert rc == 0 and "dry" in capsys.readouterr().out  # plan only, no run


def test_ralph_missing_task_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = ralph_cli.main(["x", "--repo", str(tmp_path), "--task", str(tmp_path / "nope.md")])
    assert rc == 1 and "not found" in capsys.readouterr().err


def test_ralph_apply_done_returns_0(tmp_path: Path) -> None:
    runs: list[int] = []
    rc = ralph_cli.main(
        ["x", "--repo", str(tmp_path), "--task", str(_task(tmp_path)), "--apply",
         "--done-cmd", "true"],
        run_iteration=lambda n: runs.append(n),
        is_done=lambda: True,  # done on the first check
        progressed=lambda: True,
    )
    assert rc == 0 and runs == [1]  # finished in one iteration


def test_ralph_apply_unfinished_with_done_cmd_returns_1(tmp_path: Path) -> None:
    rc = ralph_cli.main(
        ["x", "--repo", str(tmp_path), "--task", str(_task(tmp_path)), "--apply",
         "--done-cmd", "false", "--max-iterations", "2", "--stall-after", "0"],
        run_iteration=lambda n: None,
        is_done=lambda: False,  # never reaches the goal
        progressed=lambda: True,
    )
    assert rc == 1  # a done-cmd was set but never reached -> exit 1 (+ a diagnostics anomaly)


def test_ralph_apply_no_done_cmd_returns_0(tmp_path: Path) -> None:
    rc = ralph_cli.main(
        ["x", "--repo", str(tmp_path), "--task", str(_task(tmp_path)), "--apply",
         "--max-iterations", "2", "--stall-after", "0"],
        run_iteration=lambda n: None,
        is_done=lambda: False,
        progressed=lambda: True,
    )
    assert rc == 0  # no done-cmd -> exhausting the budget is a normal end


def test_run_tier1_evals_with_builtins_records_apart_from_the_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR 0086's condition is a measurement, not the gate: its failures are recorded under
    `tier1-builtins:<skill>` so they never read as a routing regression."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_tier1_evals, "_build_router", lambda *a, **k: object())
    captured: dict[str, object] = {}

    def fake_run(*a: object, **k: object) -> list[object]:
        captured.update(k)
        return [_FakeReport(False)]

    recorded: list[str] = []
    monkeypatch.setattr(run_tier1_evals.tier1_runner, "run_tier1", fake_run)
    monkeypatch.setattr(
        run_tier1_evals._eval_cli, "record_failure", lambda comp, *a, **k: recorded.append(comp)
    )
    assert run_tier1_evals.main(["run", "--runner", "claude", "--with-builtins"]) == 1
    assert captured["namespace"] == "agentic-forge" and captured["extra_cards"]
    assert recorded == ["tier1-builtins:fake-skill"]
    assert "condition: +" in capsys.readouterr().out


def test_run_activation_evals_dry_ok() -> None:
    import run_activation_evals

    assert run_activation_evals.main(["run", "--runner", "dry"]) == 0


def test_run_activation_evals_gates_the_pooled_rate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The verdict is one binomial over the run (ADR 0093): 3/5 + 5/5 pools to 0.800 and passes a
    0.8 floor a per-skill gate would fail; 0/5 + 4/4 pools to 0.444, fails, and is recorded ONCE
    under `tier1b-activation` (not per skill); without a floor the run measures and exits 0."""
    import run_activation_evals
    from agentic_forge import activation as activation_lib
    from agentic_forge.activation import ActivationReport

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_activation_evals, "_cli_runner", lambda *a, **k: object())
    recorded: list[str] = []
    monkeypatch.setattr(
        run_activation_evals._eval_cli, "record_failure",
        lambda comp, *a, **k: recorded.append(comp),
    )
    fake = [ActivationReport("a", 3, 5, 0.6), ActivationReport("b", 5, 5, 1.0)]
    monkeypatch.setattr(activation_lib, "run_activation", lambda *a, **k: fake)
    argv = ["run", "--runner", "claude", "--min-activation", "0.8"]
    assert run_activation_evals.main(argv) == 0
    assert "pooled PASS  activation=0.800 (8/10 over 2 skill(s)" in capsys.readouterr().out
    fake[:] = [ActivationReport("a", 0, 5, 0.0), ActivationReport("b", 4, 4, 1.0)]
    assert run_activation_evals.main(argv) == 1 and recorded == ["tier1b-activation"]
    assert "pooled FAIL  activation=0.444" in capsys.readouterr().out
    fake[:] = [
        ActivationReport("a", 4, 5, 1.0, undetermined=[("Investigate X", "limit hit")]),
        ActivationReport("b", 9, 9, 1.0),
    ]
    assert run_activation_evals.main(argv) == 0  # 1 dead session of 14: excluded, not a miss
    out = capsys.readouterr().out
    assert "never ran [a] Investigate X: limit hit" in out and "1 of 14 never ran" in out
    assert run_activation_evals.main(["run", "--runner", "claude"]) == 0  # measure only
    assert "pooled ----" in capsys.readouterr().out


# --- the PR watcher's undetermined outcome, bounds and honest failures (audit 2026-09) -------

import json  # noqa: E402
import subprocess  # noqa: E402

from agentic_forge import ops, pr_watch  # noqa: E402


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def _enable(tmp_path: Path, extra: str = "") -> None:
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.json").write_text(
        '{"pr_watcher": {"enabled": true' + extra + "}}", encoding="utf-8"
    )


def _log(tmp_path: Path) -> str:
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    return log.read_text(encoding="utf-8") if log.is_file() else ""


class _Git:
    """A fake `_git(repo, *args)`: records every call; answers per subcommand."""

    def __init__(self, *, dirty: bool = False, diff: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.dirty = dirty  # `status --porcelain` shows changes BEFORE the fixer ran
        self.diff = diff  # `add -A` stages something (the session landed an edit)

    def __call__(self, repo: Path, *args: str) -> types.SimpleNamespace:
        self.calls.append(args)
        if args[0] == "status":
            return _completed(" M a.py\n" if self.dirty else "")
        if args[:2] == ("diff", "--cached"):
            return _completed("", returncode=1 if self.diff else 0)
        if args[0] == "rev-parse":
            return _completed("abc1234\n")
        return _completed("")

    def ran(self, *prefix: str) -> bool:
        return any(c[: len(prefix)] == prefix for c in self.calls)


_THREAD = pr_watch.ReviewThread("T1", False, "rev", "fix this", "a.py", 5)


def test_fixer_runner_raising_is_undetermined_and_restores_a_clean_tree(tmp_path: Path) -> None:
    git = _Git()

    def runner(system: str, prompt: str, workdir: Path) -> str:
        raise RuntimeError("claude call failed after 1 attempts: You've hit your usage limit")

    action, reply = pr_watch_cli._fixer(tmp_path, "m", runner=runner, git=git)(_THREAD)
    assert action == pr_watch.UNDETERMINED
    assert reply.startswith("fixer session did not complete: claude call failed")
    assert git.ran("reset", "--hard") and git.ran("clean", "-fdq")  # half-edits discarded
    assert not git.ran("commit") and not git.ran("add")


def test_fixer_never_discards_a_tree_that_was_dirty_before_it_ran(tmp_path: Path) -> None:
    git = _Git(dirty=True)  # a manual --apply on a checkout holding the user's own edits

    def runner(system: str, prompt: str, workdir: Path) -> str:
        raise OSError("claude: command not found")

    action, _ = pr_watch_cli._fixer(tmp_path, "m", runner=runner, git=git)(_THREAD)
    assert action == pr_watch.UNDETERMINED
    assert not git.ran("reset") and not git.ran("clean")  # the user's work is left alone


@pytest.mark.parametrize("reply", ["", "You've hit your usage limit · resets 3pm"])
def test_fixer_cli_error_reply_without_a_diff_is_undetermined(tmp_path: Path, reply: str) -> None:
    git = _Git(diff=False)
    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: reply, git=git)
    action, why = fix(_THREAD)
    assert action == pr_watch.UNDETERMINED and ("empty" in why or "CLI error" in why)
    assert not git.ran("commit")


def test_fixer_prose_without_a_diff_is_rejected_and_with_a_diff_is_fixed(tmp_path: Path) -> None:
    prose = "No change needed: the check already covers this."
    git = _Git(diff=False)
    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: prose, git=git)
    assert fix(_THREAD) == (
        "rejected", "No change made — may be a discussion point or already addressed."
    )
    git = _Git(diff=True)
    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: prose, git=git)
    assert fix(_THREAD) == ("fixed", "Addressed in abc1234.") and git.ran("commit")


def test_fixer_builds_a_bounded_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_runner(**kwargs: object) -> object:
        seen.update(kwargs)
        return lambda s, p, w: ""

    monkeypatch.setattr(pr_watch_cli.agent_eval, "claude_cli_runner", fake_runner)
    pr_watch_cli._fixer(tmp_path, "the-model", max_threads=10)
    assert seen["retries"] == 0  # one attempt: a retry loop could outlive the whole watch pass
    assert seen["call_timeout"] == pr_watch.fixer_timeout(10) == 144
    assert seen["model"] == "the-model" and seen["allowed_tools"] == "Read,Write,Edit,Grep,Glob"


def test_pr_watch_apply_undetermined_posts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _enable(tmp_path)
    calls: list[list[str]] = []
    pushed: list[bool] = []
    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42", "--apply"],
        fetch=_pr_fetch, fixer=lambda t: (pr_watch.UNDETERMINED, "limit hit"),
        gh_exec=calls.append, push=lambda: pushed.append(True),
    )
    out = capsys.readouterr().out
    assert rc == 0 and "undetermined 1" in out and "fixed 0" in out
    assert calls == [] and pushed == []  # no reply on the reviewer's thread, nothing pushed
    assert "undetermined (limit hit)" in _log(tmp_path)  # but audited (forced)


# F7: the conflict notice is posted once — and NOT when the comments could not be read.


class _ConflictGit:
    def __init__(self, *, fetch_ok: bool = True, merge_ok: bool = False) -> None:
        self.fetch_ok, self.merge_ok = fetch_ok, merge_ok
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, repo: Path, *args: str) -> types.SimpleNamespace:
        self.calls.append(args)
        if args[0] == "fetch":
            return _completed("", returncode=0 if self.fetch_ok else 1)
        if args[:2] == ("merge", "--no-edit"):
            return _completed("", returncode=0 if self.merge_ok else 1)
        return _completed("")


def _handler(tmp_path: Path, git: _ConflictGit, bodies: list[str] | None, posted: list) -> object:
    return pr_watch_cli._conflict_handler(
        tmp_path, "o", "r", 42, "main", git=git,
        comment_bodies=lambda repo, owner, name, number: bodies, post=posted.append,
    )


def test_conflict_handler_unreadable_comments_skips_the_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    posted: list[list[str]] = []
    git = _ConflictGit()
    assert _handler(tmp_path, git, None, posted)() is False
    assert posted == []  # unknown is not absent: nothing re-posted this poll
    assert ("merge", "--abort") in git.calls
    assert "rebase notice NOT posted" in capsys.readouterr().err
    assert "rebase notice NOT posted" in _log(tmp_path)  # and recorded why


def test_conflict_handler_posts_the_notice_once(tmp_path: Path) -> None:
    posted: list[list[str]] = []
    assert _handler(tmp_path, _ConflictGit(), [], posted)() is False
    assert len(posted) == 1 and pr_watch.CONFLICT_NOTICE in posted[0]  # first poll: posted
    present = [f"x {pr_watch.CONFLICT_NOTICE}"]
    assert _handler(tmp_path, _ConflictGit(), present, posted)() is False
    assert len(posted) == 1  # already there: not again


def test_conflict_handler_clean_merge_and_failed_fetch(tmp_path: Path) -> None:
    posted: list[list[str]] = []
    assert _handler(tmp_path, _ConflictGit(merge_ok=True), [], posted)() is True
    git = _ConflictGit(fetch_ok=False)
    assert _handler(tmp_path, git, [], posted)() is False
    assert posted == [] and not any(c[0] == "merge" for c in git.calls)  # no merge on a stale base


# F11: an empty `gh pr view` body is "unconfirmed", never "not merged".


def test_merge_confirmer_empty_output_is_unconfirmed_not_unmerged(tmp_path: Path) -> None:
    def confirmer(stdout: str) -> pr_watch.ConfirmMerged:
        return pr_watch_cli._merge_confirmer(
            tmp_path, "o/r", 42, run=lambda *a, **k: _completed(stdout)
        )

    with pytest.raises(RuntimeError, match="no output"):
        confirmer("")()
    assert confirmer('{"state": "MERGED"}')() is True
    assert confirmer('{"state": "OPEN"}')() is False
    # Through run_watch the raise becomes an "unconfirmed" outcome, not an unmerged one.
    state = pr_watch.parse_pr({"pullRequest": {
        "number": 42, "mergeable": "MERGEABLE", "headRefName": "f", "baseRefName": "main",
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        "reviewThreads": {"nodes": []},
    }})
    result = pr_watch.run_watch(
        state, bot="b", max_threads=1, fixer=lambda t: ("fixed", "x"), gh_exec=lambda a: None,
        push=lambda: None, merge=lambda: None, auto_merge=True, confirm_merged=confirmer(""),
    )
    assert not result.merged
    assert result.merge_blocked_by == ["merge outcome unconfirmed: gh pr view returned no output"]


# F12: an errored `gh pr list` is an error, not "no open PRs".


def test_pr_list_errors_are_errors_not_no_open_prs(tmp_path: Path) -> None:
    list_prs = run_scheduled._pr_list(tmp_path, run=lambda *a, **k: _completed("1\n2\n"))
    assert list_prs("o", "r") == [1, 2]
    broken = run_scheduled._pr_list(
        tmp_path, run=lambda *a, **k: _completed("", 4, "gh: HTTP 403: API rate limit exceeded")
    )
    with pytest.raises(RuntimeError, match=r"exit 4\): gh: HTTP 403: API rate limit exceeded"):
        broken("o", "r")


# F2: the watcher runs in its own process group, bounded by the budget, killed as a group.


class _Proc:
    def __init__(self, *, returncode: int = 0, hang: bool = False) -> None:
        self.pid, self.returncode, self.hang = 4242, returncode, hang
        self.communicates: list[float | None] = []

    def communicate(self, timeout: float | None = None) -> tuple[None, None]:
        self.communicates.append(timeout)
        if self.hang and timeout is not None:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
        return (None, None)


def test_run_watcher_kills_the_whole_group_at_the_budget(tmp_path: Path) -> None:
    spawned: dict[str, object] = {}
    proc = _Proc(hang=True)
    killed: list[int] = []

    def popen(cmd: list[str], **kwargs: object) -> _Proc:
        spawned.update(kwargs)
        return proc

    rc = run_scheduled._run_watcher(["w"], tmp_path, 7.0, popen=popen, kill_group=killed.append)
    assert rc is None
    assert spawned["start_new_session"] is True  # its own group: the kill reaches the grandchild
    assert killed == [4242] and proc.communicates == [7.0, None]  # killed at 7 s, then reaped


def test_run_watcher_returns_the_exit_code(tmp_path: Path) -> None:
    proc = _Proc(returncode=3)
    killed: list[int] = []
    rc = run_scheduled._run_watcher(
        ["w"], tmp_path, 7.0, popen=lambda *a, **k: proc, kill_group=killed.append
    )
    assert rc == 3 and killed == []


# F3 / F8: a watch pass reports its outcome; anything but exit 0 is a forced diagnostics event.


def test_watch_one_pr_reads_the_exit_code_and_records_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _enable(tmp_path, ', "auto_merge": true, "bot": "trusted[bot]"')
    cmds: list[list[str]] = []

    def run_watcher(cmd: list[str]) -> int | None:
        cmds.append(cmd)
        return {1: 0, 2: 1, 3: None}[int(cmd[cmd.index("--pr") + 1])]

    watch = run_scheduled._watch_one_pr(
        tmp_path, checkout=lambda argv: 0, run_watcher=run_watcher
    )
    assert watch("o", "r", 1) == run_scheduled.WatchOutcome(True)
    assert _log(tmp_path) == ""  # a completed pass is not an anomaly
    assert watch("o", "r", 2) == run_scheduled.WatchOutcome(False, "watcher exited 1")
    assert watch("o", "r", 3).reason.startswith("watcher killed at the 1800s budget")
    log = _log(tmp_path)
    assert "o/r#2: watcher exited 1" in log and "o/r#3: watcher killed" in log
    assert log.count('"component": "pr-watch-queue"') == 2
    assert "skip #2" in capsys.readouterr().err
    # the trusted (pre-checkout) settings reach the watcher as argv, after --apply
    assert cmds[0][-6:] == [
        "--apply", "--bot", "trusted[bot]", "--merge-method", "rebase", "--auto-merge"
    ]


def test_watch_one_pr_checkout_failure_is_recorded(tmp_path: Path) -> None:
    _enable(tmp_path)
    ran: list[list[str]] = []

    def run_watcher(cmd: list[str]) -> int | None:
        ran.append(cmd)
        return 0

    watch = run_scheduled._watch_one_pr(
        tmp_path, component="pr-watch", checkout=lambda argv: 128, run_watcher=run_watcher
    )
    assert watch("o", "r", 9) == run_scheduled.WatchOutcome(False, "checkout failed (exit 128)")
    assert ran == []  # never --apply on the wrong branch

    def hung(argv: list[str]) -> int:
        raise subprocess.TimeoutExpired(cmd=argv, timeout=120)

    watch = run_scheduled._watch_one_pr(tmp_path, checkout=hung, run_watcher=run_watcher)
    assert watch("o", "r", 9).reason.startswith("checkout failed: ")
    log = _log(tmp_path)
    assert '"component": "pr-watch"' in log and "checkout failed (exit 128)" in log


# F2c / F3: every entry's tick advances, the queue is persisted, THEN failed passes are reported.


def _queue(tmp_path: Path, entries: list[dict]) -> Path:
    path = diagnostics.state_file(tmp_path, pr_watch.QUEUE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_pr_watch_queue_persists_ticks_then_reports_failed_passes(tmp_path: Path) -> None:
    _enable(tmp_path)
    path = _queue(tmp_path, [
        {"owner": "o", "name": "r", "number": 1},
        {"owner": "o", "name": "r", "number": 2, "ticks": 5, "failures": 1},
        {"owner": "o", "name": "r", "number": 3},
    ])

    def watch_one(owner: str, name: str, number: int) -> run_scheduled.WatchOutcome:
        if number == 2:
            return run_scheduled.WatchOutcome(False, "watcher killed at the 1800s budget")
        if number == 3:
            raise RuntimeError("driver bug")
        return run_scheduled.WatchOutcome(True)

    with pytest.raises(RuntimeError, match=r"3 watched, 0 dropped, 3 remaining; 2 of 3 watch"):
        run_scheduled._pr_watch_queue(tmp_path, watch_one=watch_one, finished=lambda e: False)
    kept = pr_watch.parse_queue(json.loads(path.read_text(encoding="utf-8")))
    assert [(e.number, e.ticks, e.failures) for e in kept] == [(1, 1, 0), (2, 6, 2), (3, 1, 1)]
    assert "o/r#3: watch crashed: driver bug" in _log(tmp_path)


def test_pr_watch_queue_drop_reasons_are_true(tmp_path: Path) -> None:
    _enable(tmp_path, ', "max_ticks": 3')
    path = _queue(tmp_path, [
        {"owner": "o", "name": "r", "number": 1, "ticks": 2, "failures": 2},  # every poll failed
        {"owner": "o", "name": "r", "number": 2},  # merged meanwhile
    ])

    def watch_one(owner: str, name: str, number: int) -> run_scheduled.WatchOutcome:
        return run_scheduled.WatchOutcome(number == 2, "" if number == 2 else "watcher exited 1")

    with pytest.raises(RuntimeError, match="1 of 2 watch pass"):
        run_scheduled._pr_watch_queue(
            tmp_path, watch_one=watch_one, finished=lambda e: e.number == 2
        )
    assert json.loads(path.read_text(encoding="utf-8")) == []  # both left the queue
    log = _log(tmp_path)
    assert "dropped o/r#1 (tick budget spent: 3 of 3 polls failed)" in log
    assert "dropped o/r#2 (finished (merged or closed))" in log


def test_pr_watch_queue_all_ok_is_a_plain_summary(tmp_path: Path) -> None:
    _enable(tmp_path)
    _queue(tmp_path, [{"owner": "o", "name": "r", "number": 1}])

    def watch_one(owner: str, name: str, number: int) -> run_scheduled.WatchOutcome:
        return run_scheduled.WatchOutcome(True)

    summary = run_scheduled._pr_watch_queue(tmp_path, watch_one=watch_one, finished=lambda e: False)
    assert summary == "pr-watch-queue: 1 watched, 0 dropped, 1 remaining"
    assert _log(tmp_path) == ""


def test_run_scheduled_job_failure_is_a_diagnostics_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(repo: Path) -> str:
        raise RuntimeError("action failed")

    monkeypatch.setitem(run_scheduled._ACTIONS, "kb_maintenance", boom)
    assert run_scheduled.main(["run", "--repo", str(tmp_path), "--force"]) == 1
    log = _log(tmp_path)
    assert '"component": "scheduled-run"' in log and "kb-maintenance: action failed" in log
    assert '"kind": "error"' in log


# F5: the deploy digest says "unknown" when a source is down — never "healthy" on zero data.


class _Pipe:
    """A pipeline source that is NOT the in-memory fake (which short-circuits the digest)."""

    def __init__(self, deploys: list[ops.Deploy] | None = None, why: str = "") -> None:
        self.deploys, self.why = deploys or [], why

    def recent_deploys(self, environment: str) -> list[ops.Deploy]:
        if self.why:
            raise ops.SourceUnavailable(self.why)
        return list(self.deploys)


class _DownAlerts:
    def active_alerts(self, environment: str) -> list[ops.Alert]:
        raise ops.SourceUnavailable("grafana fetch failed: HTTP 401")


def _digest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pipe: object, alerts: object) -> str:
    monkeypatch.setattr(run_scheduled.connectors, "pipeline_source", lambda repo: pipe)
    monkeypatch.setattr(run_scheduled.connectors, "alert_source", lambda: alerts)
    return run_scheduled._deploy_digest(tmp_path)


def test_deploy_digest_says_unknown_when_the_source_is_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    line = _digest(monkeypatch, tmp_path, _Pipe(why="gh run list timed out after 60s"),
                   ops.InMemoryAlerts({}))
    assert line == (
        "deploy-digest [production]: unknown — source unavailable "
        "(pipeline: gh run list timed out after 60s)"
    )


def test_deploy_digest_names_a_down_source_next_to_a_real_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    failing = _Pipe([ops.Deploy("abc", "failing", "production")])
    line = _digest(monkeypatch, tmp_path, failing, _DownAlerts())
    assert line.startswith("deploy-digest [production]: failing — roll back")
    assert line.endswith(
        "(1 recent runs); source unavailable (alerts: grafana fetch failed: HTTP 401)"
    )


def test_deploy_digest_healthy_line_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    passing = _Pipe([ops.Deploy("abc", "passing", "production")])
    assert _digest(monkeypatch, tmp_path, passing, ops.InMemoryAlerts({})) == (
        "deploy-digest [production]: healthy — none — continue monitoring (1 recent runs)"
    )


# --- eval audit fixes: what the CLIs print, pass and refuse ------------------------------------


def test_run_agent_evals_prints_the_unmeasured_sessions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = _FakeReport(True)
    rep.evidence_lines = lambda: [  # type: ignore[method-assign]
        "    unmeasured: run 1 case 2 undetermined (error_max_turns, num_turns=40)"
    ]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_agent_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_agent_evals.agent_eval, "run_role", lambda *a, **k: rep)
    assert run_agent_evals.main(["run", "--runner", "claude", "--role", "reviewer"]) == 0
    assert "undetermined (error_max_turns, num_turns=40)" in capsys.readouterr().out


def test_run_skill_evals_prints_the_unmeasured_sessions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rep = _FakeReport(True)
    rep.evidence_lines = lambda: ["    unmeasured: run 3 case 1 ungraded (grading-unparseable)"]  # type: ignore[method-assign]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_skill_evals, "_build_runners", lambda *a, **k: (object(), object()))
    monkeypatch.setattr(run_skill_evals.skill_eval, "run_skill", lambda *a, **k: rep)
    assert run_skill_evals.main(["run", "--runner", "claude", "--skill", "python-patterns"]) == 0
    assert "ungraded (grading-unparseable)" in capsys.readouterr().out


def test_run_spine_e2e_gives_the_phases_sixty_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    # 40 stopped the develop phase mid-task, and a cap hit read as a failed phase (audit C13).
    seen: dict[str, object] = {}

    def fake_runner(*a: object, **k: object) -> object:
        seen.update(k)
        return lambda *x, **y: ""

    monkeypatch.setattr(run_spine_e2e.agent_eval, "claude_cli_runner", fake_runner)
    monkeypatch.setattr(run_spine_e2e.spine_e2e, "run_scenario", lambda *a, **k: [_FakePhase(True)])
    assert run_spine_e2e.main(["run", "--runner", "claude", "--scenario", "spine"]) == 0
    assert seen["max_turns"] == 60


def test_run_activation_evals_scores_a_bare_builtin_name_as_a_collision(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import run_activation_evals
    from agentic_forge import activation as activation_lib
    from agentic_forge.activation import ActivationReport

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(run_activation_evals, "_cli_runner", lambda *a, **k: object())
    captured: dict[str, object] = {}

    def fake_run(*a: object, **k: object) -> list[ActivationReport]:
        captured.update(k)
        return [ActivationReport("code-review", 4, 5, 0.8, collided=["Review my PR"])]

    monkeypatch.setattr(activation_lib, "run_activation", fake_run)
    assert run_activation_evals.main(["run", "--runner", "claude"]) == 0
    builtins = captured["builtins"]
    assert isinstance(builtins, frozenset) and {"code-review", "security-review"} <= builtins
    out = capsys.readouterr().out
    assert "[code-review] activation=0.800 (4/5; 1 bare-collided)" in out
    assert "bare-collided [code-review] Review my PR: called `code-review` bare" in out
    assert "1 bare-collided)" in out.splitlines()[-1]  # and on the pooled line


# --- ralph: a harness fault is an error, not the agent's exhaustion (eval audit C7/C14) --------


def test_ralph_done_checker_runs_the_command_as_argv(tmp_path: Path) -> None:
    assert ralph_cli._done_checker(tmp_path, "true")() is True
    assert ralph_cli._done_checker(tmp_path, "false")() is False
    assert ralph_cli._done_checker(tmp_path, None)() is False  # no command: never done


def test_ralph_done_checker_that_cannot_launch_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ralph_cli.DoneCommandError, match="could not be launched"):
        ralph_cli._done_checker(tmp_path, "no-such-command-xyz-123 -q")()


def test_ralph_done_checker_timeout_is_not_done_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    is_done = ralph_cli._done_checker(tmp_path, "sleep 5", timeout=0.2)
    assert is_done() is False
    assert "timed out after 0.2s" in capsys.readouterr().err


def _git_repo(path: Path) -> Path:
    import subprocess

    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main"], check=True)
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=t@local", "-c", "user.name=t",
         "commit", "-q", "-m", "baseline"],
        check=True,
    )
    return path


def test_ralph_progress_checker_sees_a_tree_change(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    progressed = ralph_cli._progress_checker(repo)
    assert progressed() is False  # nothing changed since the baseline
    (repo / "g.txt").write_text("new\n", encoding="utf-8")
    assert progressed() is True and progressed() is False


def test_ralph_progress_checker_on_a_non_git_repo_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ralph_cli.RepoStateError, match="git rev-parse HEAD failed"):
        ralph_cli._progress_checker(tmp_path)


def test_ralph_apply_aborts_on_an_unlaunchable_done_cmd(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A typo'd --done-cmd read as "not done" on every iteration, burned the budget and reported
    # `exhausted` as the agent's failure. Now: one clear message, exit 1, no iterations wasted.
    runs: list[int] = []
    rc = ralph_cli.main(
        ["x", "--repo", str(tmp_path), "--task", str(_task(tmp_path)), "--apply",
         "--done-cmd", "no-such-command-xyz-123", "--max-iterations", "5"],
        run_iteration=runs.append, progressed=lambda: True,
    )
    assert rc == 1 and runs == [1]  # the first check found the fault
    assert "ralph: error: done-cmd 'no-such-command-xyz-123' could not be launched" in (
        capsys.readouterr().err
    )


def test_ralph_apply_aborts_on_a_non_git_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = ralph_cli.main(
        ["x", "--repo", str(tmp_path), "--task", str(_task(tmp_path)), "--apply",
         "--done-cmd", "true"],
        run_iteration=lambda n: None, is_done=lambda: False,
    )
    assert rc == 1 and "ralph: error: git rev-parse HEAD failed" in capsys.readouterr().err
