"""Tests for the pre-merge preflight (ADR 0076) — pure rule + the hook's contract.

The rule exists because `gh pr merge`'s *local* half failed twice while developing this plugin,
each time from a condition visible in one cheap git read beforehand. It must WARN and never block:
the merge itself is durable (it happens on the server), so refusing it would trade a recoverable
annoyance for a wedged workflow.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "lib"))
sys.path.insert(0, str(_REPO / "plugin" / "hooks" / "scripts"))

import merge_preflight  # noqa: E402  — the hook script, for the in-process tests

from agentic_forge import diagnostics, guardrails  # noqa: E402

_HOOK = _REPO / "plugin" / "hooks" / "scripts" / "merge_preflight.py"
_MAIN = "/repo"


@pytest.mark.parametrize(
    "command,expected",
    [
        ("gh pr merge 27 --rebase", True),
        ("gh pr merge --squash --delete-branch", True),
        ("cd /x && gh pr merge 1", True),
        ("gh --repo o/n pr merge 3", True),
        ('git commit -m "gh pr merge"', False),  # a quoted mention is not a merge
        ("gh pr view 27", False),
        ("gh pr create --title x", False),
        ("echo gh pr merge", False),  # not in command position
        # --- 2026-09 audit (A7): per quote-aware segment, heredoc bodies stripped ---
        ('echo "x; gh pr merge 1"', False),  # a separator inside a quoted string
        ("cat > notes.md <<'EOF'\ngh pr merge 1\nEOF", False),  # a heredoc body is data
        ("GH_TOKEN=x gh pr merge 2", True),
        ("gh pr merge 12 --rebase && git pull", True),
        ("echo don't; gh pr merge 3", True),  # unparseable segment: the text match still fires
    ],
)
def test_is_pr_merge(command: str, expected: bool) -> None:
    assert guardrails.is_pr_merge(command) is expected


def test_worktree_branches_parses_and_skips_detached() -> None:
    porcelain = (
        "worktree /repo\nHEAD abc\nbranch refs/heads/master\n\n"
        "worktree /repo/../wt-a\nHEAD def\nbranch refs/heads/feat/x\n\n"
        "worktree /repo/../wt-detached\nHEAD 123\ndetached\n"
    )
    assert guardrails.worktree_branches(porcelain) == {
        "/repo": "master",
        "/repo/../wt-a": "feat/x",
    }


def test_preflight_clean_state_is_silent() -> None:
    decision = guardrails.merge_preflight(
        "master", {_MAIN: "master", "/wt-a": "feat/x"}, 0, main_root=_MAIN
    )
    assert decision == guardrails.ALLOW


def test_preflight_warns_when_a_worktree_holds_the_base() -> None:
    decision = guardrails.merge_preflight(
        "master", {_MAIN: "feat/x", "/wt-a": "master"}, 0, main_root=_MAIN
    )
    assert not decision.block  # never blocks
    assert "/wt-a" in decision.message and "worktree" in decision.message


def test_preflight_warns_when_local_base_is_ahead() -> None:
    decision = guardrails.merge_preflight("master", {_MAIN: "master"}, 2, main_root=_MAIN)
    assert not decision.block
    assert "ahead" in decision.message and "2" in decision.message


def test_preflight_reports_both_problems_at_once() -> None:
    decision = guardrails.merge_preflight(
        "master", {_MAIN: "master", "/wt-a": "master"}, 1, main_root=_MAIN
    )
    assert "worktree" in decision.message and "ahead" in decision.message


def test_main_checkout_holding_the_base_is_normal() -> None:
    """The main checkout is *supposed* to be on the base branch — that must not warn."""
    assert guardrails.merge_preflight("master", {_MAIN: "master"}, 0, main_root=_MAIN).message == ""


# --- the hook script ---------------------------------------------------------


def _run_hook(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_HOOK)], input=json.dumps(payload), capture_output=True, text=True
    )


def test_hook_ignores_non_merge_commands(tmp_path: Path) -> None:
    result = _run_hook(
        {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": "gh pr view 1"}}
    )
    assert result.returncode == 0 and result.stderr == ""


def test_hook_never_blocks_outside_a_repo(tmp_path: Path) -> None:
    """No git repo, no `origin/HEAD` -> nothing to say, and certainly no failure."""
    result = _run_hook(
        {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": "gh pr merge 1"}}
    )
    assert result.returncode == 0


def test_hook_survives_malformed_input() -> None:
    result = subprocess.run(
        [sys.executable, str(_HOOK)], input="not json", capture_output=True, text=True
    )
    assert result.returncode == 0


def test_hook_warns_on_a_real_repo_with_a_diverged_base(tmp_path: Path) -> None:
    """End-to-end on a real git repo: an ahead-of-upstream base must produce a warning, exit 0."""
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)], check=True,
                   capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    for key, value in (("user.email", "t@e.st"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(clone), "config", key, value], check=True)
    (clone / "a.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-m", "one"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(clone), "push", "-u", "origin", "master"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(clone), "remote", "set-head", "origin", "master"], check=True)
    (clone / "b.txt").write_text("2", encoding="utf-8")  # a local commit that is NOT pushed
    subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-m", "two"], check=True,
                   capture_output=True)

    payload = {"tool_name": "Bash", "cwd": str(clone), "tool_input": {"command": "gh pr merge 1"}}
    result = _run_hook(payload)
    assert result.returncode == 0  # warn, never block
    # stderr from a hook that exits 0 is debug-log only — the warning has to be JSON on stdout,
    # for the operator (systemMessage) AND the model (additionalContext).
    assert result.stderr == ""
    out = json.loads(result.stdout)
    assert "pre-merge" in out["systemMessage"] and "ahead" in out["systemMessage"]
    assert out["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse", "additionalContext": out["systemMessage"]
    }


# --- the git reads share ONE deadline inside the hook's own timeout (A12) ---------------------


def _fake_git(monkeypatch, *, seconds_per_call: float) -> list[float]:
    """Stub `subprocess.run` + `time.monotonic`: every git call "takes" ``seconds_per_call`` and
    records the timeout it was given."""
    clock = {"now": 100.0}
    timeouts: list[float] = []

    def run(cmd, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock["now"] += seconds_per_call
        out = "origin/master" if "symbolic-ref" in cmd else "0"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(merge_preflight.subprocess, "run", run)
    monkeypatch.setattr(merge_preflight.time, "monotonic", lambda: clock["now"])
    return timeouts


def test_git_reads_share_one_deadline(monkeypatch, tmp_path: Path) -> None:
    """Three reads at 5 s each summed to exactly the hook's 15 s cap in hooks.json, so a stalled
    git got the hook killed by Claude Code instead of recorded by the hook."""
    timeouts = _fake_git(monkeypatch, seconds_per_call=4.0)
    assert merge_preflight.preflight(str(tmp_path), budget=12.0) == guardrails.ALLOW
    assert timeouts == [12.0, 8.0, 4.0]  # each call gets only what is LEFT of the budget
    assert merge_preflight._BUDGET_SECONDS < 15  # the hook's own cap in hooks.json


def test_exhausted_budget_is_recorded_not_killed(monkeypatch, tmp_path: Path, capsys) -> None:
    """Past the deadline the hook raises TimeoutExpired itself — inside its 15 s cap, so the crash
    path still runs: fail open, record it (diagnostics OFF), announce it."""
    monkeypatch.delenv("AGENTIC_FORGE_DIAGNOSTICS", raising=False)
    _fake_git(monkeypatch, seconds_per_call=7.0)  # two calls eat 14 s of a 12 s budget
    payload = {
        "tool_name": "Bash", "cwd": str(tmp_path), "session_id": "s-slow",
        "tool_input": {"command": "gh pr merge 1"},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert merge_preflight.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "merge-preflight hook crashed: TimeoutExpired" in out["systemMessage"]
    events = [json.loads(line) for line in diagnostics.load(tmp_path)]
    assert [e["kind"] for e in events if e["component"] == "merge-preflight"] == ["error"]


# --- a crash is recorded regardless of the diagnostics toggle, and announced once (A5) --------


def test_hook_crash_is_recorded_and_announced_once_per_session(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_DIAGNOSTICS", raising=False)  # the DEFAULT install

    def boom(_cwd: str) -> guardrails.Decision:
        raise RuntimeError("git exploded")

    monkeypatch.setattr(merge_preflight, "preflight", boom)
    payload = {
        "tool_name": "Bash", "cwd": str(tmp_path), "session_id": "s-crash",
        "tool_input": {"command": "gh pr merge 1"},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert merge_preflight.main() == 0  # fail open
    first = json.loads(capsys.readouterr().out)
    assert "merge-preflight hook crashed: RuntimeError: git exploded" in first["systemMessage"]
    assert "failing open" in first["systemMessage"]

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert merge_preflight.main() == 0
    assert capsys.readouterr().out == ""  # same session: said once

    events = [json.loads(line) for line in diagnostics.load(tmp_path)]
    crashes = [e for e in events if e["component"] == "merge-preflight"]
    assert len(crashes) == 2 and all(e["kind"] == "error" for e in crashes)  # BOTH recorded
