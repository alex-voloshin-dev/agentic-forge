"""Deterministic L4 guardrail logic (ADR 0019).

The hook scripts under ``plugin/hooks/scripts/`` are thin: they parse the Claude Code hook
payload and call these tested functions. Every decision here is deterministic so it is fast,
predictable, and unit-testable without a model.

- :func:`classify_command` — the **security** deny-list (block clearly-dangerous Bash).
- :func:`is_commit_or_push` / :func:`choose_gate` — the **test-gate** (which fast gate to run
  before a commit/push).
- :func:`redact_secrets` / :func:`audit_record` — the **logging** audit record.
- :func:`bump_and_check` — the **budgets** subagent counter (warn/block).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "Decision",
    "ALLOW",
    "classify_command",
    "is_commit_or_push",
    "choose_gate",
    "redact_secrets",
    "audit_record",
    "bump_and_check",
]


@dataclass(frozen=True)
class Decision:
    """A guardrail outcome. ``block`` -> the hook exits 2; a non-empty ``message`` with
    ``block=False`` -> a non-blocking warning (the hook prints it and exits 0)."""

    block: bool
    message: str = ""


ALLOW = Decision(False)


# --- security: dangerous-command deny-list -----------------------------------

# A target that means "everything": filesystem root or the home directory (not /tmp/x etc.).
_ROOT_TARGET = re.compile(r"(^|\s)(/|/\*|~|\$HOME|\$\{HOME\})(\s|/?\*?\s|$)")
_RM = re.compile(r"\brm\b")
_RM_RECURSIVE = re.compile(r"(?<![\w-])-\w*[rR]\w*\b|--recursive\b")
_RM_FORCE = re.compile(r"(?<![\w-])-\w*f\w*\b|--force\b")

_BLOCKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (
        re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b"),
        "pipe a network download into a shell",
    ),
    (re.compile(r"\bmkfs\b|\bdd\b[^\n]*\bof=/dev/"), "overwrite a filesystem/disk device"),
    (re.compile(r"\bchmod\b\s+-\w*R\w*\s+0?777\s+/(\s|$)"), "world-writable chmod on /"),
    (re.compile(r">\s*/dev/(sd[a-z]|nvme\d|disk\d)"), "write to a raw disk device"),
]
_FORCE_PUSH = re.compile(r"\bgit\s+push\b.*?(--force\b|--force-with-lease\b|\s-f\b)", re.S)
_PROTECTED = re.compile(r"\b(main|master|release)\b")


def _dangerous_rm(command: str) -> bool:
    """True for a recursive+forced ``rm`` whose target is the root or home (not a subpath)."""
    if not _RM.search(command):
        return False
    return bool(
        _RM_RECURSIVE.search(command)
        and _RM_FORCE.search(command)
        and _ROOT_TARGET.search(command)
    )


def classify_command(command: str) -> Decision:
    """Block (Decision.block) a clearly-dangerous Bash command; otherwise ALLOW.

    Conservative by design — a false block causes friction, so only unambiguous hazards match.
    """
    if _dangerous_rm(command):
        return Decision(True, "blocked: recursive/forced delete of / or home")
    for pattern, reason in _BLOCKERS:
        if pattern.search(command):
            return Decision(True, f"blocked: {reason}")
    if _FORCE_PUSH.search(command) and _PROTECTED.search(command):
        return Decision(True, "blocked: force-push to a protected branch (main/master/release)")
    return ALLOW


# --- test-gate: fast gate before commit/push ---------------------------------

_COMMIT_PUSH = re.compile(r"\bgit\s+(commit|push)\b")


def is_commit_or_push(command: str) -> bool:
    return bool(_COMMIT_PUSH.search(command))


def choose_gate(cwd: Path | str) -> list[str] | None:
    """The fast gate command to run before a commit/push, or None if no gate applies.

    Prefers the repo's own Tier-0 validator (`dev/validate.py`); otherwise the detected stack's
    lint command (by-stack). None means "nothing fast to check" (don't block).
    """
    cwd = Path(cwd)
    if (cwd / "dev" / "validate.py").is_file():
        return ["python", "dev/validate.py"]
    from agentic_forge import stacks

    lint = stacks.primary(cwd).toolchain.lint
    return lint.split() if lint else None


# --- logging: redacted audit record ------------------------------------------

_SECRETS = [
    re.compile(r"\b(sk|rk)-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
]


def redact_secrets(text: str) -> str:
    """Replace secret-looking substrings with a placeholder (for safe audit logging)."""
    for pattern in _SECRETS:
        text = pattern.sub("[REDACTED]", text)
    return text


def audit_record(payload: dict[str, Any], *, max_len: int = 300) -> dict[str, str]:
    """Build a compact, secret-redacted audit record from a PostToolUse hook payload."""
    tool = str(payload.get("tool_name") or payload.get("tool") or "unknown")
    raw = json.dumps(payload.get("tool_input") or {}, sort_keys=True)
    brief = redact_secrets(raw)
    if len(brief) > max_len:
        brief = brief[:max_len] + "…"
    record = {"tool": tool, "input": brief}
    if payload.get("session_id"):
        record["session_id"] = str(payload["session_id"])
    return record


# --- budgets: per-session subagent counter -----------------------------------


def bump_and_check(counter_path: Path | str, *, soft: int, hard: int) -> Decision:
    """Increment the counter at ``counter_path`` and decide warn/block against soft/hard caps.

    Over ``hard`` -> block; over ``soft`` -> a non-blocking warning; otherwise ALLOW. The counter
    is a tiny integer file (one per session), so the budget is enforced across hook invocations.
    """
    path = Path(counter_path)
    try:
        count = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        count = 0
    count += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(count), encoding="utf-8")
    if count > hard:
        return Decision(True, f"blocked: subagent budget exceeded ({count} > hard cap {hard})")
    if count > soft:
        return Decision(False, f"warning: {count} subagents this session (soft cap {soft})")
    return ALLOW
