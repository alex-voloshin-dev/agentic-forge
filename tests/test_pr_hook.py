"""Tests for the PR-created hook detection (ADR 0063)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

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


# --- ADR 0067: separators and success-channel precision -----------------------


@pytest.mark.parametrize(
    "command",
    [
        # THE flagship shape: the create lands on its own line
        "git push -u origin feat/x\ngh pr create --fill",
        "# comment first\ngh pr create --fill",
        "git push;gh pr create",                            # unspaced `;`
        "git push&&gh pr create --fill",                    # unspaced `&&`
        "GH_TOKEN=x gh pr create --fill",                   # env assignment prefix
        "command gh pr create --fill",                      # wrapper
        "gh pr create --fill | tee log",
    ],
)
def test_detects_every_real_invocation_shape(command: str) -> None:
    # A missed reminder is silent: nothing tells the operator the watch never started.
    assert pr_hook.is_pr_create(command) is True, command


@pytest.mark.parametrize(
    "command",
    [
        "gh pr view 11", "gh pr merge 11 --rebase", "gh pr checks 11", "gh pr list",
        'gh pr comment 1 --body "run gh pr create next"',
        'echo "gh pr create"',
        'gh pr comment 5 --body "line1\ngh pr create\nline3"',  # newline INSIDE quotes stays data
    ],
)
def test_near_misses_still_do_not_fire(command: str) -> None:
    assert pr_hook.is_pr_create(command) is False, command


def test_failed_create_whose_error_carries_a_url_stays_silent() -> None:
    # `gh pr create` on a branch that already has a PR fails — and prints THAT PR's URL on stderr.
    # Announcing it would start an autonomous watch over a PR this session did not create.
    response = {
        "stdout": "",
        "stderr": 'a pull request for branch "x" into branch "y" already exists:\n'
                  "https://github.com/owner/name/pull/11",
    }
    assert pr_hook.pr_created_notice(_payload("gh pr create --fill", response)) == ""


def test_success_is_read_from_stdout() -> None:
    response = {"stdout": _URL, "stderr": "some warning mentioning /pull/99"}
    assert _URL in pr_hook.pr_created_notice(_payload("gh pr create --fill", response))


def test_non_dict_tool_input_does_not_raise() -> None:
    assert pr_hook.pr_created_notice({"tool_name": "Bash", "tool_input": "gh pr create"}) == ""


# --- ADR 0068: the queue reference ---------------------------------------------


def test_created_pr_ref_extracts_owner_name_number() -> None:
    payload = _payload("gh pr create --fill", {"stdout": "https://github.com/acme/widgets/pull/42"})
    assert pr_hook.created_pr_ref(payload) == ("acme", "widgets", 42)


def test_a_failed_create_is_never_enqueued() -> None:
    # The queue must be fed by exactly the events that produce the reminder — no more. Otherwise
    # `already exists:` would enqueue a watch (and possibly a merge) over someone else's PR.
    response = {"stdout": "", "stderr": "already exists:\nhttps://github.com/acme/widgets/pull/9"}
    assert pr_hook.created_pr_ref(_payload("gh pr create --fill", response)) is None


def test_a_non_create_command_is_never_enqueued() -> None:
    assert pr_hook.created_pr_ref(_payload("gh pr view 11", {"stdout": _URL})) is None
