"""Narrow the commit gate to what a simple command changes (ADR 0101).

The gate is always what ``guardrails.choose_gate`` picked for the directory the commit acts on
(``guardrails.commit_dir``, ADR 0111). :func:`narrow` can only leave it as it is, skip it, or hand
`ruff check` the changed files. A `cd` or a `git -C` is never a simple command, so it is never
narrowed against a directory other than that one. A command it does not fully
understand, or any git failure, leaves the gate as it is: uncertainty is neither an allow nor a new
block. Hook-reachable, so Python 3.9.
"""

from __future__ import annotations

import os
import re
import shlex
import time
from dataclasses import dataclass
from subprocess import DEVNULL, PIPE, SubprocessError, run

__all__ = ["NARROWABLE", "Simple", "parse_simple", "narrow", "printable"]

_RUFF_GATE = ["ruff", "check", "."]
GO_GATE = ["go", "vet", "./..."]
_GO_GATE = GO_GATE  # the name this module uses internally
NARROWABLE = (_RUFF_GATE, _GO_GATE)
_RUFF_EXTENSIONS = (".py", ".pyi", ".pyw", ".ipynb")
_RUFF_CONFIGS = (".ruff.toml", "ruff.toml", "pyproject.toml")
# Keys by which a config chooses its own inputs, or takes them from another file: the extension
# list above does not hold there. Words, not TOML: `[tool.poetry] include` over-triggers, correctly.
_INPUT_KEYS = re.compile(
    r"""\b(?:extend-)?include\b|\bextension\b|^\s*["']?extend["']?\s*=""", re.MULTILINE
)
_RUFF_WORD = re.compile(r"\bruff\b")
_READ_BUDGET = 5.0  # seconds for ALL the git reads: with the gate's 110 it fits the hook's 120
_MAX_ARGV = 100_000  # characters of filenames; past this the OS may refuse the argv: run it whole

# One word: safe characters, or a quoted part whose content the shell cannot act on. No glob, tilde,
# brace or variable, and in double quotes no `$`, backtick or backslash either.
_WORD = r"""(?:[\w./@%+=:,-]|'[^'\n]*'|"[^"$`\\\n]*")+"""
_SHAPE = re.compile(rf"[ \t]*(?:{_WORD}|&&)(?:[ \t]+(?:{_WORD}|&&))*[ \t]*")
# A message from a heredoc, as the very end of the command, with nothing quoted before it, the
# delimiter quoted so the body is not expanded, and the FIRST line equal to it closing the body.
# Any line starting with the delimiter closes it: bash also closes on a line like `EOF)`.
_HEREDOC = r"""<<'(\w+)'\n(?:(?!\2)[^\n]*\n)*\2"""
_HEREDOC_MESSAGES = (
    (re.compile(rf"""([^'"\n]*[ \t]-a?m )"\$\(cat {_HEREDOC}\n\)"[ \t]*"""), "message"),
    (re.compile(rf"""([^'"\n]*[ \t])-F - {_HEREDOC}\n?"""), "-m message"),
)
_PATHSPEC_MAGIC = re.compile(r"""^:|[*?\[\\]""")
_REF = re.compile(r"(?!.*\.\.)\w[\w./-]*")
_COMMIT_FLAGS = {"--allow-empty", "--no-verify", "-n", "-q", "--quiet", "-s", "--signoff"}
_PUSH_FLAGS = {"-u", "--set-upstream"}


@dataclass(frozen=True)
class Simple:
    """`git commit`: ``add`` is what a `git add` before it names, ``tracked`` is ``-a``. `git push`:
    ``remote`` and ``branch``, each "" when not named."""

    verb: str
    add: tuple[str, ...] = ()
    tracked: bool = False
    remote: str = ""
    branch: str = ""


def _add_pathspecs(words: list[str]) -> tuple[str, ...]:
    if words[:2] != ["git", "add"]:
        return ()
    args = words[2:]
    if args in (["-A"], ["--all"]):
        return (":/",)
    paths = args[1:] if args[:1] == ["--"] else args
    if paths is args and any(path.startswith("-") for path in paths):
        return ()
    return () if not all(paths) or any(_PATHSPEC_MAGIC.search(p) for p in paths) else tuple(paths)


def parse_simple(command: str) -> Simple | None:
    """The command as a :class:`Simple`, or None for any other shape."""
    for pattern, stand_in in _HEREDOC_MESSAGES:
        heredoc = pattern.fullmatch(command)
        command = heredoc.group(1) + stand_in if heredoc else command
    if not _SHAPE.fullmatch(command):
        return None
    words = shlex.split(command)
    if any(word.startswith("=") for word in words):  # zsh expands it, even as `''=x`
        return None
    add: tuple[str, ...] = ()
    if "&&" in words:
        cut = words.index("&&")
        add, words = _add_pathspecs(words[:cut]), words[cut + 1 :]
        if not add:
            return None
    if words[:2] == ["git", "push"] and not add:
        names = [word for word in words[2:] if word not in _PUSH_FLAGS]
        if len(names) > 2 or not all(_REF.fullmatch(name) for name in names):
            return None
        return Simple("push", remote="".join(names[:1]), branch="".join(names[1:]))
    if words[:2] != ["git", "commit"]:
        return None
    tracked = False
    rest = iter(words[2:])
    for word in rest:
        if word in ("-m", "--message", "-am", "-qm"):
            tracked = tracked or word == "-am"
            if next(rest, None) is None:
                return None
        elif word in ("-a", "--all"):
            tracked = True
        elif word not in _COMMIT_FLAGS:
            return None
    return Simple("commit", add=add, tracked=tracked)


