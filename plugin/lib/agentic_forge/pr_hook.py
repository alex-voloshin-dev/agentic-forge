"""PR-created detection for the PostToolUse hook (ADR 0063).

Pure: given a hook payload, decide whether the session just **created** a pull request and, if so,
produce the reminder that starts the autonomous watch. Kept out of the hook script so it is unit
tested like every other guardrail decision — the script is only stdin/stdout plumbing.

Deliberately narrow: it matches `gh pr create` on the **command word** of a segment (the
`command-position` discipline of ADR 0054), so a quoted mention in an echo, a `--body` that talks
*about* `gh pr create`, or `gh pr view` never fires it.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

__all__ = ["created_pr_url", "is_pr_create", "pr_created_notice", "NOTICE"]

# The reminder printed into the transcript. It names the follow-up explicitly so the session can act
# on it; it does not itself start anything (a hook must not launch a merging agent — ADR 0063 §6).
NOTICE = (
    "agentic-forge: pull request created. Autonomous watch is available — run /pr-watch to poll "
    "checks, triage review comments, resolve conflicts, and (when pr_watcher.auto_merge is on and "
    "the merge gate opens) merge."
)

# A PR URL in the command's output, e.g. https://github.com/owner/name/pull/11
_PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/\d+")


def _segments(command: str) -> list[list[str]]:
    """Split a shell command into token lists per segment (``;`` / ``&&`` / ``||`` / ``|``).

    Quote-aware via ``shlex``, so a separator *inside* quotes stays data. An unparseable command
    yields no segments — the hook then simply stays silent, which is the safe direction for a
    reminder."""
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in (";", "&&", "||", "|", "&"):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def is_pr_create(command: str) -> bool:
    """True if ``command`` actually invokes ``gh pr create`` at a command position.

    Matches the first three meaningful tokens of a segment, so `gh pr create …` fires while
    `gh pr view`, `gh pr merge`, and a quoted `"gh pr create"` inside a `--body` do not."""
    for tokens in _segments(command):
        if len(tokens) >= 3 and tokens[0] == "gh" and tokens[1] == "pr" and tokens[2] == "create":
            return True
    return False


def created_pr_url(output: Any) -> str:
    """The PR URL `gh pr create` printed, or ``""``. ``gh` writes the URL to stdout on success, so
    its presence is also the success signal — a failed create prints an error instead, and the hook
    then stays silent rather than announcing a PR that does not exist."""
    match = _PR_URL.search(str(output or ""))
    return match.group(0) if match else ""


def pr_created_notice(payload: dict[str, Any]) -> str:
    """The reminder for a PostToolUse payload, or ``""`` when this was not a successful PR create.

    Requires **both** that the command was a real `gh pr create` and that a PR URL came back, so a
    dry `--help`, a failed create, or a mere mention produces nothing."""
    if str(payload.get("tool_name") or "") != "Bash":
        return ""
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not is_pr_create(command):
        return ""
    response = payload.get("tool_response")
    # The response shape varies (a plain string, or a dict with stdout/output) — flatten to text so
    # the URL search works either way. `default=str` keeps a non-serialisable value from raising.
    blob = response if isinstance(response, str) else json.dumps(response, default=str)
    url = created_pr_url(blob)
    return f"{NOTICE}\nPR: {url}" if url else ""
