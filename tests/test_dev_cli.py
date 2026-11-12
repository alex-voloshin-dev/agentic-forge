from __future__ import annotations

import os
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
from agentic_forge import diagnostics, schedule, settings  # noqa: E402


def test_validate_cli_main_ok() -> None:
    # The real plugin passes Tier-0.
    assert validate_cli.main(["validate"]) == 0


def test_validate_cli_missing_dir() -> None:
    assert validate_cli.main(["validate", "/no/such/plugin/dir"]) == 1


def test_validate_cli_validates_maintainer_skills_outside_the_budget(capsys) -> None:
    assert validate_cli.main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "maintainer skills: 1 validated, not shipped, not in the budget (skill-factory)" in out
    assert "16 on-listing skills)" in out  # the budget counts the shipped listing only


def _repo_with_maintainer_skill(
    tmp_path: Path, skill_md: str, evals: str | None, *, marker: bool = True
) -> Path:
    if marker:  # what makes tmp_path "this repository" (validation.REPO_MARKER)
        (tmp_path / "docs" / "architecture").mkdir(parents=True)
        (tmp_path / "docs" / "architecture" / "meta-core.md").write_text("# m\n", encoding="utf-8")
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "p", "version": "1"}', encoding="utf-8"
    )
    skill = tmp_path / ".claude" / "skills" / "maint"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(skill_md, encoding="utf-8")
    if evals is not None:
        (skill / "evals").mkdir()
        (skill / "evals" / "evals.json").write_text(evals, encoding="utf-8")
    return plugin


def test_validate_cli_fails_on_a_broken_maintainer_skill(tmp_path: Path, capsys) -> None:
    plugin = _repo_with_maintainer_skill(
        tmp_path, "---\nname: maint\ndescription: d\n---\nSee [x](references/x.md)\n", None
    )
    assert validate_cli.main(["validate", str(plugin)]) == 1
    out = capsys.readouterr().out
    assert ".claude/skills/maint/SKILL.md: referenced file does not exist" in out
    assert ".claude/skills/maint/evals/evals.json: missing required eval contract" in out
    assert "0 on-listing skills)" in out  # never counted in the shipped budget


def test_validate_cli_never_reads_a_personal_claude_skills_dir(tmp_path: Path, capsys) -> None:
    """`dev/validate.py ~/some-plugin` must not validate the user's own ~/.claude/skills: without
    this repo's marker there are no maintainer skills."""
    plugin = _repo_with_maintainer_skill(
        tmp_path, "---\nname: maint\ndescription: d\n---\nSee [x](references/x.md)\n", None,
        marker=False,
    )
    assert validate_cli.main(["validate", str(plugin)]) == 0
    assert "maintainer skills:" not in capsys.readouterr().out


def test_validate_cli_passes_a_standalone_plugin_without_maintainer_skills(
    tmp_path: Path, capsys
) -> None:
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "p", "version": "1"}', encoding="utf-8"
    )
    assert validate_cli.main(["validate", str(plugin)]) == 0  # no .claude/skills beside it
    assert "maintainer skills:" not in capsys.readouterr().out


def test_run_agent_evals_dry_ok() -> None:
    assert run_agent_evals.main(["run", "--runner", "dry"]) == 0


def test_run_spine_e2e_dry_ok() -> None:
    assert run_spine_e2e.main(["run", "--runner", "dry"]) == 0


def test_run_tier1_evals_dry_ok(capsys) -> None:
    # The real plugin's live listing + triggers are well-formed — with the maintainer skills,
    # which are included by default (ADR 0105).
    assert run_tier1_evals.main(["run", "--runner", "dry"]) == 0
    root = _REPO / ".claude" / "skills"
    assert f"listing: 16 shipped + 1 maintainer skill(s) (extra roots: {root})" in (
        capsys.readouterr().out
    )


def test_run_tier1_evals_dry_shipped_only(capsys) -> None:
    assert run_tier1_evals.main(["run", "--runner", "dry", "--no-maintainer-skills"]) == 0
    assert "listing: 16 shipped + 0 maintainer skill(s) (extra roots: none)" in (
        capsys.readouterr().out
    )


