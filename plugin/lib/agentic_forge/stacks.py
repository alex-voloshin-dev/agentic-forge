"""Deterministic stack detection for target repos (ADR 0015).

:func:`detect` inspects a target repo and returns ranked :class:`StackProfile`s describing the
stack(s) present, the conventional toolchain, and which ``*-patterns`` knowledge pack (if any)
applies. Detection is a *fact* derived from explicit hints and manifest files — never an LLM
guess — so the spine's ``develop`` / ``code-review`` phases run the **right** test/lint/type
commands on any stack.

Precedence: an explicit ``stack:`` hint in the repo's ``CLAUDE.md`` / ``AGENTS.md`` wins (it may
name several stacks, comma-separated); otherwise manifest signatures at the root, ranked by
specificity (most specific first, ties broken by id for determinism). A root that matches no
manifest is scanned one level down — a polyglot monorepo keeps its services in subdirectories —
and yields one profile per stack and directory, each carrying the ``dir`` it was found in. A repo
where nothing matches yields the ``unknown`` profile (engineering-standards only).

Toolchain commands in a profile are **fallbacks**: a consumer always prefers the repo's own
declared gate (its CI workflow, ``AGENTS.md`` / ``CLAUDE.md``, Makefile, package scripts) when
present; :func:`declared_gate_sources` lists where to look. The fallbacks are resolved against the
profile's directory rather than copied from the registry: a JavaScript/TypeScript profile names the
package manager the repo declares and only the scripts and tools it has, Go names golangci-lint when
it is configured, JVM uses the build wrapper, Terraform lists ``terraform test`` only when tests
exist and ``tflint`` only when it is configured.

This module is reachable from the commit-gate hook, so it runs on Python 3.9 and treats the repo
as untrusted: it never executes anything, reads only bounded prefixes of a few named files, and
does not read through a symlink that leaves the repo.
"""

from __future__ import annotations

import fnmatch
import itertools
import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

