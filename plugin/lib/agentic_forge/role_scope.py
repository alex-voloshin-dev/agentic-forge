"""Hold the plugin's read-only roles to their tool scope (ADR 0106).

A plugin agent's ``tools:`` list does not restrict what a ``Bash(...)`` specifier names: the
``reviewer`` with ``Bash(git diff:*)`` gets Bash, and in ``bypassPermissions`` nothing stopped it
running anything. A ``PreToolUse`` hook's deny applies in every permission mode, and the payload of
a tool call made inside a subagent carries ``agent_type``, so ``hooks/scripts/role_scope.py`` asks
:func:`respond` and refuses what the calling role may not do.

Matching is on the **namespaced** ``agent_type`` only (``agentic-forge:reviewer``): that is how
Claude Code names a plugin's agent, and a bare ``reviewer`` is somebody else's agent (a project's
or a user's own), which this hook has no business policing. A call with no ``agent_type`` (the main
session) or any other value is allowed, silently.

The allowlists, by role:

- ``reviewer`` / ``security-engineer``: Read, Grep, Glob, and Bash for one read-only git command
  (:func:`parse_git`);
- ``grader``: Read, Grep, Glob;
- ``architect``: Read, Grep, Glob, and Write for Markdown design documents under ``docs/`` in the
  session's working tree (:func:`_write_problem`).

Every other tool, an MCP tool included, is refused for these roles.

**What runs is what was checked.** An allowed git call is not passed through: :func:`respond`
returns it as ``updatedInput``, rebuilt from the checked words, each single-quoted, behind a fixed
hardening prefix (:func:`hardened_command`), so no shell expansion can turn the words the hook
read into different ones. The checks on the raw command stay as a second layer.

Turned off for the call: an external diff program (``--no-ext-diff``, ``GIT_EXTERNAL_DIFF``
cleared), textconv (``--no-textconv``), the pager, hooks, fsmonitor, nested submodule diffs
(``diff.submodule=log``), signature verification through ``log.showSignature`` or the default
format, or any gpg program (``gpg.program`` and its ssh and x509 forms set to ``/dev/null``), the
global attributes file, implicitly found bare repositories, the git environment
variables that redirect git or name a program or a trace file, and, on git 2.41 and later, every
attribute the checkout's ``.gitattributes`` sets (``--attr-source`` = the empty tree), so no clean
filter, diff driver or textconv is selected; on git 2.44 and later, lazy fetching in a partial
clone (``GIT_NO_LAZY_FETCH``). Not turned off: on git older than 2.41, a ``.gitattributes`` in the
checkout can still select a clean filter the user's config defines, which status, a worktree diff
or blame run; attributes in ``$GIT_DIR/info/attributes``; on git older than 2.44, lazy fetching
over the transport the repository's config names. Deterministic apart from asking ``git
--version`` once per call, stdlib-only and hook-reachable: Python 3.9.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .guardrails import ALLOW, Decision, redact_secrets

__all__ = [
    "Decision",
    "ALLOW",
    "PLUGIN_NAMESPACE",
    "ROLE_TOOLS",
    "GIT_ROLES",
    "READ_ONLY_GIT_SUBCOMMANDS",
    "FORBIDDEN_GIT_OPTIONS",
    "ATTR_SOURCE_SINCE",
    "EMPTY_TREE",
    "HARDENED_PREFIX",
    "HARDENING_FLAGS",
    "LEGACY_PREFIX",
    "UNSET_ENV",
    "GitCall",
    "decide",
    "deny_output",
    "git_problem",
    "git_supports_attr_source",
    "hardened_command",
    "is_held",
    "parse_git",
    "respond",
]

# Claude Code names a plugin's agent `<plugin name>:<agent name>`; the plugin name is the
# manifest's `name` (a test pins the two together).
PLUGIN_NAMESPACE = "agentic-forge"

_READ = frozenset({"Read", "Grep", "Glob"})
ROLE_TOOLS: dict[str, frozenset[str]] = {
    f"{PLUGIN_NAMESPACE}:reviewer": _READ | {"Bash"},
    f"{PLUGIN_NAMESPACE}:security-engineer": _READ | {"Bash"},
    f"{PLUGIN_NAMESPACE}:grader": _READ,
    f"{PLUGIN_NAMESPACE}:architect": _READ | {"Write"},
}
# The roles whose Bash is held to the read-only git rule.
GIT_ROLES = frozenset({f"{PLUGIN_NAMESPACE}:reviewer", f"{PLUGIN_NAMESPACE}:security-engineer"})
_ARCHITECT = f"{PLUGIN_NAMESPACE}:architect"

# In the order the refusal lists them, the most useful to a lens first.
_SUBCOMMAND_ORDER = (
    "diff", "show", "log", "status", "blame", "ls-files", "ls-tree", "rev-parse", "merge-base",
    "cat-file", "grep", "shortlog", "describe",
)
READ_ONLY_GIT_SUBCOMMANDS = frozenset(_SUBCOMMAND_ORDER)

# Options that write a file (--output), run a program git is configured with (--ext-diff,
# --textconv, --filters, --open-files-in-pager / grep's -O, --paginate, --help, --show-signature,
# which runs gpg, and --submodule, whose `diff` form runs nested diffs that do not inherit
# --no-ext-diff), change git's configuration or programs for the call (-c, --config-env,
# --exec-path, --upload-pack), or take git outside the repository (--no-index: a lens reviews the
# repository, not arbitrary files). `-o` is refused with them. A token is refused when it IS one of
# these or STARTS with one (`--output=f`, `-cname=v`), and a long one also when it is an
# abbreviation of one, since git accepts a unique prefix of a long option. The prefix rule is
# deliberately coarse: it also refuses harmless options that share a prefix, such as
# `--output-indicator-new`.
FORBIDDEN_GIT_OPTIONS: tuple[str, ...] = (
    "--output", "-o", "--ext-diff", "--textconv", "--filters", "-c", "--config-env",
    "--exec-path", "--upload-pack", "--paginate", "--open-files-in-pager", "--help",
    "--no-index", "--submodule", "--show-signature",
)
# `--text` is a prefix of `--textconv` but its own option ("treat all files as text") in the
# subcommands whose man pages list `-a, --text`: diff, show, log and grep. Anywhere else (blame,
# cat-file, shortlog) git would read it as an abbreviation of `--textconv`, so it is refused there.
_TEXT_IS_TEXT = frozenset({"diff", "show", "log", "grep"})
# `cat-file` may only print an object (-p), its type (-t) or size (-s), or test that it exists
# (-e). Its other options run textconv or filters (--textconv, --filters, and `--text`, an
# abbreviation of the first) or read object names from stdin, which a lens cannot supply.
_CAT_FILE_OPTIONS = frozenset({"-p", "-t", "-s", "-e"})
# The built-in pretty formats; any other `--pretty=`/`--format=` name is a `pretty.<name>` alias
# from config, which could hold a signature placeholder.
_BUILTIN_FORMATS = frozenset({
    "oneline", "short", "medium", "full", "fuller", "reference", "email", "mboxrd", "raw",
})
# A signature placeholder: `%`, an optional `+`, `-` or space modifier, then `G` (`%G?`, `%+GS`).
# The second layer: gpg.program is /dev/null in the hardened form anyway.
_SIGNATURE_PLACEHOLDER = re.compile(r"%[-+ ]?G")
_GLOBAL_OPTIONS_HELP = "one -C <path> and --no-pager"

# --- the hardened form an allowed command runs in -------------------------------------------
# Variables (from `git help git`, ENVIRONMENT VARIABLES) that point git at another repository,
# index, object store, attribute source or config, name a program it runs (a diff, pager or editor
# program, an ssh or askpass helper), or name a file it writes (the trace targets). `env -u` clears
# them for the call, whatever set them: the shell a Bash call runs in also reads the user's rc files
# and `CLAUDE_ENV_FILE`, which the hook's own environment never sees, so checking the hook's
# environment instead would miss some. `GIT_CONFIG_KEY_<n>` needs `GIT_CONFIG_COUNT`, which goes.
UNSET_ENV = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_ATTR_SOURCE", "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
    "GIT_EXEC_PATH", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "PAGER", "GIT_EDITOR",
    "GIT_SEQUENCE_EDITOR", "EDITOR", "VISUAL", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS",
    "SSH_ASKPASS", "GIT_PROXY_COMMAND", "GIT_TRACE", "GIT_TRACE2", "GIT_TRACE2_EVENT",
    "GIT_TRACE2_PERF", "GIT_TRACE_FSMONITOR", "GIT_TRACE_PACK_ACCESS", "GIT_TRACE_PACKET",
    "GIT_TRACE_PACKFILE", "GIT_TRACE_PERFORMANCE", "GIT_TRACE_REFS", "GIT_TRACE_SETUP",
    "GIT_TRACE_SHALLOW", "GIT_TRACE_CURL", "GIT_REDIRECT_STDIN", "GIT_REDIRECT_STDOUT",
    "GIT_REDIRECT_STDERR",
)
# Set for the call: git 2.44 and later fetch no missing object in a partial clone (older git
# ignores the variable).
_SET_ENV = ("GIT_NO_LAZY_FETCH=1",)
# Command-line config outranks every config file, and git passes it on to the git processes it
# starts (in submodules too): no implicitly discovered bare repository, no fsmonitor program, no
# hooks, submodule changes as a log and never as a nested diff (which would not inherit
# --no-ext-diff), no signature verification through `log.showSignature` or a default format
# holding a signature placeholder, no signature program at all (`/dev/null` cannot run, so a
# placeholder that slips past the check below runs nothing), and no global attributes file.
_HARDENING_CONFIG = (
    "safe.bareRepository=explicit", "core.fsmonitor=false", "core.hooksPath=/dev/null",
    "diff.submodule=log", "log.showSignature=false", "format.pretty=medium",
    "core.attributesFile=/dev/null", "gpg.program=/dev/null", "gpg.ssh.program=/dev/null",
    "gpg.x509.program=/dev/null",
)
# The empty tree's id, which every SHA-1 repository has without storing it. Reading attributes from
# it (`--attr-source`, git 2.41 and later) means no `.gitattributes` in the checkout selects a
# clean filter, a diff driver or textconv for this call. A SHA-256 repository does not know this id,
# so git refuses to start there: it fails closed.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_ATTR_SOURCE = "--attr-source=" + EMPTY_TREE
ATTR_SOURCE_SINCE = (2, 41)


def _prefix(attr_source: bool) -> tuple[str, ...]:
    # `/usr/bin/env` by path: no alias or shell function named `env` or `git` stands in for them.
    return tuple(
        ["/usr/bin/env"]
        + [w for name in UNSET_ENV for w in ("-u", name)]
        + list(_SET_ENV)
        + ["git"]
        + [w for item in _HARDENING_CONFIG for w in ("-c", item)]
        + ["--no-pager"]
        + ([_ATTR_SOURCE] if attr_source else [])
    )


# The prefix on git 2.41 and later, and on a git older than that.
HARDENED_PREFIX: tuple[str, ...] = _prefix(True)
LEGACY_PREFIX: tuple[str, ...] = _prefix(False)
# Per subcommand, the flags that turn off a configured external diff program and textconv
# filters, confirmed against git 2.43: `--no-ext-diff` and `--no-textconv` in the man pages of
# diff, show and log, `--[no-]textconv` in `git blame -h`, `--no-textconv` in git-grep(1). The
# other subcommands produce no diff and run neither program; most reject the flags (status,
# cat-file, describe and ls-files exit 129).
HARDENING_FLAGS: dict[str, tuple[str, ...]] = {
    "diff": ("--no-ext-diff", "--no-textconv"),
    "show": ("--no-ext-diff", "--no-textconv"),
    "log": ("--no-ext-diff", "--no-textconv"),
    "blame": ("--no-textconv",),
    "grep": ("--no-textconv",),
}

# Refused anywhere in the command, quoted or not: shell operators, redirections, every `$` form,
# the backslash (whose meaning differs between quoting contexts) and line breaks. Other control
# characters and lone surrogates are refused as well (see _unsafe_character).
_FORBIDDEN_ANYWHERE = frozenset(";&|<>`$\\\n\r\x00")
# Outside quotes, a word may hold only these: no glob, brace, history, comment, grouping or zsh
# extended-glob character (`^`, `#`), which a shell could expand into something else.
_SAFE_UNQUOTED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:@,=+%~-"
)
_EVIDENCE_LEN = 60

# --- what the architect may write --------------------------------------------------------------
# Instruction files an agent reads as its own orders, which a design document must not be.
# A skill definition (`SKILL.md`) is one too, wherever it is.
_AGENT_FILES = frozenset({"claude.md", "claude.local.md", "agents.md", "gemini.md", "skill.md"})
# The role's contract directory, below a working tree's top.
_DOCS_DIR = "docs"
# The second layer: writing these leads to code running later (git hooks and config) or to the
# agents' own settings.
_PROTECTED_PAIRS = ((".agentic-forge", "config.json"),)


class _Refusal(Exception):
    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason


@dataclass(frozen=True)
class GitCall:
    """A checked read-only git call: an optional ``-C`` directory (absolute, resolved), the
    subcommand and its arguments, in the order git will see them."""

    c_path: str | None
    subcommand: str
    args: tuple[str, ...]


def _excerpt(text: str) -> str:
    """A short, redacted piece of the command for a message or a record."""
    clean = redact_secrets(text)
    return clean if len(clean) <= _EVIDENCE_LEN else clean[: _EVIDENCE_LEN - 1] + "…"


def _unsafe_character(command: str) -> str | None:
    """A description of the first character a shell could act on, or None when there is none.
    With no backslash allowed, quoting is plain: `'…'` and `"…"` are literal to the end quote."""
    quote: str | None = None
    word_empty = True  # nothing but quote marks so far in this word: `""=cmd` is `=cmd` to zsh
    for ch in command:
        if ch in _FORBIDDEN_ANYWHERE:
            return f"the shell character {ch!r}"
        if (ch < " " and ch != "\t") or ch == "\x7f":
            return "a control character"
        if "\ud800" <= ch <= "\udfff":
            return "a lone surrogate"
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                word_empty = False
        elif ch in "'\"":
            quote = ch
        elif ch in " \t":
            word_empty = True
        elif ch not in _SAFE_UNQUOTED:
            return f"the unquoted character {ch!r}"
        elif ch == "=" and word_empty:
            return "an unquoted '=' at the start of a word"  # zsh's `=cmd` names a path
        else:
            word_empty = False
    if quote is not None:
        return "an unclosed quote"
    return None


def _forbidden_option(token: str, subcommand: str) -> str | None:
    """The forbidden option ``token`` is or abbreviates, or None."""
    name = token.split("=", 1)[0]
    for option in FORBIDDEN_GIT_OPTIONS:
        if token.startswith(option):
            return option
        if option.startswith("--") and len(name) > 2 and option.startswith(name):
            if name == "--text" and subcommand in _TEXT_IS_TEXT:
                continue
            return option
    short_bundle = token.startswith("-") and not token.startswith("--")
    if subcommand == "grep" and short_bundle and "O" in token:
        return "-O"  # grep's -O runs a pager program, in a bundle (`-nO`) too
    if _SIGNATURE_PLACEHOLDER.search(token):
        return "%G"  # a signature placeholder, with or without a modifier: formatting it runs gpg
    if name in ("--pretty", "--format") and "=" in token:
        value = token.split("=", 1)[1]
        named = "%" not in value and not value.startswith(("format:", "tformat:"))
        if named and value not in _BUILTIN_FORMATS:
            return f"{name}=<a format alias from config>"
    return None


def _git_dir_of(work_tree: str) -> str | None:
    """The real path of the git directory ``work_tree/.git`` names, or None when there is none.
    A ``.git`` file (a linked worktree, a submodule) names its directory as ``gitdir: <path>``."""
    dot_git = os.path.join(work_tree, ".git")
    if os.path.isdir(dot_git):
        return os.path.realpath(dot_git)
    if not os.path.isfile(dot_git):
        return None
    try:
        with open(dot_git, encoding="utf-8") as handle:
            first = handle.readline(4096).strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not first.startswith("gitdir:"):
        return None
    target = first[len("gitdir:"):].strip()
    return os.path.realpath(os.path.join(work_tree, target)) if target else None


def _common_dir(git_dir: str) -> str:
    """The main repository's git directory for ``git_dir``, from git's own metadata: a linked
    worktree's git directory holds a ``commondir`` file naming the shared one (relative to itself).
    Without that file ``git_dir`` is its own common directory. A directory NAME is never evidence:
    an ordinary checkout that happens to live in a folder called ``worktrees`` or ``modules`` is
    its own repository, not part of its neighbour's (a review found the name test let `-C` reach
    an unrelated sibling). A submodule needs nothing here: its git directory lives inside the
    superproject's, which the membership check in :func:`_resolve_c_path` already reads."""
    try:
        with open(os.path.join(git_dir, "commondir"), encoding="utf-8") as handle:
            target = handle.readline(4096).strip()
    except (OSError, UnicodeDecodeError):
        return git_dir
    return os.path.realpath(os.path.join(git_dir, target)) if target else git_dir