_GIT = "git --no-replace-objects -c core.fsmonitor=false -c safe.bareRepository=explicit".split()
_GIT += "-c diff.relative=false -c diff.autoRefreshIndex=false -c log.showSignature=false".split()
_GIT += ["-c", "log.showRoot=true"]
_DIFF = ("--raw", "-z", "--no-renames", "--no-ext-diff", "--ignore-submodules=dirty")
# These steer git somewhere other than cwd, or steer the push. The command inherits them, so a read
# without them would describe something else: with one set, the gate is left as it is.
_GIT_STEERING = "GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY".split()
_GIT_STEERING += ["GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"]
# All the reads need. No token reaches a clean filter a repo's own config names.
_READ_ENV = "PATH HOME XDG_CONFIG_HOME TMPDIR LANG LC_ALL LC_CTYPE SYSTEMROOT".split() + (
    "GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_CONFIG_NOSYSTEM GIT_CEILING_DIRECTORIES".split()
)
_HEAD_ONLY_DEFAULTS = {b"push.default simple", b"push.default current"}


class _GitFailed(Exception):
    """A read did not answer: the gate is left as it is."""


def _git(cwd: str, deadline: float, *args: str, ok: tuple[int, ...] = (0,)) -> bytes:
    env = {name: os.environ[name] for name in _READ_ENV if name in os.environ}
    left = deadline - time.monotonic()
    if left <= 0:
        raise _GitFailed
    try:
        done = run(
            [*_GIT, *args], cwd=cwd, env={**env, "GIT_NO_LAZY_FETCH": "1"}, stdin=DEVNULL,
            stdout=PIPE, stderr=DEVNULL, timeout=left,
        )  # fmt: skip
    except (OSError, ValueError, SubprocessError) as exc:
        raise _GitFailed from exc
    if done.returncode not in ok:
        raise _GitFailed
    return done.stdout


def _text(cwd: str, deadline: float, *args: str) -> str:
    return _git(cwd, deadline, *args).decode("utf-8", "replace").strip()


def _names(cwd: str, deadline: float, *args: str) -> list[str]:
    return [os.fsdecode(name) for name in _git(cwd, deadline, *args).split(b"\0") if name]


def _pushed(simple: Simple, cwd: str, deadline: float) -> list[str]:
    """Files in the commits the push sends that its remote lacks, only when the push can only send
    this branch to the same name there. `log -c` lists a merge's own changes; plain `log` has none.
    """
    current = _text(cwd, deadline, "symbolic-ref", "-q", "HEAD")[len("refs/heads/") :]
    if simple.branch not in ("", "HEAD", current):
        raise _GitFailed
    remotes = _text(cwd, deadline, "remote").split()
    remote = simple.remote
    if not remote:  # git's own answer, and a failure when there is nowhere to push to
        target = _text(cwd, deadline, "rev-parse", "--symbolic-full-name", "@{push}")
        remote = next((name for name in remotes if target == f"refs/remotes/{name}/{current}"), "")
    if remote not in remotes or not _REF.fullmatch(remote):
        raise _GitFailed
    escaped = remote.replace(".", "\\.")
    pattern = rf"^(push\.default|remote\.{escaped}\.(push|mirror))$"
    config = _git(cwd, deadline, "config", "--get-regexp", pattern, ok=(0, 1))
    if set(config.splitlines()) - _HEAD_ONLY_DEFAULTS:
        raise _GitFailed
    # What that ref lacks is what lands there, even if some other branch of the remote holds it.
    tracking = f"refs/remotes/{remote}/{current}"
    known = _git(cwd, deadline, "rev-parse", "-q", "--verify", tracking, ok=(0, 1))
    if known and _text(cwd, deadline, "rev-parse", "--symbolic-full-name", "@{push}") != tracking:
        raise _GitFailed
    against = tracking if known else f"--remotes={remote}"
    log = ("log", "-c", "--no-renames", "--name-only", "--format=", "-z", "HEAD", "--not")
    return _names(cwd, deadline, *log, against)


def _diff(cwd: str, deadline: float, *args: str) -> list[str]:
    """What `git diff` lists. A gitlink gets the trailing slash `ls-files -o` gives a nested repo.
    """
    fields = _git(cwd, deadline, "diff", *_DIFF, *args).split(b"\0")  # `:mode mode ...`, then path
    return [
        os.fsdecode(path) + ("/" if b"160000" in meta[:14] else "")
        for meta, path in zip(fields[::2], fields[1::2])  # noqa: B905 (no `strict=` on 3.9)
    ]


