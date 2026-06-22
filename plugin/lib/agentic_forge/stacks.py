"""Deterministic stack detection for target repos (ADR 0015).

:func:`detect` inspects a target repo and returns ranked :class:`StackProfile`s describing the
stack(s) present, the conventional toolchain, and which ``*-patterns`` knowledge pack (if any)
applies. Detection is a *fact* derived from explicit hints and manifest files — never an LLM
guess — so the spine's ``develop`` / ``code-review`` phases run the **right** test/lint/type
commands on any stack.

Precedence: an explicit ``stack:`` hint in the repo's ``CLAUDE.md`` / ``AGENTS.md`` wins;
otherwise manifest signatures, ranked by specificity (most specific first, ties broken by id
for determinism). An empty/unknown repo yields the ``unknown`` profile (engineering-standards
only).

Toolchain commands in a profile are **conventional fallbacks** — a consumer always prefers the
repo's own declared commands (CLAUDE.md / Makefile / ``package.json`` scripts) when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Toolchain",
    "StackSpec",
    "StackProfile",
    "STACKS",
    "UNKNOWN",
    "detect",
    "primary",
    "format_profile",
]


@dataclass(frozen=True)
class Toolchain:
    """Conventional commands for a stack. ``None`` = no conventional default."""

    test: str | None = None
    lint: str | None = None
    typecheck: str | None = None
    format: str | None = None


@dataclass(frozen=True)
class StackSpec:
    """Registry entry: how to detect a stack and its conventional toolchain.

    ``manifests`` are filenames or globs (containing ``*``) that signal the stack.
    ``pack`` is the ``*-patterns`` knowledge skill name, or ``None`` if none ships yet.
    ``specificity`` ranks overlapping matches (higher = more specific).
    """

    id: str
    display: str
    manifests: tuple[str, ...]
    toolchain: Toolchain
    pack: str | None = None
    specificity: int = 1


@dataclass(frozen=True)
class StackProfile:
    """A detected stack for a repo — the "stack profile" the workflows consume."""

    stack_id: str
    display: str
    pack: str | None
    toolchain: Toolchain
    manifests: tuple[str, ...]  # evidence: matched manifest filenames (relative), sorted
    source: str  # "hint" | "manifest" | "unknown"


# Registry — adding a language is one entry (data, not code). Detection ships for all of these;
# `*-patterns` knowledge packs ship one at a time (only `pack` is set when a pack exists).
STACKS: dict[str, StackSpec] = {
    "python": StackSpec(
        id="python",
        display="Python",
        manifests=("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"),
        toolchain=Toolchain(
            test="pytest", lint="ruff check .", typecheck="mypy .", format="ruff format ."
        ),
        pack="python-patterns",
        specificity=2,
    ),
    "typescript": StackSpec(
        id="typescript",
        display="TypeScript",
        manifests=("tsconfig.json",),
        toolchain=Toolchain(
            test="npm test",
            lint="npm run lint",
            typecheck="tsc --noEmit",
            format="prettier --write .",
        ),
        pack="typescript-patterns",
        specificity=3,
    ),
    "javascript": StackSpec(
        id="javascript",
        display="JavaScript (Node)",
        manifests=("package.json",),
        toolchain=Toolchain(test="npm test", lint="npm run lint", format="prettier --write ."),
        specificity=1,
    ),
    "go": StackSpec(
        id="go",
        display="Go",
        manifests=("go.mod",),
        toolchain=Toolchain(
            test="go test ./...",
            lint="go vet ./...",
            typecheck="go build ./...",
            format="gofmt -w .",
        ),
        pack="go-patterns",
        specificity=2,
    ),
    "rust": StackSpec(
        id="rust",
        display="Rust",
        manifests=("Cargo.toml",),
        toolchain=Toolchain(
            test="cargo test", lint="cargo clippy", typecheck="cargo check", format="cargo fmt"
        ),
        pack="rust-patterns",
        specificity=2,
    ),
    "jvm": StackSpec(
        id="jvm",
        display="JVM (Java/Kotlin)",
        manifests=("pom.xml", "build.gradle", "build.gradle.kts"),
        toolchain=Toolchain(test="mvn test"),
        specificity=2,
    ),
    "dotnet": StackSpec(
        id="dotnet",
        display=".NET",
        manifests=("*.csproj", "*.sln"),
        toolchain=Toolchain(test="dotnet test", typecheck="dotnet build", format="dotnet format"),
        specificity=2,
    ),
    "ruby": StackSpec(
        id="ruby",
        display="Ruby",
        manifests=("Gemfile",),
        toolchain=Toolchain(test="bundle exec rspec", lint="rubocop"),
        specificity=2,
    ),
    "php": StackSpec(
        id="php",
        display="PHP",
        manifests=("composer.json",),
        toolchain=Toolchain(test="composer test"),
        specificity=1,
    ),
}

UNKNOWN = StackProfile(
    stack_id="unknown",
    display="Unknown",
    pack=None,
    toolchain=Toolchain(),
    manifests=(),
    source="unknown",
)

# Common spellings/aliases a repo might use in a `stack:` hint -> canonical registry id.
_ALIASES: dict[str, str] = {
    "py": "python",
    "python3": "python",
    "ts": "typescript",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "node.js": "javascript",
    "golang": "go",
    "rs": "rust",
    "java": "jvm",
    "kotlin": "jvm",
    "csharp": "dotnet",
    "c#": "dotnet",
    ".net": "dotnet",
    "rb": "ruby",
}

# Match a `stack:` / `stack =` declaration at the start of a line (allowing markdown bullet /
# blockquote / bold markers and indentation). The separators around the delimiter are
# line-local (`[ \t*]`, not `\s`) so a bare `stack:` never bridges a newline to grab the next
# line's token as the value.
_HINT_RE = re.compile(
    r"(?im)^[\s\-*>]*stack[ \t*]*[:=][ \t*]*[\"'`]?([A-Za-z0-9.#+]+)"
)


def _normalize_hint(raw: str) -> str | None:
    """Map a raw `stack:` value to a canonical registry id, or None if unknown."""
    token = raw.strip().strip("\"'`").lower()
    if token in STACKS:
        return token
    return _ALIASES.get(token)


def _read_hint(repo: Path) -> str | None:
    """Return the canonical stack id from a `stack:` hint in CLAUDE.md / AGENTS.md, else None."""
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = repo / name
        if not path.is_file():
            continue
        match = _HINT_RE.search(path.read_text(encoding="utf-8", errors="ignore"))
        if match:
            canonical = _normalize_hint(match.group(1))
            if canonical:
                return canonical
    return None


def _matched_manifests(repo: Path, spec: StackSpec) -> tuple[str, ...]:
    """Manifest filenames (relative, sorted) present in ``repo`` for ``spec``."""
    found: set[str] = set()
    for pattern in spec.manifests:
        if "*" in pattern:
            found.update(p.name for p in repo.glob(pattern) if p.is_file())
        elif (repo / pattern).is_file():
            found.add(pattern)
    return tuple(sorted(found))


def _profile(spec: StackSpec, manifests: tuple[str, ...], source: str) -> StackProfile:
    return StackProfile(
        stack_id=spec.id,
        display=spec.display,
        pack=spec.pack,
        toolchain=spec.toolchain,
        manifests=manifests,
        source=source,
    )


def detect(repo: Path | str) -> list[StackProfile]:
    """Detect the stack(s) in ``repo``, most-relevant first.

    An explicit ``stack:`` hint short-circuits to a single profile. Otherwise every stack whose
    manifest signature is present is returned, ranked by specificity (TypeScript supersedes a
    bare ``package.json``). An empty/unknown repo returns ``[UNKNOWN]``.
    """
    repo = Path(repo)

    hinted = _read_hint(repo)
    if hinted:
        spec = STACKS[hinted]
        return [_profile(spec, _matched_manifests(repo, spec), source="hint")]

    matches = [(spec, m) for spec in STACKS.values() if (m := _matched_manifests(repo, spec))]
    if not matches:
        return [UNKNOWN]

    ids = {spec.id for spec, _ in matches}
    if "typescript" in ids and "javascript" in ids:
        matches = [(spec, m) for spec, m in matches if spec.id != "javascript"]

    matches.sort(key=lambda sm: (-sm[0].specificity, sm[0].id))
    return [_profile(spec, m, source="manifest") for spec, m in matches]


def primary(repo: Path | str) -> StackProfile:
    """The single most-relevant stack profile for ``repo`` (first of :func:`detect`)."""
    return detect(repo)[0]


def format_profile(profile: StackProfile) -> str:
    """A one-line human summary for a workflow to log after detection."""
    tc = profile.toolchain
    cmds = ", ".join(
        f"{label}=`{cmd}`"
        for label, cmd in (
            ("test", tc.test),
            ("lint", tc.lint),
            ("typecheck", tc.typecheck),
        )
        if cmd
    )
    pack = profile.pack or "engineering-standards only (no pack)"
    evidence = ", ".join(profile.manifests) if profile.manifests else "—"
    return (
        f"stack={profile.display} [{profile.stack_id}] via {profile.source} "
        f"({evidence}); pack={pack}; {cmds or 'no conventional commands'}"
    )