def _enclosing_work_tree(path: str) -> tuple[str, str] | None:
    """The nearest directory at or above ``path`` (already resolved) that holds a ``.git`` entry,
    and the git directory it names, or None outside any repository."""
    current = path
    while True:
        git_dir = _git_dir_of(current)
        if git_dir is not None:
            return current, git_dir
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _session_common_dir(cwd: str) -> str | None:
    """The main git directory of the repository ``cwd`` is in, or None outside one."""
    found = _enclosing_work_tree(os.path.realpath(cwd))
    return _common_dir(found[1]) if found else None


def _resolve_c_path(path: str, cwd: str) -> str | None:
    """The directory ``git -C path`` enters from ``cwd``, resolved as the kernel resolves a
    ``chdir`` (symlinks first, then ``..``), when it is the top of a working tree of the repository
    ``cwd`` is in: its main checkout, a linked worktree, or a submodule of it. None otherwise."""
    try:
        session = _session_common_dir(cwd)
        if session is None:
            return None
        target = os.path.realpath(os.path.join(cwd, path))
        git_dir = _git_dir_of(target)
    except (OSError, ValueError):  # UnicodeEncodeError is a ValueError: a path git cannot enter
        return None
    if git_dir is None:
        return None
    if git_dir == session or git_dir.startswith(session + os.sep):
        return target
    return None


