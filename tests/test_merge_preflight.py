"""Tests for the pre-merge preflight (ADR 0076) — pure rule + the hook's contract.

The rule exists because `gh pr merge`'s *local* half failed twice while developing this plugin,
each time from a condition visible in one cheap git read beforehand. It must WARN and never block:
the merge itself is durable (it happens on the server), so refusing it would trade a recoverable
annoyance for a wedged workflow.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "lib"))

from agentic_forge import guardrails  # noqa: E402

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
    assert "pre-merge" in result.stderr and "ahead" in result.stderr
