"""Tests for the PR-created hook detection (ADR 0063)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from agentic_forge import pr_hook

_URL = "https://github.com/owner/name/pull/11"
HOOK = Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "scripts" / "pr_created.py"


def _payload(command: str, response: Any = _URL) -> dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": response,
        "cwd": ".",
    }


# --- is_pr_create (command-position discipline, ADR 0054) --------------------


def test_detects_a_real_create() -> None:
    assert pr_hook.is_pr_create("gh pr create --title x --body y") is True


def test_detects_create_after_a_separator() -> None:
    assert pr_hook.is_pr_create("git push -u origin b && gh pr create --fill") is True


def test_ignores_other_gh_pr_subcommands() -> None:
    for cmd in ("gh pr view 11", "gh pr merge 11 --rebase", "gh pr checks 11", "gh pr list"):
        assert pr_hook.is_pr_create(cmd) is False, cmd


def test_ignores_a_quoted_mention() -> None:
    # A --body that talks ABOUT the command is data, not an invocation.
    assert pr_hook.is_pr_create('gh pr comment 1 --body "run gh pr create next"') is False
    assert pr_hook.is_pr_create('echo "gh pr create"') is False


def test_unparseable_command_is_silent() -> None:
    assert pr_hook.is_pr_create('gh pr create --body "unterminated') is False


# --- pr_created_notice -------------------------------------------------------


def test_notice_on_successful_create() -> None:
    notice = pr_hook.pr_created_notice(_payload("gh pr create --fill"))
    assert pr_hook.NOTICE in notice and _URL in notice


def test_no_notice_when_create_failed() -> None:
    # gh prints the URL only on success; without one there may be no PR to watch.
    assert pr_hook.pr_created_notice(_payload("gh pr create --fill", "error: no commits")) == ""


def test_no_notice_for_other_tools_or_commands() -> None:
    assert pr_hook.pr_created_notice({"tool_name": "Read", "tool_input": {}}) == ""
    assert pr_hook.pr_created_notice(_payload("gh pr view 11")) == ""


def test_notice_reads_a_structured_response() -> None:
    # The response may be a dict (stdout/stderr) rather than a bare string.
    payload = _payload("gh pr create --fill", {"stdout": _URL, "stderr": ""})
    assert _URL in pr_hook.pr_created_notice(payload)


def test_notice_survives_a_non_serialisable_response() -> None:
    assert pr_hook.pr_created_notice(_payload("gh pr create", {"o": object()})) == ""


def test_created_pr_url_extracts_only_a_pull_url() -> None:
    assert pr_hook.created_pr_url("see https://github.com/o/n/pull/3 now") == (
        "https://github.com/o/n/pull/3"
    )
    assert pr_hook.created_pr_url("https://github.com/o/n/issues/3") == ""
    assert pr_hook.created_pr_url(None) == ""


# --- the hook script (never blocks) -----------------------------------------


def _run_hook(payload: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        capture_output=True, text=True, check=False,
    )


def test_hook_prints_notice_and_exits_zero() -> None:
    done = _run_hook(_payload("gh pr create --fill"))
    assert done.returncode == 0 and _URL in done.stdout


def test_hook_silent_for_unrelated_calls() -> None:
    done = _run_hook(_payload("gh pr view 11"))
    assert done.returncode == 0 and done.stdout.strip() == ""


def test_hook_never_blocks_on_malformed_stdin() -> None:
    # A reminder hook must not break a session, whatever it is fed.
    done = _run_hook("not json at all")
    assert done.returncode == 0