def test_run_tier1_evals_rejects_a_missing_skill_root(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nope"
    assert run_tier1_evals.main(["run", "--runner", "dry", "--skill-root", str(missing)]) == 1
    assert f"error: skill root not found: {missing}" in capsys.readouterr().err


def test_resolve_skill_roots_default_override_and_marker(tmp_path: Path) -> None:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    resolve = _eval_cli.resolve_skill_roots
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    assert resolve(plugin, None) == []  # .claude/skills, but not this repository: not ours
    (tmp_path / "docs" / "architecture").mkdir(parents=True)
    (tmp_path / "docs" / "architecture" / "meta-core.md").write_text("# m\n", encoding="utf-8")
    assert resolve(plugin, None) == [tmp_path / ".claude" / "skills"]
    assert resolve(plugin, [tmp_path]) == [tmp_path.resolve()]
    assert resolve(plugin, [tmp_path], include=False) == []
    with pytest.raises(ValueError, match="skill root not found"):
        resolve(plugin, [tmp_path / "nope"])


def test_run_skill_evals_dry_ok(capsys) -> None:
    # Every tier2 skill (packs + engineering-standards + deep-review/skill-factory) is wired;
    # skill-factory is found in the maintainer root by default (ADR 0105).
    assert run_skill_evals.main(["run", "--runner", "dry"]) == 0
    assert "skill-factory: ready" in capsys.readouterr().out


def test_run_skill_evals_skill_root_overrides_the_default(tmp_path: Path, capsys) -> None:
    assert run_skill_evals.main(["run", "--runner", "dry", "--skill-root", str(tmp_path)]) == 0
    assert "skill-factory" not in capsys.readouterr().out
    assert _eval_cli.resolve_skill_roots(_REPO / "plugin", None) == [_REPO / ".claude" / "skills"]


def test_run_skill_evals_rejects_a_missing_skill_root(tmp_path: Path, capsys) -> None:
    """A typo'd --skill-root used to replace the default and be skipped: skill-factory then
    silently dropped out of the run."""
    missing = tmp_path / "nope"
    assert run_skill_evals.main(["run", "--runner", "dry", "--skill-root", str(missing)]) == 1
    assert f"error: skill root not found: {missing}" in capsys.readouterr().err


def test_run_skill_evals_empty_discovery_returns_1(monkeypatch: pytest.MonkeyPatch) -> None:
    # nothing to evaluate must NOT be a vacuous exit 0 (a rename emptying discovery would hide it).
    monkeypatch.setattr(
        run_skill_evals.skill_eval, "discover_skills_with_tier2", lambda d, roots=(): []
    )
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


def test_tier1_router_removes_every_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--allowedTools ""` only grants nothing; it removes nothing. A router that kept the default
    tools ran the `Skill` it was asked to name and answered in prose, leaving prompts unmeasured
    (ADR 0105). `--tools ""` is the flag that takes the tools away."""
    import subprocess

    captured: dict = {}

    class _Done:
        returncode = 0
        stdout = '{"result": "research", "subtype": "success"}'
        stderr = ""

    def fake_run(cmd: list[str], **kw: object) -> _Done:
        captured["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_tier1_evals._build_router("claude", "m")("SYS", "P", _REPO)
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd  # and no MCP server tools either
    assert "--system-prompt" in cmd  # still a classifier, not an agent (ADR 0064)


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


def _skip(reason: str, detail: str = "") -> object:
    return external_review_cli.external_review.ReviewOutcome(
        status="skipped",
        reason=reason,
        detail=detail,
    )


def _fail(reason: str, detail: str = "") -> object:
    return external_review_cli.external_review.ReviewOutcome(
        status="failed",
        reason=reason,
        detail=detail,
    )


_EXIT_FAILED = 3


def _ext(monkeypatch: pytest.MonkeyPatch, *, available: bool, result: object) -> None:
    lib = external_review_cli.external_review
    outcome = (
        lib.ReviewOutcome(status="reviewed", review=result)
        if result is not None
        else _fail("invalid-output", "no review-shaped JSON in the output")
    )
    monkeypatch.setattr(lib, "is_available", lambda c: available)
    monkeypatch.setattr(lib, "review_outcome", lambda *a, **k: outcome)


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


def test_external_review_unparseable_is_a_failure_and_returns_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ext(monkeypatch, available=True, result=None)
    assert _run_ext(tmp_path, "--force") == _EXIT_FAILED
    assert external_review_cli.EXIT_FAILED == _EXIT_FAILED  # the documented contract


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


# --- --target and --out refuse a symlink (ADR 0100) ----------------------------


def _forbid_review(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*a: object, **k: object) -> object:
        raise AssertionError("the reviewer must not run")

    lib = external_review_cli.external_review
    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", fail)


@pytest.mark.parametrize("dangling", [False, True])
def test_external_review_refuses_a_symlinked_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    dangling: bool,
) -> None:
    _forbid_review(monkeypatch)
    secret = tmp_path / "secret.txt"
    if not dangling:
        secret.write_text("not for a third party", encoding="utf-8")
    link = tmp_path / "diff.txt"
    link.symlink_to(secret)
    rc = external_review_cli.main(["x", "--repo", str(tmp_path), "--target", str(link), "--force"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "refusing --target" in err and "symlink" in err


@pytest.mark.parametrize("dangling", [False, True])
def test_external_review_refuses_a_symlinked_out_before_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    dangling: bool,
) -> None:
    _forbid_review(monkeypatch)
    victim = tmp_path / "victim.txt"
    if not dangling:
        victim.write_text("keep me", encoding="utf-8")
    link = tmp_path / "review.md"
    link.symlink_to(victim)
    assert _run_ext(tmp_path, "--out", str(link), "--force") == 1
    err = capsys.readouterr().err
    assert "refusing --out" in err and "symlink" in err
    if dangling:
        assert not victim.exists()
    else:
        assert victim.read_text(encoding="utf-8") == "keep me"


def test_external_review_refuses_an_out_symlink_that_appears_during_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    out = tmp_path / "review.md"
    lib = external_review_cli.external_review

    def plant(*a: object, **k: object) -> object:
        out.symlink_to(victim)
        return lib.ReviewOutcome(status="reviewed", review=_APPROVE)

    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", plant)
    assert _run_ext(tmp_path, "--out", str(out)) == 1
    assert "could not write" in capsys.readouterr().err
    assert victim.read_text(encoding="utf-8") == "keep me"


def _repo_with_a_linked_directory(tmp_path: Path) -> tuple[Path, Path]:
    """A repo holding ``docs/link``, a symlink to a directory outside it, and that directory."""
    repo, outside = tmp_path / "repo", tmp_path / "outside"
    (repo / "docs").mkdir(parents=True)
    outside.mkdir()
    (outside / "plan.md").write_text("not for a third party", encoding="utf-8")
    (repo / "docs" / "link").symlink_to(outside)
    return repo, outside


def _main_ext(repo: Path, target: Path, *extra: str) -> int:
    return external_review_cli.main(["x", "--repo", str(repo), "--target", str(target), *extra])


@pytest.mark.parametrize(
    "route",
    [
        "repo/docs/link/plan.md",
        "repo/docs/link/../outside/plan.md",
        "outside/../repo/docs/link/plan.md",
    ],
)
def test_external_review_refuses_a_target_through_a_symlinked_directory_in_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, route: str
) -> None:
    # `link/..` is the link's target's parent to the OS, whatever it looks like as text, and a `..`
    # on the way into the repo must not read as being outside it.
    _forbid_review(monkeypatch)
    repo, _ = _repo_with_a_linked_directory(tmp_path)
    assert _main_ext(repo, tmp_path / route) == 1
    err = capsys.readouterr().err
    assert "refusing --target" in err and "symlink inside the repo" in err


def test_external_review_refuses_a_relative_target_through_a_linked_directory_in_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _forbid_review(monkeypatch)
    repo, _ = _repo_with_a_linked_directory(tmp_path)
    monkeypatch.chdir(repo)
    assert _main_ext(Path("."), Path("docs/link/plan.md")) == 1
    assert "symlink inside the repo" in capsys.readouterr().err


def test_external_review_refuses_a_target_through_a_link_when_the_repo_is_named_by_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # `--repo` is resolved, so its own link is above the root, and the one below it still counts.
    _forbid_review(monkeypatch)
    repo, _ = _repo_with_a_linked_directory(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(repo)
    assert _main_ext(alias, alias / "docs" / "link" / "plan.md") == 1
    assert "symlink inside the repo" in capsys.readouterr().err


def test_external_review_refuses_an_out_through_a_symlinked_directory_in_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _forbid_review(monkeypatch)
    repo, outside = _repo_with_a_linked_directory(tmp_path)
    target = repo / "diff.txt"
    target.write_text("x", encoding="utf-8")
    assert _main_ext(repo, target, "--out", str(repo / "docs/link/review.md")) == 1
    assert "refusing --out" in capsys.readouterr().err
    assert not (outside / "review.md").exists()


def test_external_review_refuses_an_out_whose_parent_becomes_a_link_during_the_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo, outside = _repo_with_a_linked_directory(tmp_path)
    (repo / "docs" / "link").unlink()
    (repo / "out").mkdir()
    target = repo / "diff.txt"
    target.write_text("x", encoding="utf-8")
    lib = external_review_cli.external_review

    def swap(*a: object, **k: object) -> object:
        (repo / "out").rmdir()
        (repo / "out").symlink_to(outside)
        return lib.ReviewOutcome(status="reviewed", review=_APPROVE)

    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", swap)
    assert _main_ext(repo, target, "--out", str(repo / "out" / "review.md")) == 1
    assert "could not write" in capsys.readouterr().err
    assert not (outside / "review.md").exists()


def test_external_review_allows_a_link_above_the_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # /tmp and home directories are often links themselves.
    _ext(monkeypatch, available=True, result=_APPROVE)
    real = tmp_path / "real"
    (real / "repo").mkdir(parents=True)
    (tmp_path / "linked").symlink_to(real)
    repo = tmp_path / "linked" / "repo"
    target = _target(repo)
    assert _main_ext(repo, target, "--out", str(repo / "review.md")) == 0
    assert (real / "repo" / "review.md").is_file()


def test_external_review_allows_a_link_outside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Outside the repo the path is the operator's own, wherever it leads, even back into the repo.
    _ext(monkeypatch, available=True, result=_APPROVE)
    repo, outside = _repo_with_a_linked_directory(tmp_path)
    (tmp_path / "out-link").symlink_to(outside)
    (tmp_path / "docs-link").symlink_to(repo / "docs")
    via_link = tmp_path / "out-link"
    assert _main_ext(repo, via_link / "plan.md", "--out", str(via_link / "r.md")) == 0
    assert (outside / "r.md").is_file()
    (repo / "docs" / "plan.md").write_text("x", encoding="utf-8")
    assert _main_ext(repo, tmp_path / "docs-link" / "plan.md") == 0


def test_external_review_allows_a_target_outside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ext(monkeypatch, available=True, result=_APPROVE)
    repo, outside = _repo_with_a_linked_directory(tmp_path)
    assert _main_ext(repo, outside / "plan.md") == 0


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="the platform has no such flag")
def test_external_review_refuses_a_target_swapped_for_a_symlink_after_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # The link the check did not see, as if it were put there between the check and the read.
    _forbid_review(monkeypatch)
    secret = tmp_path / "secret.txt"
    secret.write_text("not for a third party", encoding="utf-8")
    link = tmp_path / "diff.txt"
    link.symlink_to(secret)
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    assert _main_ext(tmp_path, link) == 1
    err = capsys.readouterr().err
    assert "refusing --target" in err and "Traceback" not in err


@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_external_review_refuses_a_target_that_is_not_a_regular_file_when_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, kind: str
) -> None:
    # What the fstat is for: `is_file` said yes, and then something else was there. A pipe must be
    # refused, not waited on.
    _forbid_review(monkeypatch)
    swapped = tmp_path / "diff.txt"
    if kind == "fifo":
        os.mkfifo(swapped)
    else:
        swapped.mkdir()
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    assert _main_ext(tmp_path, swapped) == 1
    err = capsys.readouterr().err
    assert "refusing --target" in err and "not a regular file" in err


def test_external_review_refuses_a_target_that_is_not_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _forbid_review(monkeypatch)
    target = tmp_path / "diff.txt"
    target.write_bytes(b"\xff\xfe not text")
    assert _main_ext(tmp_path, target) == 1
    err = capsys.readouterr().err
    assert "refusing --target" in err and "not UTF-8" in err and "Traceback" not in err


def test_external_review_reports_a_target_it_cannot_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _forbid_review(monkeypatch)
    target = _target(tmp_path)

    def denied(*a: object, **k: object) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(external_review_cli.os, "open", denied)
    assert _main_ext(tmp_path, target) == 1
    assert "Permission denied" in capsys.readouterr().err


def test_external_review_keeps_the_targets_universal_newlines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As `read_text` did: the reader change must not put `\\r` into the prompt.
    lib = external_review_cli.external_review
    seen: list[str] = []

    def record(text: str, *a: object, **k: object) -> object:
        seen.append(text)
        return lib.ReviewOutcome(status="reviewed", review=_APPROVE)

    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", record)
    target = tmp_path / "diff.txt"
    target.write_bytes(b"one\r\ntwo\n")
    assert _main_ext(tmp_path, target) == 0
    assert seen == ["one\ntwo\n"]


def test_external_review_overwrites_a_regular_out_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ext(monkeypatch, available=True, result=_APPROVE)
    out = tmp_path / "review.md"
    out.write_text("x" * 10_000, encoding="utf-8")
    assert _run_ext(tmp_path, "--out", str(out)) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("---\n") and "x" * 100 not in text  # truncated, not overlaid


def test_external_review_scrubs_a_hostile_finding_from_terminal_and_review_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Regression, through the real parser: these survived to both places.
    import json

    lib = external_review_cli.external_review
    finding = {"severity": "major", "location": "\x1b[2Ja:1", "issue": "AKIAABCDEFGHIJKLMNOP"}

    def run(argv: list[str], **kwargs: object) -> object:
        import subprocess

        reply = json.dumps({"verdict": "changes", "findings": [finding]})
        return subprocess.CompletedProcess(argv, 0, stdout=reply, stderr="")

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(lib.shutil, "which", lambda c: "/bin/" + c)
    monkeypatch.setattr(lib.subprocess, "run", run)
    out = tmp_path / "review.md"
    assert _run_ext(tmp_path, "--out", str(out)) == 1
    printed = capsys.readouterr().out
    written = out.read_text(encoding="utf-8")
    for text in (printed, written):
        assert "\x1b" not in text and "[2J" not in text and "AKIAABCDEFGHIJKLMNOP" not in text
        assert "[REDACTED]" in text


def test_external_review_command_override_reaches_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, str] = {}
    lib = external_review_cli.external_review

    def fake_outcome(target: str, kind: str, *, command: str, **kwargs: object) -> object:
        seen["command"] = command
        return lib.ReviewOutcome(status="reviewed", review=_APPROVE)

    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", fake_outcome)
    assert _run_ext(tmp_path, "--command", "my-reviewer", "--force") == 0
    assert seen["command"] == "my-reviewer"


@pytest.mark.parametrize(
    "reason", ["timeout", "process-failure", "invalid-output", "isolation-unsupported"]
)
def test_external_review_prints_the_actual_failure_reason_and_exits_3(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    reason: str,
) -> None:
    lib = external_review_cli.external_review
    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", lambda *a, **k: _fail(reason, "the detail"))
    out_file = tmp_path / "review.md"
    assert _run_ext(tmp_path, "--force", "--out", str(out_file)) == _EXIT_FAILED
    captured = capsys.readouterr()
    assert f"failed ({reason})" in captured.err and "the detail" in captured.err
    assert "not a skip" in captured.err and "skipped" not in captured.err
    assert "parseable" not in captured.err  # the old message claimed this even after a timeout
    assert "verdict" not in captured.out  # a skip must never read as a verdict
    assert not out_file.exists()  # and leaves no review.md that could


def test_external_review_cli_vanishing_mid_run_still_exits_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    lib = external_review_cli.external_review
    monkeypatch.setattr(lib, "is_available", lambda c: True)
    monkeypatch.setattr(lib, "review_outcome", lambda *a, **k: _skip("missing-cli"))
    assert _run_ext(tmp_path, "--force") == 0
    err = capsys.readouterr().err
    assert "skipped (missing-cli)" in err and "failed" not in err


def _isolated_operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cfg = tmp_path / "home" / ".agentic-forge"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(
        '{"external_reviewer": {"isolated": true, "model": "gpt-5.1", "effort": "high"}}',
        encoding="utf-8",
    )


def test_external_review_isolated_config_reaches_the_real_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    _isolated_operator(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        out = (
            "--ignore-user-config --ephemeral"
            if argv[1:] == ["exec", "--help"]
            else '{"verdict":"approve","findings":[]}'
        )
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    lib = external_review_cli.external_review
    monkeypatch.setattr(lib.shutil, "which", lambda c: "/bin/" + c)
    monkeypatch.setattr(lib.subprocess, "run", run)
    assert _run_ext(tmp_path) == 0
    assert calls[0] == ["codex", "exec", "--help"]
    assert "--ignore-user-config" in calls[1] and "--ephemeral" in calls[1]
    assert calls[1][calls[1].index("--model") + 1] == "gpt-5.1"
    assert 'model_reasoning_effort="high"' in calls[1]


@pytest.mark.parametrize("schema_present", [True, False])
def test_external_review_config_path_never_reaches_the_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, schema_present: bool
) -> None:
    import subprocess

    if not schema_present:
        monkeypatch.setitem(sys.modules, "jsonschema", None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        '{"external_reviewer": {"command": "./evil.sh"}}', encoding="utf-8"
    )
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"verdict":"approve","findings":[]}', stderr=""
        )

    lib = external_review_cli.external_review
    monkeypatch.setattr(lib.shutil, "which", lambda c: "/bin/" + c)
    monkeypatch.setattr(lib.subprocess, "run", run)
    assert _run_ext(tmp_path) == 0
    assert [argv[0] for argv in calls] == ["codex"]


def test_external_review_command_argument_may_name_a_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Pinned decision (ADR 0100): --command is the operator's own argument, not repo-controlled.
    import subprocess

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"verdict":"approve","findings":[]}', stderr=""
        )

    lib = external_review_cli.external_review
    monkeypatch.setattr(lib.shutil, "which", lambda c: c)
    monkeypatch.setattr(lib.subprocess, "run", run)
    monkeypatch.chdir(tmp_path)
    assert _run_ext(tmp_path, "--command", "./my-reviewer", "--force") == 0
    assert Path(calls[0][0]) == Path.cwd() / "my-reviewer"  # the same program for check and run


@pytest.mark.parametrize("command", ["my-reviewer", "/opt/tools/my-reviewer"])
def test_external_review_command_argument_keeps_a_bare_name_and_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    import subprocess

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"verdict":"approve","findings":[]}', stderr=""
        )

    lib = external_review_cli.external_review
    monkeypatch.setattr(lib.shutil, "which", lambda c: c)
    monkeypatch.setattr(lib.subprocess, "run", run)
    assert _run_ext(tmp_path, "--command", command) == 0
    assert calls[0][0] == command


def _repo_chooses_the_reviewer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """The real scenario, with nothing faked but PATH and HOME: a repo config choosing the reviewer,
    a repo file that drops a marker and forges an approve, and stub reviewers that log their argv
    and say `changes`. PATH holds only the temp bin, so no real codex can ever run."""
    bin_dir, repo = tmp_path / "bin", tmp_path / "repo"
    bin_dir.mkdir()
    (repo / ".agentic-forge").mkdir(parents=True)
    (repo / ".agentic-forge" / "config.json").write_text(
        '{"external_reviewer": {"enabled": true, "command": "python3"}}', encoding="utf-8"
    )
    (bin_dir / "python3").symlink_to(sys.executable)
    marker, log = tmp_path / "marker", tmp_path / "reviewer.log"
    (repo / "exec").write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('ran')\n"
        """print('{"verdict":"approve","findings":[]}')\n""",
        encoding="utf-8",
    )
    for name in ("codex", "my-reviewer"):
        stub = bin_dir / name
        stub.write_text(
            f"#!{sys.executable}\nimport json, pathlib, sys\n"
            f"pathlib.Path({str(log)!r}).write_text(json.dumps([{name!r}, *sys.argv[1:]]))\n"
            """print('{"verdict":"changes","findings":[]}')\n""",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return {"repo": repo, "marker": marker, "log": log}


@pytest.mark.parametrize("schema_present", [True, False])
def test_repo_config_cannot_choose_the_reviewer_or_forge_a_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    schema_present: bool,
) -> None:
    # Regression: this ran what the repo chose and took its output as the verdict (ADR 0100).
    import json

    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    if not schema_present:
        monkeypatch.setitem(sys.modules, "jsonschema", None)
    assert _run_ext(scene["repo"]) == 1  # the default reviewer's `changes`, not the forged approve
    captured = capsys.readouterr()
    assert not scene["marker"].exists()
    assert json.loads(scene["log"].read_text(encoding="utf-8"))[:4] == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
    ]
    assert "verdict: changes" in captured.out
    assert "external_reviewer.command" in captured.err and "python3" not in captured.err


def test_repo_config_cannot_replace_the_operators_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    user = tmp_path / "home" / ".agentic-forge"
    user.mkdir(parents=True)
    (user / "config.json").write_text(
        '{"external_reviewer": {"command": "my-reviewer"}}', encoding="utf-8"
    )
    assert _run_ext(scene["repo"]) == 1
    assert not scene["marker"].exists()
    assert json.loads(scene["log"].read_text(encoding="utf-8"))[0] == "my-reviewer"


def test_the_repo_scenario_is_real_when_the_operator_passes_the_same_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The control. It proves the two tests above are not passing vacuously: the same repo file does
    # run and does forge an approve once that program is chosen, here by the operator's own
    # --command, which is allowed to do this.
    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    assert _run_ext(scene["repo"], "--command", "python3") == 0
    assert scene["marker"].read_text(encoding="utf-8") == "ran"
    assert not scene["log"].exists()


def test_review_refuses_the_value_a_session_read_from_the_raw_repo_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression, really executed: this is the same repo as above, reached through the call the
    # skills make. The control test above shows this repo file does run once it is chosen.
    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    lib = external_review_cli.external_review
    assert lib.review("target", "code", command="python3", workdir=scene["repo"]) is None
    assert not scene["marker"].exists()
    assert not scene["log"].exists()  # nothing ran at all


def test_review_without_a_command_runs_the_configured_reviewer_for_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    lib = external_review_cli.external_review
    got = lib.review("target", "code", workdir=scene["repo"])
    assert got is not None and got["verdict"] == "changes"
    assert not scene["marker"].exists()
    assert json.loads(scene["log"].read_text(encoding="utf-8"))[0] == "codex"


def test_repo_config_cannot_set_the_operators_reviewer_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Really executed against the stub reviewer: its argv is what reached the program.
    import json

    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    (scene["repo"] / ".agentic-forge" / "config.json").write_text(
        '{"external_reviewer": {"isolated": true, "model": "weak-model", "effort": "low"}}',
        encoding="utf-8",
    )
    assert _run_ext(scene["repo"]) == 1
    captured = capsys.readouterr()
    argv = json.loads(scene["log"].read_text(encoding="utf-8"))
    assert argv == ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"]
    for key in ("isolated", "model", "effort"):
        assert f"external_reviewer.{key}" in captured.err
    assert "weak-model" not in captured.err


def test_review_honours_a_repo_opt_out_for_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)
    (scene["repo"] / ".agentic-forge" / "config.json").write_text(
        '{"external_reviewer": {"enabled": false}}', encoding="utf-8"
    )
    lib = external_review_cli.external_review
    assert lib.review("target", "code", workdir=scene["repo"]) is None
    assert not scene["log"].exists() and not scene["marker"].exists()
    outcome = lib.configured_review_outcome("target", "code", workdir=scene["repo"])
    assert outcome.reason == "disabled"
    # The CLI is the operator's: disabled exits 0 without running, and --force still runs it.
    assert _run_ext(scene["repo"]) == 0
    assert not scene["log"].exists()
    assert _run_ext(scene["repo"], "--force") == 1
    assert scene["log"].exists()


@pytest.mark.parametrize("schema_present", [True, False])
def test_external_review_cli_honours_a_user_level_opt_out_over_the_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    schema_present: bool,
) -> None:
    scene = _repo_chooses_the_reviewer(tmp_path, monkeypatch)  # its repo config sets enabled: true
    if not schema_present:
        monkeypatch.setitem(sys.modules, "jsonschema", None)
    user = tmp_path / "home" / ".agentic-forge"
    user.mkdir(parents=True)
    (user / "config.json").write_text('{"external_reviewer": {"enabled": false}}', encoding="utf-8")
    assert _run_ext(scene["repo"]) == 0
    assert "disabled" in capsys.readouterr().out
    assert not scene["log"].exists() and not scene["marker"].exists()
    assert _run_ext(scene["repo"], "--force") == 1  # the operator's own override still works
    assert scene["log"].exists()


def test_external_review_isolated_config_on_an_old_cli_fails_and_exits_3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    import subprocess

    _isolated_operator(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="--sandbox", stderr="")

    lib = external_review_cli.external_review
    monkeypatch.setattr(lib.shutil, "which", lambda c: "/bin/" + c)
    monkeypatch.setattr(lib.subprocess, "run", run)
    assert _run_ext(tmp_path) == _EXIT_FAILED
    assert "failed (isolation-unsupported)" in capsys.readouterr().err
    assert calls == [["codex", "exec", "--help"]]


# --- the shipped CLI against a real executable, nothing faked but PATH and HOME (ADR 0100) ------

_STUB_BODY = """\
import hashlib, json, os, pathlib, sys, time
spec = json.loads(pathlib.Path(SPEC).read_text(encoding="utf-8"))
stdin = sys.stdin.buffer.read()
entry = {"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin_len": len(stdin),
         "stdin_sha256": hashlib.sha256(stdin).hexdigest()}
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps(entry) + "\\n")
part = spec["help" if sys.argv[1:] == ["exec", "--help"] else "run"]
time.sleep(part["sleep"])
sys.stdout.buffer.write(bytes.fromhex(part["stdout"]))
sys.stdout.flush()
sys.stderr.buffer.write(bytes.fromhex(part["stderr"]))
sys.stderr.flush()
sys.exit(part["exit"])
"""
_HELP_BOTH = "  --ignore-user-config\n  --ephemeral\n"
_REPLY_APPROVE = '{"verdict":"approve","findings":[]}'
_REPLY_CHANGES = '{"verdict":"changes","findings":[{"severity":"major","issue":"real bug"}]}'
_SECRET = "AKIAABCDEFGHIJKLMNOP"


def _part(
    stdout: str | bytes = "",
    stderr: str = "",
    exit_code: int = 0,
    sleep: int = 0,
    stderr_bytes: bytes = b"",
) -> dict[str, object]:
    raw = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
    err = stderr_bytes or stderr.encode("utf-8")
    return {"stdout": raw.hex(), "stderr": err.hex(), "exit": exit_code, "sleep": sleep}


def _stub_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run: dict[str, object] | None = None,
    help_part: dict[str, object] | None = None,
    user_reviewer: dict[str, object] | None = None,
) -> types.SimpleNamespace:
    """`codex` as a real program on a PATH that holds nothing else, so no real codex can run, and a
    temp HOME holding the operator's file. It logs each argv and cwd, then does what it is told."""
    import json

    bin_dir, repo, home = tmp_path / "bin", tmp_path / "repo", tmp_path / "home"
    bin_dir.mkdir()
    repo.mkdir(exist_ok=True)
    log, spec = tmp_path / "calls.jsonl", tmp_path / "stub.json"
    spec.write_text(
        json.dumps({"run": run or _part(_REPLY_APPROVE), "help": help_part or _part(_HELP_BOTH)}),
        encoding="utf-8",
    )
    stub = bin_dir / "codex"
    stub.write_text(
        f"#!{sys.executable}\nSPEC = {str(spec)!r}\nLOG = {str(log)!r}\n{_STUB_BODY}",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    if user_reviewer is not None:
        (home / ".agentic-forge").mkdir(parents=True)
        (home / ".agentic-forge" / "config.json").write_text(
            json.dumps({"external_reviewer": user_reviewer}), encoding="utf-8"
        )
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOME", str(home))

    def calls() -> list[dict[str, object]]:
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    target = tmp_path / "diff.txt"
    target.write_text("TARGET-MARKER", encoding="utf-8")
    argv = ["x", "--repo", str(repo), "--target", str(target)]
    return types.SimpleNamespace(repo=repo, target=target, calls=calls, argv=argv)


_HELP_CALL = ["exec", "--help"]


@pytest.mark.parametrize(
    ("run", "help_part", "isolated", "reason"),
    [
        (_part(stderr=f"auth failed {_SECRET}", exit_code=3), None, False, "process-failure"),
        (_part(_REPLY_APPROVE, exit_code=3), None, False, "process-failure"),  # exit code decides
        (_part("Looks fine to me."), None, False, "invalid-output"),
        (_part('{"verdict":"changes"}'), None, False, "invalid-output"),
        (_part(_REPLY_APPROVE), _part("  --ephemeral\n"), True, "isolation-unsupported"),
        (_part(_REPLY_APPROVE), _part("  --ignore-user-config\n"), True, "isolation-unsupported"),
        (_part(_REPLY_APPROVE), _part(_HELP_BOTH, exit_code=2), True, "isolation-unsupported"),
    ],
)
def test_real_reviewer_failure_says_why_writes_nothing_and_exits_3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    run: dict[str, object],
    help_part: dict[str, object] | None,
    isolated: bool,
    reason: str,
) -> None:
    scene = _stub_reviewer(
        tmp_path,
        monkeypatch,
        run=run,
        help_part=help_part,
        user_reviewer={"isolated": True} if isolated else None,
    )
    out = tmp_path / "review.md"
    assert external_review_cli.main([*scene.argv, "--out", str(out)]) == _EXIT_FAILED
    captured = capsys.readouterr()
    assert f"failed ({reason})" in captured.err
    assert "verdict:" not in captured.out and not out.exists()
    assert _SECRET not in captured.err and "TARGET-MARKER" not in captured.err
    if isolated:  # never a fallback: the only program that ran was the capability check
        assert [c["argv"] for c in scene.calls()] == [_HELP_CALL]


def test_real_reviewer_that_hangs_is_a_timeout_and_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # The CLI has no --timeout, so only the limit is shortened. A real timeout hands back stderr as
    # bytes, which the seam-based tests can only imitate.
    import functools

    scene = _stub_reviewer(tmp_path, monkeypatch, run=_part(_REPLY_APPROVE, sleep=60))
    lib = external_review_cli.external_review
    monkeypatch.setattr(lib, "review_outcome", functools.partial(lib.review_outcome, timeout=1))
    out = tmp_path / "review.md"
    assert external_review_cli.main([*scene.argv, "--out", str(out)]) == _EXIT_FAILED
    captured = capsys.readouterr()
    assert "failed (timeout)" in captured.err and "no result within 1s" in captured.err
    assert "TARGET-MARKER" not in captured.err  # TimeoutExpired's own text holds the argv
    assert "verdict:" not in captured.out and not out.exists()


def test_real_capability_check_that_hangs_is_unsupported_and_runs_no_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    scene = _stub_reviewer(
        tmp_path,
        monkeypatch,
        help_part=_part(_HELP_BOTH, sleep=60),
        user_reviewer={"isolated": True},
    )
    monkeypatch.setattr(external_review_cli.external_review, "_PROBE_TIMEOUT", 1)
    assert external_review_cli.main(scene.argv) == _EXIT_FAILED
    assert "failed (isolation-unsupported)" in capsys.readouterr().err
    assert all(c["argv"] == _HELP_CALL for c in scene.calls())


def test_force_overrides_the_opt_out_but_not_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # --force answers `enabled`. It says nothing about `isolated`, which the operator asked for too.
    scene = _stub_reviewer(
        tmp_path,
        monkeypatch,
        help_part=_part("  --sandbox\n"),
        user_reviewer={"enabled": False, "isolated": True},
    )
    assert external_review_cli.main(scene.argv) == 0
    assert scene.calls() == []
    assert external_review_cli.main([*scene.argv, "--force"]) == _EXIT_FAILED
    assert "failed (isolation-unsupported)" in capsys.readouterr().err
    assert [c["argv"] for c in scene.calls()] == [_HELP_CALL]


@pytest.mark.parametrize(
    "reply",
    [
        f"{_REPLY_APPROVE}\n{_REPLY_CHANGES}",
        f"{_REPLY_CHANGES}\n{_REPLY_APPROVE}",
        f'He wrote " here.\n{_REPLY_APPROVE}\n{_REPLY_CHANGES}\n{_REPLY_APPROVE}',
    ],
)
def test_real_reply_with_an_approve_and_a_changes_is_changes_everywhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    reply: str,
) -> None:
    from agentic_forge import handoff

    scene = _stub_reviewer(tmp_path, monkeypatch, run=_part(reply))
    out = tmp_path / "review.md"
    assert external_review_cli.main([*scene.argv, "--out", str(out)]) == 1
    assert "verdict: changes" in capsys.readouterr().out
    art = handoff.load_artifact(out, expected_type="review")
    assert art.header["verdict"] == "changes"
    assert [f["issue"] for f in art.header["findings"]] == ["real bug"]


@pytest.mark.parametrize(
    "content", ["y" * 4_000_000 + "TARGET-MARKER", "TARGET-MARKER\x00after a NUL"]
)
def test_target_that_cannot_be_an_argv_element_is_reviewed_through_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    content: str,
) -> None:
    # Regression: a target over Linux's 128 KiB cap on one argv element failed with E2BIG, and one
    # holding a NUL could not be passed at all; both were reported as a skip. The prompt now goes on
    # stdin, so a real program receives every byte of it.
    import hashlib

    scene = _stub_reviewer(tmp_path, monkeypatch)
    scene.target.write_text(content, encoding="utf-8")
    assert external_review_cli.main(scene.argv) == 0
    assert "verdict: approve" in capsys.readouterr().out
    (call,) = scene.calls()
    assert call["argv"] == ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"]
    prompt = external_review_cli.external_review.build_prompt(content, "code").encode("utf-8")
    assert call["stdin_len"] == len(prompt)
    assert call["stdin_sha256"] == hashlib.sha256(prompt).hexdigest()


def test_reviewer_runs_from_a_cwd_that_is_no_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Regression: develop writes the diff to a scratch dir, and from a cwd outside a trusted git
    # repo codex refused to start ("Not inside a trusted directory"), reported as a skip.
    scene = _stub_reviewer(tmp_path, monkeypatch)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    assert external_review_cli.main(["x", "--target", str(scene.target)]) == 0
    assert "verdict: approve" in capsys.readouterr().out
    (call,) = scene.calls()
    assert call["cwd"] == str(scratch.resolve())
    assert "--skip-git-repo-check" in call["argv"] and "read-only" in call["argv"]


def test_a_repo_disabling_the_reviewer_is_named_warned_about_and_still_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    scene = _stub_reviewer(tmp_path, monkeypatch, user_reviewer={"enabled": True})
    (scene.repo / ".agentic-forge").mkdir()
    (scene.repo / ".agentic-forge" / "config.json").write_text(
        '{"external_reviewer":{"enabled":false}}', encoding="utf-8"
    )
    assert external_review_cli.main(scene.argv) == 0
    captured = capsys.readouterr()
    assert "disabled by this repo's config" in captured.out
    assert "overrides your user-level true" in captured.err
    assert scene.calls() == []
    assert external_review_cli.main([*scene.argv, "--force"]) == 0  # the operator can still run it
    assert len(scene.calls()) == 1


def test_symlinked_target_is_refused_even_when_the_reviewer_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # "Before anything runs" includes the opt-out's friendly exit 0: a wrong path is still reported.
    scene = _stub_reviewer(tmp_path, monkeypatch, user_reviewer={"enabled": False})
    link = tmp_path / "link.txt"
    link.symlink_to(scene.target)
    argv = ["x", "--repo", str(scene.repo), "--target", str(link)]
    assert external_review_cli.main(argv) == 1
    assert "refusing --target" in capsys.readouterr().err
    assert scene.calls() == []


@pytest.mark.parametrize("kind", ["directory", "missing-parent"])
def test_out_that_cannot_be_written_is_reported_with_exit_1_after_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, kind: str
) -> None:
    scene = _stub_reviewer(tmp_path, monkeypatch)
    out = tmp_path / "out-dir"
    if kind == "directory":
        out.mkdir()
    else:
        out = out / "review.md"
    assert external_review_cli.main([*scene.argv, "--out", str(out)]) == 1
    captured = capsys.readouterr()
    assert "verdict: approve" in captured.out and "wrote" not in captured.out
    assert "could not write" in captured.err and "Traceback" not in captured.err


def _git_repo(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)


def test_real_git_repo_as_cwd_and_as_repo_reads_that_repos_config_and_stays_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import json
    import shutil
    import subprocess

    git = shutil.which("git")
    assert git is not None
    repo, other = tmp_path / "repo", tmp_path / "other"
    _git_repo(repo)
    _git_repo(other)
    (other / ".agentic-forge").mkdir()
    (other / ".agentic-forge" / "config.json").write_text(
        json.dumps({"external_reviewer": {"enabled": False}}), encoding="utf-8"
    )
    scene = _stub_reviewer(tmp_path, monkeypatch)
    target_only = ["x", "--target", str(scene.target)]

    # As cwd, with the default --repo: it reviews there, and the reviewer runs there.
    monkeypatch.chdir(repo)
    assert external_review_cli.main(target_only) == 0
    assert [c["cwd"] for c in scene.calls()] == [str(repo.resolve())]
    # As --repo, from another git repo: the config that counts is --repo's, not the cwd's.
    assert external_review_cli.main([*target_only, "--repo", str(other)]) == 0
    assert "disabled" in capsys.readouterr().out
    assert len(scene.calls()) == 1
    monkeypatch.chdir(other)  # the cwd's opt-out does not apply to a --repo without one
    assert external_review_cli.main([*target_only, "--repo", str(repo)]) == 0
    assert len(scene.calls()) == 2
    status = subprocess.run(
        [git, "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    assert status.stdout == ""


def test_subdirectory_of_a_git_repo_sees_the_user_opt_out_but_not_the_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # ADR 0100's stated limit, both halves: a repo's opt-out is read from the workdir only, and the
    # operator's holds wherever the call is made.
    import json

    repo = tmp_path / "repo"
    _git_repo(repo)
    (repo / ".agentic-forge").mkdir()
    (repo / ".agentic-forge" / "config.json").write_text(
        json.dumps({"external_reviewer": {"enabled": False}}), encoding="utf-8"
    )
    (repo / "sub").mkdir()
    scene = _stub_reviewer(tmp_path, monkeypatch)
    target_only = ["x", "--target", str(scene.target)]
    monkeypatch.chdir(repo / "sub")
    assert external_review_cli.main(target_only) == 0
    assert len(scene.calls()) == 1  # the known limit
    (tmp_path / "home" / ".agentic-forge").mkdir(parents=True)
    (tmp_path / "home" / ".agentic-forge" / "config.json").write_text(
        json.dumps({"external_reviewer": {"enabled": False}}), encoding="utf-8"
    )
    capsys.readouterr()
    assert external_review_cli.main(target_only) == 0
    assert "disabled" in capsys.readouterr().out
    assert len(scene.calls()) == 1


def test_relative_command_runs_the_operators_program_and_not_a_repo_file_of_that_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The capability check runs from the cwd and the review from the repo, so a relative path would
    # name a different program in each. It is resolved first, against the cwd.
    scene = _stub_reviewer(tmp_path, monkeypatch, user_reviewer={"isolated": True})
    build = tmp_path / "rv"
    build.write_text((tmp_path / "bin" / "codex").read_text(encoding="utf-8"), encoding="utf-8")
    build.chmod(0o755)
    planted = scene.repo / "rv"
    marker = tmp_path / "repo-file-ran"
    planted.write_text(
        f"#!{sys.executable}\nimport pathlib\npathlib.Path({str(marker)!r}).write_text('ran')\n"
        f"print({_REPLY_APPROVE!r})\n",
        encoding="utf-8",
    )
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    assert external_review_cli.main([*scene.argv, "--command", "./rv"]) == 0
    assert not marker.exists()
    assert [c["argv"][:2] for c in scene.calls()] == [_HELP_CALL, ["exec", "--sandbox"]]


def test_reviewer_that_exits_0_with_undecodable_stdout_is_invalid_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    scene = _stub_reviewer(tmp_path, monkeypatch, run=_part(b"\xff\xfe not text"))
    assert external_review_cli.main(scene.argv) == _EXIT_FAILED
    assert "failed (invalid-output)" in capsys.readouterr().err


def test_undecodable_stderr_neither_spoils_a_reply_nor_hides_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Only stdout is the reply: a bad byte in stderr says nothing about it.
    ok, failed = tmp_path / "ok", tmp_path / "failed"
    ok.mkdir()
    failed.mkdir()
    scene = _stub_reviewer(ok, monkeypatch, run=_part(_REPLY_CHANGES, stderr_bytes=b"\xff warn"))
    assert external_review_cli.main(scene.argv) == 1
    assert "real bug" in capsys.readouterr().out
    scene = _stub_reviewer(failed, monkeypatch, run=_part(exit_code=3, stderr_bytes=b"\xff died"))
    assert external_review_cli.main(scene.argv) == _EXIT_FAILED
    err = capsys.readouterr().err
    assert "failed (process-failure)" in err and "exit status 3" in err and "died" in err


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
        {"body": "fix", "path": "a.py", "line": 5, "author": {"login": "rev"},
         "authorAssociation": "MEMBER"}]}}]},
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
    _enable(tmp_path)
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
    _enable(tmp_path)
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
    _enable(tmp_path)
    assert "no repos" in run_scheduled._pr_watch(tmp_path)  # enabled but nothing configured


def test_pr_watch_job_runs_live_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable(tmp_path, ', "repos": ["o/r"]')
    monkeypatch.setattr(
        run_scheduled, "_run_pr_watch_live", lambda repo, specs, trusted: f"ran {len(specs)}"
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


def _checkout(repo: Path) -> None:
    """A real checkout of ``o/r``: a watch pass and the drain ask git about the tree they act on."""
    for args in (
        ("init", "-q", "-b", "main"),
        ("remote", "add", "origin", "https://github.com/o/r.git"),
        ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _enable(_repo: Path, extra: str = "") -> None:
    """The operator's file: a repo's cannot turn the watcher on (ADR 0103)."""
    cfg = Path.home() / ".agentic-forge"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.json").write_text(
        '{"pr_watcher": {"enabled": true' + extra + "}}", encoding="utf-8"
    )


def _log(tmp_path: Path) -> str:
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    return log.read_text(encoding="utf-8") if log.is_file() else ""


@pytest.fixture(autouse=True)
def _no_real_permission_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child asks GitHub about a thread's author, and these threads' authors are made up."""
    monkeypatch.setattr(pr_watch_cli, "_read_permission", lambda *_args: True)


class _Git:
    """A fake `_git(repo, *args)`: records every call; answers per subcommand."""

    def __init__(self, *, dirty: bool = False, diff: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.dirty = dirty  # `status --porcelain` shows changes BEFORE the fixer ran
        self.diff = diff  # `add -A` stages something (the session landed an edit)
        self.commit_exit = 0
        self.commits = True  # `commit` moves HEAD

    def __call__(self, repo: Path, *args: str) -> types.SimpleNamespace:
        self.calls.append(args)
        if args[0] == "status":
            return _completed(" M a.py\n" if self.dirty else "")
        if args[:3] == ("diff", "--cached", "--quiet"):
            return _completed("", returncode=1 if self.diff else 0)
        if args[0] == "rev-parse":  # HEAD moves when something is committed, and not otherwise
            return _completed("abc1234\n" if self.ran("commit") and self.commits else "0000000\n")
        if args[0] == "commit":
            return _completed("", returncode=self.commit_exit, stderr="gpg failed to sign")
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
    pr_watch_cli._fixer_runner("the-model", 10, "/a/fresh/scratch")
    assert seen["env"] == {"CLAUDE_CODE_TMPDIR": "/a/fresh/scratch"}
    assert seen["retries"] == 0  # one attempt: a retry loop could outlive the whole watch pass
    assert seen["call_timeout"] == pr_watch.fixer_timeout(10) == 144
    assert seen["model"] == "the-model"
    # The tree is a PR's, and the comment untrusted: ADR 0103, measured in test_fixer_real_cli.py.
    assert seen["allowed_tools"] is None and seen["tools"] == "Read,Write,Edit,Grep,Glob"
    assert seen["setting_sources"] == "" and seen["permission_mode"] == "acceptEdits"
    assert seen["strict_mcp_config"] is True and seen["session_persistence"] is False
    assert seen["denials_undetermined"] is True
    assert seen["settings"] == pr_watch_cli._fixer_settings()


@pytest.mark.parametrize(
    "staged",
    [
        ".github/workflows/ci.yml\0",
        "a.py\0.gitattributes\0",
        "sub/.gitattributes\0",
        ".gitmodules\0",
        ".husky/pre-commit\0",
        ".agentic-forge/config.json\0",
        ".GitHub/x\0",
    ],
)
def test_fixer_refuses_to_commit_a_protected_path(tmp_path: Path, staged: str) -> None:
    git = _Git(diff=True)
    real = git.__call__

    def with_names(repo: Path, *args: str) -> types.SimpleNamespace:
        if args[:3] == ("diff", "--cached", "--name-only"):
            git.calls.append(args)
            return _completed(staged)
        return real(repo, *args)

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: "done", git=with_names)
    action, why = fix(_THREAD)
    assert action == pr_watch.UNDETERMINED and "not committed" in why
    assert not git.ran("commit")
    assert git.ran("reset", "--hard") and git.ran("clean", "-fdq")  # and it is gone
    assert ("diff", "--cached", "--name-only", "--no-renames", "-z") in git.calls


def test_fixer_commits_a_path_that_merely_looks_protected(tmp_path: Path) -> None:
    git = _Git(diff=True)
    real = git.__call__

    def with_names(repo: Path, *args: str) -> types.SimpleNamespace:
        if args[:3] == ("diff", "--cached", "--name-only"):
            return _completed("docs/github.md\0x.github\0.gitattributes.md\0")
        return real(repo, *args)

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: "done", git=with_names)
    assert fix(_THREAD)[0] == "fixed" and git.ran("commit")


def test_fixer_refuses_at_the_commit_what_a_link_below_a_protected_directory_leads_to(
    tmp_path: Path,
) -> None:
    """A link below `.github` does not stop the session, and its target is protected there."""
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "ci.yml").symlink_to("../ci/ci.yml")
    git = _Git(diff=True)
    real = git.__call__

    def with_tree(repo: Path, *args: str) -> types.SimpleNamespace:
        if args[:3] == ("ls-files", "-s", "-z"):
            return _completed("120000 abc 0\t.github/ci.yml\0")
        if args[:3] == ("diff", "--cached", "--name-only"):
            return _completed("ci/ci.yml\0")
        return real(repo, *args)

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: "done", git=with_tree)
    action, why = fix(_THREAD)
    assert action == pr_watch.UNDETERMINED
    assert "the target of .github/ci.yml" in why and not git.ran("commit")


def test_fixer_starts_no_session_when_a_link_cannot_be_read(tmp_path: Path) -> None:
    git = _Git()
    real = git.__call__
    ran: list[str] = []

    def with_tree(repo: Path, *args: str) -> types.SimpleNamespace:
        if args[:3] == ("ls-files", "-s", "-z"):
            return _completed("120000 abc 0\tmissing-link\0")
        return real(repo, *args)

    def runner(system: str, prompt: str, workdir: Path) -> str:
        ran.append(prompt)
        return "done"

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=runner, git=with_tree)
    assert fix(_THREAD)[0] == pr_watch.UNDETERMINED and ran == []


def test_fixer_starts_no_session_on_a_dirty_tree(tmp_path: Path) -> None:
    git = _Git(dirty=True, diff=True)
    ran: list[str] = []

    def runner(system: str, prompt: str, workdir: Path) -> str:
        ran.append(prompt)
        return "done"

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=runner, git=git)
    assert fix(_THREAD)[0] == pr_watch.UNDETERMINED
    assert ran == [] and not git.ran("reset") and not git.ran("add")  # the user's staging stands


@pytest.mark.parametrize(
    "failing",
    [("add",), ("diff", "--cached", "--quiet"), ("diff", "--cached", "--name-only"), ("commit",)],
    ids=["add", "diff", "listing", "commit"],
)
def test_fixer_says_undetermined_when_git_fails_and_leaves_the_tree_clean(
    tmp_path: Path, failing: tuple[str, ...]
) -> None:
    git = _Git(diff=True)
    real = git.__call__

    def fails(repo: Path, *args: str) -> types.SimpleNamespace:
        if args[: len(failing)] == failing:
            git.calls.append(args)
            return _completed("", returncode=128, stderr="the tail of git's complaint")
        return real(repo, *args)

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: "done", git=fails)
    action, why = fix(_THREAD)
    assert action == pr_watch.UNDETERMINED and "the tail of git's complaint" in why
    assert git.ran("reset", "--hard") and git.ran("clean", "-fdq")


def test_fixer_wants_head_to_have_moved(tmp_path: Path) -> None:
    git = _Git(diff=True)
    git.commits = False  # exit 0, and nothing new: as a hook or a wrapper could leave it
    fix = pr_watch_cli._fixer(tmp_path, "m", runner=lambda s, p, w: "done", git=git)
    action, why = fix(_THREAD)
    assert action == pr_watch.UNDETERMINED and "left HEAD where it was" in why


@pytest.mark.parametrize("failing", [("status",), ("ls-files",)])
def test_fixer_starts_no_session_when_it_cannot_read_the_tree(
    tmp_path: Path, failing: tuple[str, ...]
) -> None:
    git = _Git()
    real = git.__call__
    ran: list[str] = []

    def fails(repo: Path, *args: str) -> types.SimpleNamespace:
        if args[: len(failing)] == failing:
            return _completed("", returncode=128)
        return real(repo, *args)

    def runner(system: str, prompt: str, workdir: Path) -> str:
        ran.append(prompt)
        return "done"

    fix = pr_watch_cli._fixer(tmp_path, "m", runner=runner, git=fails)
    assert fix(_THREAD)[0] == pr_watch.UNDETERMINED and ran == []


@pytest.mark.parametrize("special", ["[", "]", "\\", "*", "?", "{", "(", "!", "#"])
def test_a_config_dir_no_rule_can_spell_gets_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, special: str
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", f"/opt/a{special}b")
    ran: list[str] = []

    def runner(system: str, prompt: str, workdir: Path) -> str:
        ran.append(prompt)
        return "done"

    git = _Git()
    action, why = pr_watch_cli._fixer(tmp_path, "m", runner=runner, git=git)(_THREAD)
    assert action == pr_watch.UNDETERMINED and "no session started" in why and ran == []
    assert "/opt/a" not in why


def test_fixer_settings_deny_the_clis_own_directory() -> None:
    plain = json.loads(pr_watch_cli._fixer_settings({}))
    assert plain["autoMemoryEnabled"] is False
    # No Write rule: the CLI warns about one on every session, and Edit covers the file tools.
    assert plain["permissions"]["deny"] == ["Read(~/.claude/**)", "Edit(~/.claude/**)"]
    dotted = json.loads(pr_watch_cli._fixer_settings({"CLAUDE_CONFIG_DIR": "/opt/x/../cc"}))
    assert "Read(//opt/cc/**)" in dotted["permissions"]["deny"]
    moved = json.loads(pr_watch_cli._fixer_settings({"CLAUDE_CONFIG_DIR": "/opt/cc"}))
    assert "Read(//opt/cc/**)" in moved["permissions"]["deny"]
    assert "Edit(~/.claude/**)" in moved["permissions"]["deny"]


def test_author_checker_asks_once_a_pass_and_not_for_who_the_pr_already_rules_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked: list[str] = []

    def read(repo: Path, slug: str, login: str) -> bool:
        asked.append(login)
        return login == "writer"

    monkeypatch.setattr(pr_watch_cli, "_read_permission", read)
    check = pr_watch_cli._author_checker(tmp_path, "o/r", ("codex",))
    thread = pr_watch.ReviewThread
    writer = thread("A", False, "writer", "b", "p", 1, author_association="MEMBER")
    other = thread("B", False, "reader", "b", "p", 1, author_association="COLLABORATOR")
    stranger = thread("C", False, "x", "b", "p", 1, author_association="NONE")
    app = thread("D", False, "codex", "b", "p", 1, author_association="NONE", author_type="Bot")
    assert check(writer) and check(writer)
    assert not check(other) and not check(stranger) and check(app)
    assert asked == ["writer", "reader"]


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
    assert rc == 1 and "undetermined 1" in out and "fixed 0" in out  # the job must not read as ok
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
    assert ("fetch", "origin", "--", "main") in git.calls  # a base name is never a flag
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


_SAME_REPO = pr_watch.PrHead(False, "a" * 40)


def _pass_seams(tree: Path, **over: object) -> dict[str, object]:
    """A pass with git and gh replaced: a same-repo PR and a directory for its tree."""
    tree.mkdir(exist_ok=True)
    return {
        "read_head": lambda *_: _SAME_REPO,
        "open_tree": lambda *_: tree,
        "close_tree": lambda _tree: None,
        **over,
    }


def test_watch_one_pr_reads_the_exit_code_and_records_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _enable(tmp_path, ', "auto_merge": true, "bot": "trusted[bot]"')
    _checkout(tmp_path)
    cmds: list[list[str]] = []

    def run_watcher(cmd: list[str], cwd: Path) -> int | None:
        cmds.append(cmd)
        return {1: 0, 2: 1, 3: None}[int(cmd[cmd.index("--pr") + 1])]

    watch = run_scheduled._watch_one_pr(
        tmp_path, run_watcher=run_watcher, **_pass_seams(tmp_path / "tree")
    )
    assert watch("o", "r", 1) == run_scheduled.WatchOutcome(True)
    assert _log(tmp_path) == ""  # a completed pass is not an anomaly
    assert watch("o", "r", 2) == run_scheduled.WatchOutcome(False, "watcher exited 1")
    assert watch("o", "r", 3).reason.startswith("watcher killed at the 1800s budget")
    log = _log(tmp_path)
    assert "o/r#2: watcher exited 1" in log and "o/r#3: watcher killed" in log
    assert log.count('"component": "pr-watch-queue"') == 2
    assert "skip #2" in capsys.readouterr().err
    # the trusted settings reach the watcher as argv, after --apply
    assert cmds[0][-6:] == [
        "--apply", "--bot", "trusted[bot]", "--merge-method", "rebase", "--auto-merge"
    ]


def test_watch_one_pr_reports_a_held_thread_as_a_pass_with_a_reason(tmp_path: Path) -> None:
    _enable(tmp_path)
    _checkout(tmp_path)
    watch = run_scheduled._watch_one_pr(
        tmp_path, run_watcher=lambda cmd, cwd: pr_watch.EXIT_HELD,
        **_pass_seams(tmp_path / "tree"),
    )
    assert watch("o", "r", 1) == run_scheduled.WatchOutcome(True, run_scheduled._HELD)
    assert _log(tmp_path) == ""  # held is not an anomaly until it runs out of ticks


def test_watch_one_pr_refuses_a_repo_it_cannot_log_under(tmp_path: Path) -> None:
    _enable(tmp_path)
    ran: list[list[str]] = []

    def no_read(*_args: object) -> pr_watch.PrHead:
        raise AssertionError("it asked GitHub")

    watch = run_scheduled._watch_one_pr(
        tmp_path, read_head=no_read, run_watcher=lambda cmd, cwd: ran.append(cmd) or 0,
    )
    outcome = watch("o", "r", 1)
    assert not outcome.ok and "leads to no checkout" in outcome.reason and ran == []
    assert "leads to no checkout" in _log(tmp_path)


def test_watch_one_pr_passes_the_operators_checkout_for_the_log(tmp_path: Path) -> None:
    _enable(tmp_path)
    _checkout(tmp_path)
    cmds: list[list[str]] = []

    def run_watcher(cmd: list[str], cwd: Path) -> int:
        cmds.append(cmd)
        return 0

    run_scheduled._watch_one_pr(
        tmp_path, run_watcher=run_watcher, **_pass_seams(tmp_path / "tree")
    )("o", "r", 1)
    assert cmds[0][cmds[0].index("--state-repo") + 1] == str(tmp_path)


def test_watch_one_pr_runs_the_watcher_in_the_passs_tree(tmp_path: Path) -> None:
    _enable(tmp_path)
    _checkout(tmp_path)
    seen: list[tuple[list[str], Path]] = []
    closed: list[Path] = []

    def run_watcher(cmd: list[str], cwd: Path) -> int:
        seen.append((cmd, cwd))
        return 0

    tree = tmp_path / "tree"
    trusted = settings.resolve(tmp_path)
    run_scheduled._watch_one_pr(
        tmp_path, trusted=trusted, run_watcher=run_watcher,
        **_pass_seams(tree, close_tree=closed.append),
    )("o", "r", 1)
    ((cmd, cwd),) = seen
    assert cwd == tree and cmd[cmd.index("--repo") + 1] == str(tree) and closed == [tree]
    assert "--from-scheduler" in cmd and not any(c.startswith("--model") for c in cmd)
    assert "--auto-merge" not in cmd and "--merge-only" not in cmd


def test_watch_one_pr_passes_the_operators_model_and_the_per_repo_merge(tmp_path: Path) -> None:
    _enable(tmp_path, ', "auto_merge": ["O/R", "o/other"]')
    user_file = Path.home() / ".agentic-forge" / "config.json"
    held = json.loads(user_file.read_text(encoding="utf-8"))
    user_file.write_text(
        json.dumps({**held, "models": {"software-engineer": "user-model"}}), encoding="utf-8"
    )
    _checkout(tmp_path)
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        '{"models": {"software-engineer": "repo-model"}}', encoding="utf-8"
    )
    cmds: list[list[str]] = []

    def run_watcher(cmd: list[str], cwd: Path) -> int:
        cmds.append(cmd)
        return 0

    watch = run_scheduled._watch_one_pr(
        tmp_path, run_watcher=run_watcher, **_pass_seams(tmp_path / "tree")
    )
    watch("o", "r", 1)
    watch("o", "third", 2)
    assert "--model=user-model" in cmds[0] and "--auto-merge" in cmds[0]
    assert "--auto-merge" not in cmds[1]


def test_watch_one_pr_gives_another_repos_pr_no_tree(tmp_path: Path) -> None:
    _enable(tmp_path, ', "auto_merge": ["o/other"]')
    _checkout(tmp_path)
    seen: list[tuple[list[str], Path]] = []

    def no_tree(*_args: object) -> Path:
        raise AssertionError("a tree for another repo's PR")

    def run_watcher(cmd: list[str], cwd: Path) -> int:
        seen.append((cmd, cwd))
        return 0

    watch = run_scheduled._watch_one_pr(
        tmp_path, read_head=lambda *_: _SAME_REPO, open_tree=no_tree, run_watcher=run_watcher,
    )
    assert watch("o", "other", 2).ok
    ((cmd, cwd),) = seen
    assert "--merge-only" in cmd and "--auto-merge" in cmd and cwd == tmp_path


def test_watch_one_pr_removes_the_tree_when_the_watcher_raises(tmp_path: Path) -> None:
    _enable(tmp_path)
    _checkout(tmp_path)
    closed: list[Path] = []
    tree = tmp_path / "tree"

    def run_watcher(cmd: list[str], cwd: Path) -> int:
        raise OSError("could not start")

    watch = run_scheduled._watch_one_pr(
        tmp_path, run_watcher=run_watcher, **_pass_seams(tree, close_tree=closed.append)
    )
    with pytest.raises(OSError, match="could not start"):
        watch("o", "r", 1)
    assert closed == [tree]


def test_read_head_raises_when_gh_fails_and_reads_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([
        _completed("", returncode=4),
        _completed('{"data": {"repository": {"pullRequest": {"isCrossRepository": true}}}}'),
    ])
    monkeypatch.setattr(run_scheduled.subprocess, "run", lambda *a, **k: next(answers))
    with pytest.raises(RuntimeError, match="exited 4"):
        run_scheduled._read_head(tmp_path, "o", "r", 1)
    assert run_scheduled._read_head(tmp_path, "o", "r", 1).cross_repo is True


def test_a_worktree_that_will_not_open_is_recorded_and_nothing_runs(tmp_path: Path) -> None:
    _enable(tmp_path)
    _checkout(tmp_path)
    ran: list[list[str]] = []

    def run_watcher(cmd: list[str], cwd: Path) -> int | None:
        ran.append(cmd)
        return 0

    def refused(*_args: object) -> Path:
        raise RuntimeError("git worktree add failed (exit 128)")

    watch = run_scheduled._watch_one_pr(
        tmp_path, component="pr-watch", run_watcher=run_watcher,
        read_head=lambda *_: _SAME_REPO, open_tree=refused,
    )
    assert watch("o", "r", 9).reason == "no worktree for the PR: git worktree add failed (exit 128)"
    assert ran == []

    def hung(*_args: object) -> Path:
        raise subprocess.TimeoutExpired(cmd="git", timeout=120)

    watch = run_scheduled._watch_one_pr(
        tmp_path, run_watcher=run_watcher, read_head=lambda *_: _SAME_REPO, open_tree=hung,
    )
    assert watch("o", "r", 9).reason.startswith("no worktree for the PR: ")
    log = _log(tmp_path)
    assert '"component": "pr-watch"' in log and "git worktree add failed" in log


def test_open_worktree_cleans_up_after_a_refused_add(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(tmp_path)
    real = run_scheduled._git

    def git(repo: Path, *args: str, **kwargs: object) -> object:
        if args[0] == "fetch":
            return _completed("")
        if args[0] == "worktree":
            return _completed("", returncode=128, stderr="fatal: nope")
        return real(repo, *args)

    monkeypatch.setattr(run_scheduled, "_git", git)
    head = real(tmp_path, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(RuntimeError, match=r"git worktree add failed \(exit 128\): fatal: nope"):
        run_scheduled._open_worktree(tmp_path, 7, head)
    assert list(run_scheduled._passes_dir(tmp_path).iterdir()) == []


def test_a_timed_out_add_removes_what_it_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(tmp_path)
    real = run_scheduled._git
    removed: list[tuple[str, ...]] = []

    def git(repo: Path, *args: str, **kwargs: object) -> object:
        if args[0] == "fetch":
            return _completed("")
        if args[:2] == ("worktree", "add"):
            raise subprocess.TimeoutExpired(cmd="git", timeout=600)
        if args[:2] == ("worktree", "remove"):
            removed.append(args)
            return _completed("")
        return real(repo, *args)

    monkeypatch.setattr(run_scheduled, "_git", git)
    head = real(tmp_path, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(subprocess.TimeoutExpired):
        run_scheduled._open_worktree(tmp_path, 7, head)
    assert removed and removed[0][2:4] == ("--force", "--force")
    assert list(run_scheduled._passes_dir(tmp_path).iterdir()) == []


def test_git_output_need_not_be_utf8(tmp_path: Path) -> None:
    _checkout(tmp_path)
    bad = os.fsencode(tmp_path) + b"/wt-\xe9"
    subprocess.run(
        [b"git", b"-C", os.fsencode(tmp_path), b"worktree", b"add", b"-q", b"--detach", bad],
        check=True, capture_output=True,
    )
    done = run_scheduled._git(tmp_path, "worktree", "list", "--porcelain")
    assert done.returncode == 0 and "wt-\udce9" in done.stdout


def test_a_worktree_that_will_not_close_is_recorded_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _checkout(tmp_path)
    run_scheduled._close_worktree(tmp_path, tmp_path / "no-such-worktree")  # real git refuses it
    assert "git worktree remove failed (exit" in capsys.readouterr().err
    assert "git worktree remove failed" in _log(tmp_path)

    def no_git(*_args: object, **_kwargs: object) -> None:
        raise OSError("git")

    monkeypatch.setattr(run_scheduled, "_git", no_git)
    run_scheduled._close_worktree(tmp_path, tmp_path / "x")
    assert "git worktree remove failed: git" in capsys.readouterr().err


def test_leftovers_are_not_a_failure_when_git_will_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def no_git(*_args: object, **_kwargs: object) -> None:
        raise OSError("git")

    monkeypatch.setattr(run_scheduled, "_git", no_git)
    stray = run_scheduled._passes_dir(tmp_path) / "stray"
    stray.mkdir(parents=True)
    run_scheduled._remove_leftovers(tmp_path)
    assert "leftovers not checked" in capsys.readouterr().err
    assert not stray.exists()  # what is ours on disk still goes


def test_a_repo_directory_that_will_not_open_runs_unlocked(tmp_path: Path) -> None:
    with run_scheduled._run_lock(tmp_path / "missing") as held:
        assert held is True


def test_the_watcher_inherits_the_run_lock(tmp_path: Path) -> None:
    spawned: dict[str, object] = {}

    def popen(cmd: list[str], **kwargs: object) -> _Proc:
        spawned.update(kwargs)
        return _Proc()

    run_scheduled._run_watcher(["w"], tmp_path, 7.0, popen=popen)
    assert spawned["pass_fds"] == ()  # no lock is held here
    with run_scheduled._run_lock(tmp_path) as held:
        assert held is True
        run_scheduled._run_watcher(["w"], tmp_path, 7.0, popen=popen)
        fds = spawned["pass_fds"]
        assert isinstance(fds, tuple) and len(fds) == 1 and fds[0] == run_scheduled._lock_fd
    assert run_scheduled._lock_fd is None


def test_an_out_of_scope_drop_shows_for_a_week_and_counts_while_recent(tmp_path: Path) -> None:
    entry = pr_watch.WatchEntry("o", "renamed", 7)
    assert run_scheduled._out_of_scope_line(tmp_path, 1000.0) == ""
    run_scheduled._note_out_of_scope(tmp_path, entry, 1000.0)
    run_scheduled._note_out_of_scope(tmp_path, pr_watch.WatchEntry("o", "renamed", 8), 2000.0)
    line = run_scheduled._out_of_scope_line(tmp_path, 3000.0)
    assert "2 queued PR(s)" in line and "o/renamed#8" in line and "renamed repo" in line
    week = run_scheduled._OUT_OF_SCOPE_SHOWN_SECONDS
    assert run_scheduled._out_of_scope_line(tmp_path, 2000.0 + week) == ""
    run_scheduled._note_out_of_scope(tmp_path, entry, 2000.0 + week)
    assert "1 queued PR(s)" in run_scheduled._out_of_scope_line(tmp_path, 2000.0 + week)


@pytest.mark.parametrize("text", ["not json", "[]"])
def test_an_unreadable_out_of_scope_note_reads_as_none(tmp_path: Path, text: str) -> None:
    diagnostics.write_state(tmp_path, run_scheduled._OUT_OF_SCOPE_FILE, text)
    assert run_scheduled._out_of_scope_line(tmp_path, 1000.0) == ""


def test_an_out_of_scope_note_that_cannot_be_saved_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*_args: object) -> None:
        raise OSError("refused")

    monkeypatch.setattr(run_scheduled.diagnostics, "write_state", refused)
    run_scheduled._note_out_of_scope(tmp_path, pr_watch.WatchEntry("o", "r", 1), 1.0)


def test_an_unreadable_skip_count_reads_as_none(tmp_path: Path) -> None:
    diagnostics.write_state(tmp_path, run_scheduled._LOCK_SKIPS_FILE, "not json")
    assert run_scheduled._lock_skips(tmp_path) == 0
    diagnostics.write_state(tmp_path, run_scheduled._LOCK_SKIPS_FILE, "true")
    assert run_scheduled._lock_skips(tmp_path) == 0


def test_a_skip_that_cannot_be_saved_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*_args: object) -> None:
        raise OSError("refused")

    monkeypatch.setattr(run_scheduled.diagnostics, "write_state", refused)
    run_scheduled._note_lock_skip(tmp_path)


def test_the_watcher_under_the_scheduler_does_not_read_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    user_level = Path.home() / ".agentic-forge"
    user_level.mkdir(parents=True, exist_ok=True)
    (user_level / "config.json").write_text(  # the driver already merged this with the repo's
        '{"pr_watcher": {"enabled": true}, "models": {"software-engineer": "user-model"}}',
        encoding="utf-8",
    )
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        '{"models": {"software-engineer": "pr-model"}, "pr_watcher": {"enabled": false}}',
        encoding="utf-8",
    )
    seen: list[str] = []

    def fixer(repo: Path, model: str, **_kwargs: object) -> object:
        seen.append(model)
        return lambda t: ("fixed", "done")

    monkeypatch.setattr(pr_watch_cli, "_fixer", fixer)
    argv = ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42"]
    common: dict[str, object] = {
        "fetch": _pr_fetch, "gh_exec": lambda argv: None, "push": lambda: None,
    }
    rc = pr_watch_cli.main(
        [*argv, "--from-scheduler", "--model=argv-model", "--bot", "b", "--apply"], **common
    )
    assert rc == 0 and seen == ["argv-model"]  # not switched off, and not the PR's model
    assert "fixed 1" in capsys.readouterr().out

    # Run by hand, in the same tree, the repo's file counts for the two things it may still say.
    rc = pr_watch_cli.main([*argv, "--apply"], **common)
    assert rc == 0 and "disabled" in capsys.readouterr().out


def test_a_conflict_merge_whose_push_fails_fails_the_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """No thread to go undetermined here, and the base was merged in for nothing."""
    _enable(tmp_path)
    conflicted = {"data": {"repository": {"pullRequest": {
        "number": 42, "mergeable": "CONFLICTING", "headRefName": "f", "baseRefName": "main",
        "reviewThreads": {"nodes": []},
    }}}}

    def refused() -> None:
        raise RuntimeError("non-fast-forward")

    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42", "--apply"],
        fetch=lambda *a, **k: conflicted, handle_conflict=lambda: True, push=refused,
        gh_exec=lambda argv: None,
    )
    assert rc == 1 and "pushed=False" in capsys.readouterr().out


def test_merge_only_fixes_nothing_pushes_nothing_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _enable(tmp_path)
    calls: list[list[str]] = []
    pushed: list[bool] = []

    def fixer(thread: object) -> tuple[str, str]:
        raise AssertionError("the fixer ran")

    rc = pr_watch_cli.main(
        ["x", "--repo", str(tmp_path), "--owner", "o", "--name", "r", "--pr", "42",
         "--from-scheduler", "--merge-only", "--bot", "b", "--apply"],
        fetch=_pr_fetch, fixer=fixer, gh_exec=calls.append, push=lambda: pushed.append(True),
    )
    assert rc == 1 and calls == [] and pushed == []
    assert "fix and push refused for o/r#42" in capsys.readouterr().err
    assert "fix and push refused for o/r#42" in _log(tmp_path)


# F2c / F3: every entry's tick advances, the queue is persisted, THEN failed passes are reported.


def _queue(tmp_path: Path, entries: list[dict]) -> Path:
    _checkout(tmp_path)
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


def test_tier2_runners_point_the_session_at_the_plugin_under_test(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ten skill bodies invoke their scripts as `${CLAUDE_PLUGIN_ROOT}/skills/.../scripts/...` and
    the harness never set it, so a session resolved it to the INSTALLED plugin and graded a build
    four versions behind the tree under test (ADR 0097). Both runners now carry it."""
    import _eval_cli

    seen: list[dict] = []

    def fake_runner(**kwargs: object):
        seen.append(dict(kwargs))
        return lambda s, p, w: "out"

    monkeypatch.setattr(_eval_cli.agent_eval, "claude_cli_runner", fake_runner)
    _eval_cli.build_runners("claude", allowed_tools="Bash", model="m", plugin_dir=tmp_path)
    assert len(seen) == 2  # component and grader
    assert all(kw["env"]["CLAUDE_PLUGIN_ROOT"] == str(tmp_path.resolve()) for kw in seen)
    assert all("CLAUDE_SKILL_DIR" in kw["env"] for kw in seen)  # the whole contract, ADR 0098

    seen.clear()  # no plugin dir given -> no env override, the old behaviour
    _eval_cli.build_runners("claude", allowed_tools="Bash", model="m")
    assert all(kw["env"] is None for kw in seen)


def test_claude_cli_runner_passes_the_env_to_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from agentic_forge import agent_eval

    captured: dict[str, object] = {}

    class _Done:
        returncode = 0
        stdout = '{"result": "ok", "num_turns": 2}'

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _Done()

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", fake_run)
    runner = agent_eval.claude_cli_runner(env={"CLAUDE_PLUGIN_ROOT": "/plug"})
    runner("sys", "prompt", tmp_path)
    env = captured["env"]
    assert isinstance(env, dict) and env["CLAUDE_PLUGIN_ROOT"] == "/plug"
    assert "PATH" in env  # the real environment is inherited, not replaced