def _strip_hardening(tokens: list[str]) -> list[str]:
    """``tokens`` with this module's own hardening removed, so a command it produced is checked as
    the plain command it came from (a model can send a rewritten call back through the hook)."""
    for prefix in (list(HARDENED_PREFIX), list(LEGACY_PREFIX)):
        if tokens[: len(prefix)] == prefix:
            break
    else:
        return tokens
    rest = ["git"] + tokens[len(prefix):]
    # `git [-C <path>] <sub> <flags>`: drop the flags when they follow the subcommand exactly
    at = 3 if len(rest) > 2 and rest[1] == "-C" else 1
    if at < len(rest):
        flags = list(HARDENING_FLAGS.get(rest[at], ()))
        if flags and rest[at + 1 : at + 1 + len(flags)] == flags:
            rest = rest[: at + 1] + rest[at + 1 + len(flags):]
    return rest


def parse_git(command: str, cwd: str = ".") -> GitCall:
    """``command`` as one read-only git call, or :class:`_Refusal` saying why it is not one.

    ``cwd`` is where the command runs; a ``-C`` path is resolved against it as git resolves it and
    must be the top of a working tree of the same repository."""
    if not command.strip():
        raise _Refusal("role-bash-empty", "the command is empty")
    unsafe = _unsafe_character(command)
    if unsafe:
        raise _Refusal("role-bash-shell", f"it contains {unsafe}; run one plain git command")
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        raise _Refusal("role-bash-shell", "it does not parse as one plain command") from None
    tokens = _strip_hardening(tokens)
    if not tokens or tokens[0] != "git":
        first = _excerpt(tokens[0]) if tokens else ""
        raise _Refusal("role-bash-not-git", f"'{first}' is not git")
    i = 1
    c_path: str | None = None
    while i < len(tokens) and tokens[i].startswith("-"):
        token = tokens[i]
        if token == "--no-pager":
            i += 1
        elif token == "-C" and i + 1 < len(tokens) and c_path is None:
            c_path = tokens[i + 1]
            i += 2
        else:
            raise _Refusal(
                "role-bash-global-option",
                f"the global option '{_excerpt(token)}' is not allowed "
                f"(only {_GLOBAL_OPTIONS_HELP})",
            )
    if i >= len(tokens):
        raise _Refusal("role-bash-subcommand", "it has no git subcommand")
    subcommand = tokens[i]
    if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
        raise _Refusal(
            "role-bash-subcommand", f"'git {_excerpt(subcommand)}' is not a read-only subcommand"
        )
    for token in tokens[1:]:
        option = _forbidden_option(token, subcommand)
        if option:
            raise _Refusal(
                "role-bash-option",
                f"the option '{_excerpt(option)}' writes a file, runs a configured program, "
                "changes git's configuration or leaves the repository",
            )
    args = tuple(tokens[i + 1:])
    if subcommand == "cat-file":
        for token in args:
            if token.startswith("-") and token not in _CAT_FILE_OPTIONS:
                raise _Refusal(
                    "role-bash-option",
                    f"git cat-file takes only -p, -t, -s or -e here, not '{_excerpt(token)}'",
                )
    resolved: str | None = None
    if c_path is not None:
        resolved = None if "~" in c_path else _resolve_c_path(c_path, cwd)
        if resolved is None:
            hint = " (give its path without '~')" if "~" in c_path else ""
            raise _Refusal(
                "role-bash-c-path",
                f"-C '{_excerpt(c_path)}' is not a working tree of this session's repository"
                + hint,
            )
    return GitCall(resolved, subcommand, args)


