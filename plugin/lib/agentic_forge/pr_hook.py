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

__all__ = ["created_pr_url", "is_pr_create", "pr_created_notice", "created_pr_ref", "NOTICE"]

# The reminder printed into the transcript. It names the follow-up explicitly so the session can act
# on it; it does not itself start anything (a hook must not launch a merging agent — ADR 0063 §6).
NOTICE = (
    "agentic-forge: pull request created. Autonomous watch is available — run /pr-watch to poll "
    "checks, triage review comments, resolve conflicts, and (when pr_watcher.auto_merge is on and "
    "the merge gate opens) merge."
)

# A PR URL in the command's output, e.g. https://github.com/owner/name/pull/11
_PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/\d+")


_SEPARATORS = "\n;&|"
# Tokens that may precede the real command word: an env assignment (`GH_TOKEN=x gh …`) or a
# wrapper. Without this a perfectly ordinary invocation is invisible to the hook.
_WRAPPERS = frozenset({"command", "sudo", "env", "nohup", "time", "exec"})
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _segments(command: str) -> list[list[str]]:
    """Split a shell command into token lists per segment (newline, ``;``, ``&&``, ``||``, ``|``).

    Quote-aware, so a separator *inside* quotes stays data. Two things the plain
    ``shlex.split`` version missed (ADR 0067): **newlines** — the most common separator in a
    generated multi-line command, previously collapsed into ordinary whitespace so `push` and
    `create` merged into one segment — and **unspaced** operators (`a;b`, `a&&b`), which stayed
    glued to their neighbours. ``punctuation_chars`` makes the lexer emit them as tokens regardless
    of spacing.

    An unparseable command yields no segments — the hook then simply stays silent, which is the safe
    direction for a reminder."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=_SEPARATORS)
        lexer.whitespace_split = True
        lexer.whitespace = " \t\r"  # newline must reach the punctuation logic, not be eaten
        lexer.commenters = ""  # keep `#` as data, as the previous comments=False did
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(ch in _SEPARATORS for ch in token):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _command_word(tokens: list[str]) -> list[str]:
    """Drop leading env assignments and wrappers so the real command word comes first."""
    i = 0
    while i < len(tokens) and (_ENV_ASSIGN.match(tokens[i]) or tokens[i] in _WRAPPERS):
        i += 1
    return tokens[i:]


def is_pr_create(command: str) -> bool:
    """True if ``command`` actually invokes ``gh pr create`` at a command position.

    Matches the first three meaningful tokens of a segment — after stripping env assignments and
    wrappers — so `gh pr create …`, `GH_TOKEN=x gh pr create` and a create on its own line all fire,
    while `gh pr view`, `gh pr merge`, and a quoted `"gh pr create"` inside a `--body` do not."""
    for tokens in _segments(command):
        head = _command_word(tokens)
        if len(head) >= 3 and head[0] == "gh" and head[1] == "pr" and head[2] == "create":
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
    tool_input = payload.get("tool_input")
    command = str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""
    if not is_pr_create(command):
        return ""
    response = payload.get("tool_response")
    # Read the SUCCESS channel only. `gh pr create` on a branch that already has a PR fails with
    # `a pull request … already exists:` followed by that PR's URL — on stderr. Searching the whole
    # flattened response therefore announced a PR this session did not create, which in autonomous
    # mode is the trigger to start watching (and possibly merging) someone else's PR (ADR 0067).
    if isinstance(response, str):
        blob = response
    elif isinstance(response, dict) and "stdout" in response:
        blob = str(response.get("stdout") or "")
    else:
        blob = json.dumps(response, default=str)
    if "already exists" in blob:
        return ""
    url = created_pr_url(blob)
    return f"{NOTICE}\nPR: {url}" if url else ""


# owner/name/number from a PR URL — what the watch queue needs to identify the PR (ADR 0068).
_PR_REF = re.compile(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/pull/(\d+)")


def created_pr_ref(payload: dict[str, Any]) -> tuple[str, str, int] | None:
    """``(owner, name, number)`` for a PR this payload reports as **created**, else ``None``.

    Deliberately reuses :func:`pr_created_notice`'s decision rather than re-deriving it: the queue
    must be fed by exactly the events that produce the reminder — no more (a failed create must not
    enqueue) and no fewer. The caller gates on ``pr_watcher.auto_watch``; this function only reads.
    """
    notice = pr_created_notice(payload)
    if not notice:
        return None
    match = _PR_REF.search(notice)
    return (match.group(1), match.group(2), int(match.group(3))) if match else None