__all__ = [
    "Toolchain",
    "StackSpec",
    "StackProfile",
    "STACKS",
    "UNKNOWN",
    "STANDARDS_PACK",
    "PACKAGE_MANAGERS",
    "TOOLCHAIN_ROLE",
    "detect",
    "primary",
    "gate_profile",
    "declared_gate_sources",
    "format_profile",
    "format_profiles",
    "pack_path",
    "pack_paths",
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
    ``toolchain`` is the documented convention; a stack with a resolver (``_RESOLVERS``) refines it
    against the repo's files when a profile is built.
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
    toolchain: Toolchain  # fallbacks, resolved against `dir`; the repo's declared gate wins
    manifests: tuple[str, ...]  # evidence: matched manifest filenames (relative to `dir`), sorted
    source: str  # "hint" | "manifest" | "unknown"
    dir: str = "."  # where the stack was found, relative to the detected repo (POSIX), "." = root


# What a profile's toolchain is, for a consumer that prints or forwards it: never the gate itself.
TOOLCHAIN_ROLE = "fallback"
_FALLBACK_NOTE = (
    "commands are fallbacks: the repo's declared gate wins "
    "(CI workflow, AGENTS.md/CLAUDE.md, Makefile, package scripts)"
)

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
    # JavaScript/TypeScript commands are resolved from package.json (`_js_toolchain`): the declared
    # package manager, the repo's own scripts, else a declared tool run through the manager. These
    # are the shapes with npm and every script/tool present.
    "typescript": StackSpec(
        id="typescript",
        display="TypeScript",
        manifests=("tsconfig.json",),
        toolchain=Toolchain(
            test="npm run test",
            lint="npm run lint",
            typecheck="npm exec --no --package=typescript -- tsc --noEmit",
            format="npm exec --no --package=prettier -- prettier --write .",
        ),
        pack="typescript-patterns",
        specificity=3,
    ),
    "javascript": StackSpec(
        id="javascript",
        display="JavaScript (Node)",
        manifests=("package.json",),
        toolchain=Toolchain(
            test="npm run test",
            lint="npm run lint",
            format="npm exec --no --package=prettier -- prettier --write .",
        ),
        pack="javascript-patterns",
        specificity=1,
    ),
    "go": StackSpec(
        id="go",
        display="Go",
        manifests=("go.mod",),
        # `lint` becomes `golangci-lint run` when a golangci config sits beside go.mod.
        toolchain=Toolchain(
            test="go test -race ./...",
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
        manifests=(
            "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"
        ),
        # JVM spans Maven/Gradle and has no single canonical formatter (spotless/ktlint/
        # checkstyle vary), so lint/format stay unset — jvm-patterns defers to the repo's
        # configured ones. The test command is the lifecycle phase that also runs integration
        # tests (`verify` runs failsafe's *IT, `test` does not; Gradle's `check` runs `test` and
        # every verification task), through the wrapper when the repo ships one — beside the build
        # file, else at the repo root (`_jvm_toolchain`).
        toolchain=Toolchain(test="mvn verify"),
        pack="jvm-patterns",
        specificity=2,
    ),
    "dotnet": StackSpec(
        id="dotnet",
        display=".NET",
        manifests=("*.csproj", "*.sln"),
        toolchain=Toolchain(test="dotnet test", typecheck="dotnet build", format="dotnet format"),
        pack="dotnet-patterns",
        specificity=2,
    ),
    "ruby": StackSpec(
        id="ruby",
        display="Ruby",
        manifests=("Gemfile",),
        toolchain=Toolchain(test="bundle exec rspec", lint="rubocop"),
        pack="ruby-patterns",
        specificity=2,
    ),
    "php": StackSpec(
        id="php",
        display="PHP",
        manifests=("composer.json",),
        toolchain=Toolchain(test="composer test"),
        pack="php-patterns",
        specificity=1,
    ),
    # `typecheck` is a compound shell command (validate needs an initialised working dir;
    # `-backend=false` touches no state). Callers that run a toolchain command run it through a
    # shell; the commit gate runs only `lint` and refuses any command with shell syntax. `lint` is
    # `tflint --recursive` when `.tflint.hcl` sits in the profile's dir, else None, and the gate
    # never runs tflint (it only narrows, ADR 0101). `test` is dropped when no *.tftest.hcl exists.
    # `format` applies, like every stack's. Specificity 0: *.tf beside any language manifest is that
    # service's infra, not its stack. The pack (`terraform-patterns`) carries the IaC conventions:
    # offline checks only, the human plans and applies.
    "terraform": StackSpec(
        id="terraform",
        display="Terraform",
        manifests=("*.tf", ".terraform.lock.hcl"),
        toolchain=Toolchain(
            test="terraform test",
            typecheck="terraform init -backend=false && terraform validate",
            format="terraform fmt -recursive",
        ),
        pack="terraform-patterns",
        specificity=0,
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
    "tf": "terraform",
}

# Match a `stack:` / `stack =` declaration at the start of a line (allowing markdown bullet /
# blockquote / bold markers and indentation); the value is one name or a comma-separated list
# (`stack: go, jvm`). Matched one line at a time, because `\s` across lines made a file of newlines
# quadratic, and the commit gate reaches this (ADR 0104). The list needs a comma between names, so
# it cannot backtrack.
_HINT_RE = re.compile(
    r"(?i)[ \t\-*>]*stack[ \t*]*[:=][ \t*]*[\"'`]?"
    r"([A-Za-z0-9.#+]+(?:[\"'`]?[ \t]*,[ \t]*[\"'`]?[A-Za-z0-9.#+]+)*)"
)
_HINT_MAX_BYTES = 256 * 1024  # a hint is near the top of a file a person wrote

# Monorepo scan: one level down, bounded. Dot-dirs (.git, .claude/worktrees, .venv, ...) and
# dependency/build output are never a service.
_SCAN_SKIP = frozenset({
    "node_modules", "vendor", "target", "build", "dist", "out", "bin", "obj", "venv", "env",
    "__pycache__", "coverage", "site-packages",
})
# Every directory listing here is ONE `os.scandir`, cut off at this many entries: the root's (for
# the scan), each examined directory's (for wildcard manifests such as `*.tf`), a `tests/` and a
# workflows directory. Below the cap the result is complete and sorted; past it, which entries are
# seen is the filesystem's order. Exact manifest names are a `stat` each, never a listing.
_SCAN_MAX_ENTRIES = 2048
_SCAN_MAX_DIRS = 64  # subdirectories examined, in name order
# A subdirectory name reaches `dir`, the summary, `declared_gate_sources` and the working directory
# a caller runs commands in, so only a plain name passes: no whitespace, quotes or shell syntax, no
# leading dot or dash (a dot-dir is never a service anyway).
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}\Z")
# The same shape for a path part of a declared gate source, which may also be a dot-name
# (`.github`, `.gitlab-ci.yml`).
_SAFE_SOURCE_PART = re.compile(r"^\.?[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}\Z")

_PACKAGE_JSON_MAX_BYTES = 1024 * 1024
# The only package managers a profile ever names: the value reaches argv, so a `packageManager`
# field outside this set is ignored, never echoed.
PACKAGE_MANAGERS = ("npm", "yarn", "pnpm", "bun")
_LOCKFILES = (
    ("yarn.lock", "yarn"),
    ("pnpm-lock.yaml", "pnpm"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
    ("package-lock.json", "npm"),
)
# How yarn (classic and berry), pnpm and bun run an installed dependency's binary; none of them
# downloads a missing one. npm is `_exec`'s special case.
_PM_RUN_BIN = {"yarn": "yarn run", "pnpm": "pnpm exec", "bun": "bun run"}
_GOLANGCI_CONFIGS = (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
_TFLINT_CONFIG = ".tflint.hcl"
_TFLINT_LINT = "tflint --recursive"
_GRADLE_FILES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")


def _inside(root: Path, path: Path) -> bool:
    """True when ``path`` resolves inside ``root`` — a symlink out of the repo is not followed."""
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _read_head(root: Path | None, path: Path, cap: int) -> bytes | None:
    """At most ``cap + 1`` bytes of a regular file inside ``root`` (anywhere when ``root`` is
    None), else None. ``is_file`` follows the link and is false for a pipe or a device, so a name a
    repo points at one is never opened."""
    try:
        if not path.is_file() or (root is not None and not _inside(root, path)):
            return None
        with path.open("rb") as handle:
            return handle.read(cap + 1)
    except OSError:
        return None


def _list_dir(where: Path) -> list[os.DirEntry[str]]:
    """At most ``_SCAN_MAX_ENTRIES`` entries of ``where``, by name; [] if it cannot be read."""
    try:
        with os.scandir(where) as listing:
            entries = list(itertools.islice(listing, _SCAN_MAX_ENTRIES))
    except OSError:
        return []
    return sorted(entries, key=lambda entry: entry.name)


def _file_names(where: Path) -> list[str]:
    """The regular files (a link to one included, as ``Path.is_file``) in ``_list_dir(where)``."""

    def is_file(entry: os.DirEntry[str]) -> bool:
        try:
            return entry.is_file()
        except OSError:
            return False

    return [entry.name for entry in _list_dir(where) if is_file(entry)]


def _normalize_hint(raw: str) -> str | None:
    """Map a raw `stack:` value to a canonical registry id, or None if unknown."""
    token = raw.strip().strip("\"'`").lower()
    if token in STACKS:
        return token
    return _ALIASES.get(token)


def _read_hint(repo: Path, *, follow_links: bool = False, first_only: bool = False) -> list[str]:
    """The canonical stack ids a `stack:` hint in CLAUDE.md / AGENTS.md names, in its order.

    Unknown names are skipped; a hint naming none falls through to the next file, then to [].
    ``first_only`` reads the first name alone (unknown -> the next file), as the single-name hint
    did; ``follow_links`` reads a hint file wherever it links, as the commit gate always has.
    """
    for name in ("CLAUDE.md", "AGENTS.md"):
        data = _read_head(None if follow_links else repo, repo / name, _HINT_MAX_BYTES)
        if data is None:
            continue
        head = data[:_HINT_MAX_BYTES].decode("utf-8", errors="ignore")
        match = next(filter(None, map(_HINT_RE.match, head.splitlines())), None)
        if not match:
            continue
        raw_names = match.group(1).split(",")
        ids: list[str] = []
        for raw in raw_names[:1] if first_only else raw_names:
            canonical = _normalize_hint(raw)
            if canonical and canonical not in ids:
                ids.append(canonical)
        if ids:
            return ids
    return []


def _matched_manifests(
    where: Path, spec: StackSpec, files: list[str] | None = None
) -> tuple[str, ...]:
    """Manifest filenames (relative, sorted) present in ``where`` for ``spec``. An exact name is a
    stat; a wildcard is matched against ``files`` (one capped listing of ``where``)."""
    found: set[str] = set()
    for pattern in spec.manifests:
        if "*" in pattern:
            if files is None:
                files = _file_names(where)
            found.update(name for name in files if fnmatch.fnmatchcase(name, pattern))
        elif (where / pattern).is_file():
            found.add(pattern)
    return tuple(sorted(found))


def _subdirs(root: Path) -> list[Path]:
    """The immediate subdirectories a monorepo scan examines: bounded, sorted, plain names only,
    no symlinks, and only those this process can list (a bind-mounted `pgdata` owned by another
    user is skipped rather than raising)."""

    def scannable(entry: os.DirEntry[str]) -> bool:
        if not _SAFE_NAME.match(entry.name) or entry.name in _SCAN_SKIP:
            return False
        try:
            if not entry.is_dir(follow_symlinks=False):
                return False
        except OSError:
            return False
        return os.access(entry.path, os.R_OK | os.X_OK)

    names = [entry.name for entry in _list_dir(root) if scannable(entry)]
    return [root / name for name in names[:_SCAN_MAX_DIRS]]


# --- toolchain resolution (per profile directory) -------------------------------------------------


def _package_json(root: Path, where: Path) -> dict[str, Any]:
    """``where/package.json`` as a dict; {} when absent, oversized, outside the repo or invalid.
    Integers parse to 0: Python 3.9 has no digit limit, and a huge one parses quadratically."""
    data = _read_head(root, where / "package.json", _PACKAGE_JSON_MAX_BYTES)
    if data is None or len(data) > _PACKAGE_JSON_MAX_BYTES:
        return {}
    try:
        doc = json.loads(data.decode("utf-8", errors="replace"), parse_int=lambda _: 0)
    except (ValueError, RecursionError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _names(value: object) -> set[str]:
    return {k for k in value if isinstance(k, str)} if isinstance(value, dict) else set()


def _package_manager(dirs: Iterable[Path], docs: Iterable[dict[str, Any]]) -> str:
    """The declared package manager: a `packageManager` field first, then a lockfile, else npm.

    ``dirs``/``docs`` are searched nearest first (the profile's directory, then the repo root)."""
    for doc in docs:
        declared = doc.get("packageManager")
        if isinstance(declared, str):
            name = declared.split("@", 1)[0].strip().lower()
            if name in PACKAGE_MANAGERS:
                return name
    for where in dirs:
        for lockfile, manager in _LOCKFILES:
            if (where / lockfile).is_file():
                return manager
    return "npm"


def _exec(pm: str, package: str, invocation: str) -> str:
    """Run the installed binary of a declared dependency through ``pm`` — never a download.

    Without a TTY `npm exec` assumes `--yes` and installs a missing package from the registry: in a
    fresh worktree with no node_modules, `npm exec -- tsc` fetches and runs the unrelated `tsc`
    package. `--no` refuses to install, and `--package` names the package the binary belongs to."""
    if pm == "npm":
        return f"npm exec --no --package={package} -- {invocation}"
    return f"{_PM_RUN_BIN[pm]} {invocation}"


def _js_toolchain(root: Path, where: Path, spec: StackSpec) -> Toolchain:
    """A command only for what package.json declares: the repo's script first, else a declared
    (dev)dependency's binary through the package manager, else None."""
    doc = _package_json(root, where)
    dirs = [where] if where == root else [where, root]
    docs = [doc] if where == root else [doc, _package_json(root, root)]
    pm = _package_manager(dirs, docs)
    declared = doc.get("scripts")
    scripts = (
        {k for k, v in declared.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(declared, dict)
        else set()
    )
    deps = _names(doc.get("dependencies")) | _names(doc.get("devDependencies"))

    def pick(script_names: tuple[str, ...], tools: tuple[tuple[str, str], ...]) -> str | None:
        for script in script_names:
            if script in scripts:
                return f"{pm} run {script}"
        for package, invocation in tools:
            if package in deps:
                return _exec(pm, package, invocation)
        return None

    has_tsconfig = (where / "tsconfig.json").is_file()
    return Toolchain(
        test=pick(("test",), (("vitest", "vitest run"), ("jest", "jest"))),
        lint=pick(("lint",), (("eslint", "eslint ."),)),
        typecheck=pick(
            ("typecheck", "type-check"),
            (("typescript", "tsc --noEmit"),) if has_tsconfig else (),
        ),
        format=pick(("format",), (("prettier", "prettier --write ."),)),
    )


def _go_toolchain(root: Path, where: Path, spec: StackSpec) -> Toolchain:
    if any((where / name).is_file() for name in _GOLANGCI_CONFIGS):
        return replace(spec.toolchain, lint="golangci-lint run")
    return spec.toolchain


def _wrapper(root: Path, where: Path, name: str) -> str | None:
    """A build wrapper in ``where``, else at the repo root (the `gradle init` layout keeps it there
    beside settings.gradle), as a path to run from ``where``."""
    for base in [where] if where == root else [where, root]:
        if (base / name).is_file():
            if base == where:
                return f"./{name}"
            return Path(os.path.relpath(base / name, where)).as_posix()
    return None


def _jvm_toolchain(root: Path, where: Path, spec: StackSpec) -> Toolchain:
    if (where / "pom.xml").is_file():
        test = f"{_wrapper(root, where, 'mvnw') or 'mvn'} verify"
    elif any((where / name).is_file() for name in _GRADLE_FILES):
        test = f"{_wrapper(root, where, 'gradlew') or 'gradle'} check"
    else:  # hinted, no build file here: the convention
        return spec.toolchain
    return replace(spec.toolchain, test=test)


def _terraform_toolchain(root: Path, where: Path, spec: StackSpec) -> Toolchain:
    tests = where / "tests"
    lint = _TFLINT_LINT if (where / _TFLINT_CONFIG).is_file() else None

    def has_tftest(directory: Path) -> bool:
        return any(fnmatch.fnmatchcase(name, "*.tftest.hcl") for name in _file_names(directory))

    has_tests = has_tftest(where) or (
        tests.is_dir() and not tests.is_symlink() and has_tftest(tests)
    )
    return replace(spec.toolchain, test=spec.toolchain.test if has_tests else None, lint=lint)


# Annotation only (never evaluated on 3.9): a resolver refines a spec's toolchain for one dir.
_RESOLVERS: dict[str, Callable[[Path, Path, StackSpec], Toolchain]] = {
    "typescript": _js_toolchain,
    "javascript": _js_toolchain,
    "go": _go_toolchain,
    "jvm": _jvm_toolchain,
    "terraform": _terraform_toolchain,
}


def _profile(
    root: Path, where: Path, spec: StackSpec, manifests: tuple[str, ...], source: str
) -> StackProfile:
    resolve = _RESOLVERS.get(spec.id)
    return StackProfile(
        stack_id=spec.id,
        display=spec.display,
        pack=spec.pack,
        toolchain=resolve(root, where, spec) if resolve else spec.toolchain,
        manifests=manifests,
        source=source,
        dir="." if where == root else where.relative_to(root).as_posix(),
    )


def _manifest_matches(where: Path) -> list[tuple[StackSpec, tuple[str, ...]]]:
    """Every stack whose manifest is in ``where``; TypeScript supersedes a bare package.json."""
    files = _file_names(where)
    matches = [
        (spec, m) for spec in STACKS.values() if (m := _matched_manifests(where, spec, files))
    ]
    ids = {spec.id for spec, _ in matches}
    if "typescript" in ids and "javascript" in ids:
        matches = [(spec, m) for spec, m in matches if spec.id != "javascript"]
    return matches


def _rank(profile: StackProfile) -> tuple[int, str, str]:
    return (-STACKS[profile.stack_id].specificity, profile.stack_id, profile.dir)


def _below(root: Path, where: Path, spec: StackSpec | None) -> list[StackProfile]:
    """The profiles one scanned subdirectory yields (only ``spec``'s when given). A directory that
    stops being readable mid-scan yields none: an OSError there is not the whole repo's failure."""
    try:
        if spec is not None:
            found = _matched_manifests(where, spec)
            return [_profile(root, where, spec, found, "hint")] if found else []
        return [_profile(root, where, s, m, "manifest") for s, m in _manifest_matches(where)]
    except OSError:
        return []


def detect(repo: Path | str, *, scan_subdirs: bool = True) -> list[StackProfile]:
    """Detect the stack(s) in ``repo``, most-relevant first.

    An explicit ``stack:`` hint short-circuits to the stacks it names, in its order; a hinted
    stack with no manifest at the root is looked for one level down. Otherwise every stack whose
    manifest signature is at the root is returned, ranked by specificity (TypeScript supersedes a
    bare ``package.json``). A root that matches nothing is scanned one level down (bounded; see
    ``_subdirs``) and yields one profile per stack and directory. Nothing anywhere returns
    ``[UNKNOWN]``. ``scan_subdirs=False`` keeps detection to the root.
    """
    root = Path(repo)
    subdirs: list[Path] | None = None

    def below() -> list[Path]:
        nonlocal subdirs
        if subdirs is None:
            subdirs = _subdirs(root) if scan_subdirs else []
        return subdirs

    hinted = _read_hint(root)
    if hinted:
        profiles: list[StackProfile] = []
        for stack_id in hinted:
            spec = STACKS[stack_id]
            here = _matched_manifests(root, spec)
            found = [] if here else [p for where in below() for p in _below(root, where, spec)]
            profiles.extend(found or [_profile(root, root, spec, here, "hint")])
        return profiles

    found_at_root = _manifest_matches(root)
    if found_at_root:
        profiles = [_profile(root, root, spec, m, "manifest") for spec, m in found_at_root]
    else:
        profiles = [p for where in below() for p in _below(root, where, None)]
    if not profiles:
        return [UNKNOWN]
    return sorted(profiles, key=_rank)


def primary(repo: Path | str, *, scan_subdirs: bool = True) -> StackProfile:
    """The single most-relevant stack profile for ``repo`` (first of :func:`detect`)."""
    return detect(repo, scan_subdirs=scan_subdirs)[0]


def gate_profile(cwd: Path | str) -> StackProfile:
    """The profile the commit gate takes its lint from, read as it was before multi-name hints and
    the monorepo scan, so a richer `stack-detect` cannot change what the gate runs: ``cwd`` only,
    a hint's FIRST name only (unknown -> the next file, then manifests), and the hint file read
    wherever it links (a regular file, capped) — it is the file the session itself reads."""
    root = Path(cwd)
    hinted = _read_hint(root, follow_links=True, first_only=True)
    if hinted:
        spec = STACKS[hinted[0]]
        return _profile(root, root, spec, _matched_manifests(root, spec), "hint")
    found = [_profile(root, root, spec, m, "manifest") for spec, m in _manifest_matches(root)]
    return sorted(found, key=_rank)[0] if found else UNKNOWN


# Where a repo declares its own gate, relative to a profile's directory. Existence only: these are
# pointers for the reader, never parsed or run here.
_GATE_SOURCE_FILES = (
    "AGENTS.md", "CLAUDE.md", "Makefile", "justfile", "Taskfile.yml", "package.json", "tox.ini",
    "noxfile.py", ".pre-commit-config.yaml", ".gitlab-ci.yml", ".circleci/config.yml",
    "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile",
)
_WORKFLOW_SUFFIXES = (".yml", ".yaml")
_GATE_SOURCES_MAX = 32


def _safe_dir(rel: str) -> bool:
    return rel == "." or all(_SAFE_NAME.match(part) for part in rel.split("/"))


def declared_gate_sources(
    repo: Path | str, profiles: Iterable[StackProfile] = ()
) -> list[str]:
    """Files where ``repo`` may declare its own gate — CI workflows, agent docs, task runners,
    package scripts — at the root and in each profile's directory. Sorted repo-relative POSIX paths,
    at most ``_GATE_SOURCES_MAX``. A file that resolves outside the repo, or whose path has a part
    that is not a plain name (``_SAFE_SOURCE_PART``), is left out; so is a directory that cannot be
    read."""
    root = Path(repo)
    dirs = ["."]
    dirs.extend(p.dir for p in profiles if p.dir not in dirs and _safe_dir(p.dir))
    found: set[str] = set()
    for rel in dirs:
        where = root if rel == "." else root / rel
        try:
            candidates = [where / name for name in _GATE_SOURCE_FILES]
            workflows = where / ".github" / "workflows"
            if workflows.is_dir():
                names = [n for n in _file_names(workflows) if n.endswith(_WORKFLOW_SUFFIXES)]
                candidates.extend(workflows / name for name in names[:_GATE_SOURCES_MAX])
            for path in candidates:
                if not path.is_file() or not _inside(root, path):
                    continue
                source = path.relative_to(root).as_posix()
                if all(_SAFE_SOURCE_PART.match(part) for part in source.split("/")):
                    found.add(source)
        except OSError:
            continue
    return sorted(found)[:_GATE_SOURCES_MAX]


# Knowledge packs — `engineering-standards` and every `*-patterns` skill — are
# `disable-model-invocation: true` (ADR 0015): absent from the model's skill listing, which is
# what keeps the listing budget flat, and therefore impossible to invoke by name. A role reaches
# one only by READING its file; `pack_path` is the one place that knows the file's shape.
STANDARDS_PACK = "engineering-standards"
_PACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def pack_path(plugin_root: Path | str, pack: str) -> Path:
    """The file a role reads to load a knowledge pack: ``<plugin_root>/skills/<pack>/SKILL.md``.

    ``plugin_root`` is ``${CLAUDE_PLUGIN_ROOT}`` at runtime. The name is validated to the skill-name
    shape rather than sanitised — a pack name that needs escaping is a caller bug, not something
    to paper over (the same stance ``doc_delivery`` takes on slugs).
    """
    if not _PACK_NAME_RE.match(pack):
        raise ValueError(f"invalid pack name {pack!r}: expected {_PACK_NAME_RE.pattern}")
    return Path(plugin_root) / "skills" / pack / "SKILL.md"


def pack_paths(plugin_root: Path | str, profile: StackProfile) -> list[Path]:
    """Every pack file a role reads for ``profile``, in reading order: the standards first, then
    the stack pack when the profile names one (the ``unknown`` profile reads the standards only)."""
    paths = [pack_path(plugin_root, STANDARDS_PACK)]
    if profile.pack:
        paths.append(pack_path(plugin_root, profile.pack))
    return paths


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
    where = f" in {profile.dir}/" if profile.dir != "." else ""
    note = f"; {_FALLBACK_NOTE}" if cmds else ""
    return (
        f"stack={profile.display} [{profile.stack_id}]{where} via {profile.source} "
        f"({evidence}); pack={pack}; {cmds or 'no conventional commands'}{note}"
    )


def format_profiles(profiles: list[StackProfile]) -> str:
    """:func:`format_profile` of the primary, naming the other profiles (a monorepo's services)."""
    line = format_profile(profiles[0])
    others = ", ".join(f"{p.stack_id} ({p.dir})" for p in profiles[1:])
    return f"{line}; also: {others}" if others else line