def git_problem(command: str, cwd: str = ".") -> tuple[str, str] | None:
    """Why ``command`` is not one read-only git command, as ``(rule, reason)``; None when it is."""
    try:
        parse_git(command, cwd)
    except _Refusal as refusal:
        return refusal.rule, refusal.reason
    return None


def _quote(word: str) -> str:
    """``word`` single-quoted, always: inside single quotes bash and zsh expand nothing, whatever
    their options (zsh's MAGIC_EQUAL_SUBST rewrites a bare ``--x==cmd``, for one). A ``'`` in the
    word closes the quote, is given in double quotes, and reopens it."""
    return "'" + word.replace("'", "'\"'\"'") + "'"


@lru_cache(maxsize=1)
def _git_version() -> tuple[int, int] | None:
    """The (major, minor) version of the ``git`` on the hook's PATH, asked once per process (one
    hook call), or None when it cannot be told. Only an absolute path to git is run: a relative
    PATH entry could find a `git` in the reviewed checkout."""
    git = shutil.which("git")
    if not git or not os.path.isabs(git):
        return None
    try:
        done = subprocess.run(
            [git, "--version"], capture_output=True, text=True, timeout=3,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    match = re.match(r"git version (\d+)\.(\d+)", done.stdout)
    return (int(match.group(1)), int(match.group(2))) if match else None


def git_supports_attr_source() -> bool:
    """True unless the ``git`` on PATH is known to be older than 2.41, which lacks
    ``--attr-source``. An unknown version gets it: a git that rejects it fails to start, which
    refuses the call rather than running it without the option."""
    version = _git_version()
    return version is None or version >= ATTR_SOURCE_SINCE


def hardened_command(call: GitCall, attr_source: bool = True) -> str:
    """The command line that runs ``call``: the hardening prefix (``--attr-source`` only when
    ``attr_source``), the resolved ``-C``, the subcommand, its hardening flags, then the checked
    arguments, every word single-quoted."""
    words = list(HARDENED_PREFIX if attr_source else LEGACY_PREFIX)
    if call.c_path is not None:
        words += ["-C", call.c_path]
    words.append(call.subcommand)
    words += HARDENING_FLAGS.get(call.subcommand, ())
    words += call.args
    return " ".join(_quote(word) for word in words)


def _write_problem(file_path: Any, cwd: str = ".") -> str | None:
    """Why the architect may not write ``file_path``, or None.

    An allowlist that fits the role's contract, design documents: the resolved path (a relative one
    against ``cwd``, links followed) must lie under ``docs/`` of a working tree of the session's
    repository (its checkout or a linked worktree, not a submodule or another repository), end in
    ``.md``, have no segment below that tree's top starting with ``.``, and not be an agent
    instruction or skill file (``CLAUDE.md``, ``CLAUDE.local.md``, ``AGENTS.md``, ``GEMINI.md``,
    ``SKILL.md``). The earlier blocklist (``.git``, Claude Code settings, the plugin config) stays
    as a second layer, on the path as given and as resolved."""
    if not isinstance(file_path, str) or not file_path:
        return "the Write call names no file"
    try:
        resolved = os.path.realpath(os.path.join(cwd, file_path))
        session = _session_common_dir(cwd)
        found = _enclosing_work_tree(os.path.dirname(resolved))
    except (OSError, ValueError):  # UnicodeEncodeError is a ValueError
        return "a path that cannot be resolved"
    blocked = _blocked_write(file_path, resolved)
    if blocked:
        return blocked
    if session is None or found is None:
        return "a path outside this session's repository"
    top, git_dir = found
    own_tree = git_dir == session or os.path.dirname(git_dir) == os.path.join(session, "worktrees")
    if not own_tree:
        return "a path outside this session's working trees"
    parts = os.path.relpath(resolved, top).split(os.sep)
    if ".." in file_path.replace("\\", "/").split("/") and parts[0].startswith("."):
        # `..` led out of one working tree into the hidden space around another (where linked
        # worktrees, `.git` and tool state live), not into a document of either
        return "a path outside this session's working trees"
    if len(parts) < 2 or parts[0] != _DOCS_DIR:
        return "a path outside the docs/ directory of this session's working trees"
    if any(part.startswith(".") for part in parts):
        return "a hidden file or directory"
    names = {parts[-1].casefold(), os.path.basename(file_path).casefold()}
    if names & _AGENT_FILES:
        return "an agent instruction or skill file"
    if not parts[-1].casefold().endswith(".md"):
        return "a file that is not a Markdown document (.md)"
    return None


def _blocked_write(file_path: str, resolved: str) -> str | None:
    """The blocklist, kept as a second layer under the allowlist."""
    for path in (file_path, resolved):
        parts = [p.casefold() for p in path.replace("\\", "/").split("/") if p]
        if ".git" in parts:
            return "a path inside a .git directory"
        last_two = tuple(parts[-2:])
        if len(last_two) == 2 and last_two[0] == ".claude" and last_two[1].startswith(
            "settings"
        ) and last_two[1].endswith(".json"):
            return "Claude Code settings"
        if last_two in _PROTECTED_PAIRS:
            return "the agentic-forge config"
    return None


def _role_label(agent_type: str) -> str:
    return agent_type.split(":", 1)[1]


def _scope_text(agent_type: str) -> str:
    tools = sorted(ROLE_TOOLS[agent_type] - {"Bash"})
    text = ", ".join(tools)
    if agent_type in GIT_ROLES:
        subs = ", ".join(_SUBCOMMAND_ORDER)
        text += (
            f", and Bash for one read-only git command (git {subs}; global options only "
            f"{_GLOBAL_OPTIONS_HELP}; no shell operators, redirections, substitutions, "
            "backslashes or globs)"
        )
    if agent_type == _ARCHITECT:
        text += (
            " (Write only Markdown design documents (.md) under docs/ in this repository's working "
            "tree, outside hidden directories, and not CLAUDE.md, AGENTS.md, GEMINI.md or SKILL.md)"
        )
    return text


_ORCHESTRATOR = "Tests, linters and other tools are run by the orchestrating skill, not by"
_LENS_ADVICE = (
    f"{_ORCHESTRATOR} a review lens: verify by reading (git show <base>:<path>, git log, "
    "git blame) and report what still needs running."
)


def _deny(agent_type: str, refused: str, rule: str, evidence: str) -> Decision:
    role = _role_label(agent_type)
    advice = (
        _LENS_ADVICE if agent_type in GIT_ROLES
        else f"{_ORCHESTRATOR} the {role} role: report what needs running."
    )
    message = (
        f"agentic-forge role scope: the {role} role may use {_scope_text(agent_type)}. "
        f"Refused: {refused}. {advice}"
    )
    return Decision(True, message, rule, evidence)


def is_held(payload: dict[str, Any]) -> bool:
    """True when the call comes from one of the roles this module holds."""
    agent_type = payload.get("agent_type")
    return isinstance(agent_type, str) and agent_type in ROLE_TOOLS


def _evaluate(payload: dict[str, Any]) -> tuple[Decision, GitCall | None]:
    """The decision, and for an allowed git call the checked call to run in its hardened form."""
    if not is_held(payload):
        return ALLOW, None
    agent_type = str(payload["agent_type"])
    tool = str(payload.get("tool_name") or "")
    if tool not in ROLE_TOOLS[agent_type]:
        shown = _excerpt(tool) or "(no tool name)"
        refused = f"the tool {shown} is outside this role's scope"
        return _deny(agent_type, refused, "role-tool", shown), None
    tool_input = payload.get("tool_input")
    cwd = payload.get("cwd")
    cwd = cwd if isinstance(cwd, str) and cwd else "."
    if tool == "Write":
        file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        problem = _write_problem(file_path, cwd)
        if problem:
            refused = f"this Write, because it targets {problem}"
            return _deny(agent_type, refused, "role-write-path", _excerpt(str(file_path))), None
        return ALLOW, None
    if tool != "Bash":
        return ALLOW, None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    command = command if isinstance(command, str) else ""
    try:
        call = parse_git(command, cwd)
    except _Refusal as refusal:
        refused = f"this Bash command, because {refusal.reason}"
        return _deny(agent_type, refused, refusal.rule, _excerpt(command)), None
    return ALLOW, call


def decide(payload: dict[str, Any]) -> Decision:
    """Allow or refuse one ``PreToolUse`` call. Allows, with no message, every call whose
    ``agent_type`` is not one of :data:`ROLE_TOOLS` (the main session's carries none)."""
    return _evaluate(payload)[0]


def deny_output(reason: str) -> dict[str, Any]:
    """The PreToolUse JSON that refuses the call and tells the model why."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def respond(
    payload: dict[str, Any], attr_source: bool | None = None
) -> tuple[Decision, dict[str, Any] | None]:
    """The decision and the hook's JSON for one call: a deny, an allow that replaces the command
    with its hardened form (``updatedInput`` replaces the whole input, so the other fields are
    carried over, except a request to leave the sandbox), or None to say nothing.

    ``attr_source`` says whether the hardened form reads attributes from the empty tree; None asks
    the ``git`` on PATH (:func:`git_supports_attr_source`), only when there is a git call to run."""
    decision, call = _evaluate(payload)
    if decision.block:
        return decision, deny_output(decision.message)
    if call is None:
        return decision, None
    if attr_source is None:
        attr_source = git_supports_attr_source()
    tool_input = payload.get("tool_input")
    updated = dict(tool_input) if isinstance(tool_input, dict) else {}
    updated.pop("dangerouslyDisableSandbox", None)
    updated["command"] = hardened_command(call, attr_source)
    return decision, {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "agentic-forge role scope: read-only git, run hardened",
            "updatedInput": updated,
        }
    }