def _committed(simple: Simple, cwd: str, deadline: float) -> list[str]:
    """Staged files, plus the tracked changes `-a` takes, plus what `git add` is about to stage."""
    names = _diff(cwd, deadline, "--cached")
    if simple.tracked:
        names += _diff(cwd, deadline)
    if simple.add:
        names += _diff(cwd, deadline, "--", *simple.add)
        others = ("ls-files", "--full-name", "-z", "-o", "--exclude-standard", "--", *simple.add)
        names += _names(cwd, deadline, *others)
    return names


def _lintable_link(cwd: str, deadline: float) -> bool:
    """Is a lintable name under ``cwd`` a symlink? ruff follows one, so whatever changes its target
    can change what the whole gate says, wherever the target is."""
    for entry in _git(cwd, deadline, "ls-files", "-s", "-z", "--", ".").split(b"\0"):
        if entry.startswith(b"120000 ") and os.fsdecode(entry).endswith(_RUFF_EXTENSIONS):
            return True
    return False


def _custom_inputs(cwd: str, under: set[str]) -> bool:
    """Might a config ruff reads choose its own inputs? Any user-level config, or one mentioning
    such a key in ``cwd``, above it, or on the way to a changed file. Unreadable reads as yes."""
    users = [os.path.expanduser("~/.config"), *filter(None, [os.environ.get("XDG_CONFIG_HOME")])]
    if any(os.path.exists(os.path.join(u, "ruff", name)) for u in users for name in _RUFF_CONFIGS):
        return True
    root = os.path.realpath(cwd)
    places = {root}
    for name in under:
        while os.path.dirname(name):
            name = os.path.dirname(name)
            places.add(os.path.join(root, name))
    while root != os.path.dirname(root):
        root = os.path.dirname(root)
        places.add(root)
    try:
        for place in places:
            for config in _RUFF_CONFIGS:
                path = os.path.join(place, config)
                if os.path.isfile(path):
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        text = handle.read()
                    if _INPUT_KEYS.search(text) and (
                        config != "pyproject.toml" or _RUFF_WORD.search(text)
                    ):
                        return True
    except OSError:
        return True
    return False


def _narrowed(gate: list[str], simple: Simple, cwd: str, deadline: float) -> list[str] | None:
    prefix = os.fsdecode(_git(cwd, deadline, "rev-parse", "--show-prefix").rstrip(b"\n"))
    names = (_pushed if simple.verb == "push" else _committed)(simple, cwd, deadline)
    if not names:
        return None
    if gate not in NARROWABLE:
        return gate
    under = {name[len(prefix) :] for name in names if name.startswith(prefix)}
    if gate == _GO_GATE:  # cgo, headers, assembly, embed and go.work are all build inputs
        return gate if under else None
    if _lintable_link(cwd, deadline):
        return gate
    # A config in cwd or above it governs cwd, so changing it can change what the whole gate says.
    above = {""}
    parent = prefix.rstrip("/")
    while parent:
        above.add(parent)
        parent = os.path.dirname(parent)
    if any(os.path.basename(n) in _RUFF_CONFIGS and os.path.dirname(n) in above for n in names):
        return gate
    if not under:
        return None
    # A changed config changes what every file means, and a broken one passes on files alone.
    if any(os.path.basename(n) in _RUFF_CONFIGS for n in under) or _custom_inputs(cwd, under):
        return gate
    # A deleted `__init__.py` turns its siblings into findings (INP001) in files nothing changed.
    if any(
        os.path.basename(n) == "__init__.py" and not os.path.lexists(os.path.join(cwd, n))
        for n in under
    ):
        return gate
    # A directory is a submodule or a nested repo. A path that does not resolve to itself is, or
    # runs through, a symlink, or ends in a gitlink's slash. The whole gate reads those its own way.
    root = os.path.realpath(cwd)
    paths = {name: os.path.join(root, name) for name in under}
    if any(os.path.isdir(p) or os.path.realpath(p) != p for p in paths.values()):
        return gate
    # A file gone from the tree stays out: ruff would report it as a finding.
    lintable = (n for n in paths if n.endswith(_RUFF_EXTENSIONS))
    files = sorted(n for n in lintable if os.path.isfile(paths[n]))
    if not files:
        return None
    if sum(len(name) for name in files) > _MAX_ARGV:
        return gate
    return [*_RUFF_GATE[:2], *[f"./{name}" for name in files]]


def narrow(gate: list[str], command: str, cwd: str) -> list[str] | None:
    """``gate`` itself, None to skip it, or ruff over the changed files under ``cwd``."""
    simple = parse_simple(command)
    if simple is None or any(name in os.environ for name in _GIT_STEERING):
        return gate
    try:
        return _narrowed(gate, simple, cwd, time.monotonic() + _READ_BUDGET)
    except _GitFailed:
        return gate


def printable(text: str, keep: str = "\n\t") -> str:
    """``text`` with control characters and undecodable bytes escaped, except those in ``keep``: a
    filename is the repo's to choose, and this reaches a terminal and the model."""
    return "".join(
        ch if ch.isprintable() or ch in keep else ch.encode("unicode_escape").decode("ascii")
        for ch in text
    )
