"""Load and validate a component's evals.json against the project schema.

evals.json is the single machine-readable source of a component's readiness contract:
its identity, purpose, trigger examples, and numeric thresholds (definition of done).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

__all__ = [
    "EvalsError",
    "FIXTURE_TREE_MARKER",
    "WORKSPACES",
    "checked_fixture",
    "fixture_path_problem",
    "eval_case_problems",
    "workspace_case_ids",
    "fixture_dest",
    "load_evals",
    "validate_evals",
]

# plugin/lib/agentic_forge/evals.py -> plugin/schemas/evals.schema.json
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "evals.schema.json"


class EvalsError(ValueError):
    """Raised when evals.json cannot be read or parsed."""


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return data


def load_evals(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalsError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvalsError(f"{path}: top-level value must be an object")
    return data


def validate_evals(data: dict[str, Any], *, schema: dict[str, Any] | None = None) -> list[str]:
    """Return a list of schema-violation messages. Empty list means valid."""
    validator = jsonschema.Draft7Validator(schema or _schema())
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{location}: {err.message}")
    return errors


# A fixture path may carry a ``tree/`` directory segment: everything below it is the file's path
# INSIDE the sandbox (``eval/fixtures/rust-patterns/tree/src/lib.rs`` lands at ``src/lib.rs``),
# so a case can seed a real layout — a crate, a Maven tree, a plugin skeleton — instead of a
# pile of basenames. Without one a fixture lands by basename, as it always has.
FIXTURE_TREE_MARKER = "tree"

# A case's optional ``workspace`` (ADR 0116): ``dir`` runs it in a fresh directory holding its files
# and names them in the prompt instead of pasting them, so the component reads them with its tools
# (a bulk reader's job). Such a case needs a runner with tools: the eval CLIs skip its component
# under ``--runner api`` (:func:`workspace_case_ids`). See ``agent_eval._run_passes``.
WORKSPACES: tuple[str, ...] = ("dir",)
# Path parts a case's ``files`` entry may not hold: ``..`` would reach outside the plugin directory,
# and a ``.git`` part would read from (or seed the sandbox with) a repository's internals.
_FORBIDDEN_FILE_PARTS = frozenset({"..", ".git"})


def fixture_dest(rel: str) -> str:
    """Where a case's fixture file lands in the sandbox — and how the prompt labels it: its path
    below the first ``tree/`` segment when the entry has one, else its basename. Never the
    repo-relative path: a prompt must not hand a role a path it could resolve back to the real
    repository (see ``agent_eval.materialize_fixtures``)."""
    parts = Path(rel).parts
    if FIXTURE_TREE_MARKER in parts[:-1]:  # a directory segment, not a file named "tree"
        below = parts[parts.index(FIXTURE_TREE_MARKER) + 1 :]
        return Path(*below).as_posix()
    return Path(rel).name


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def fixture_path_problem(plugin_dir: Path, rel: str) -> str | None:
    """Why a case's ``files`` entry may not be used, or None. The one check behind the dry runner,
    :func:`checked_fixture` and so every read and copy of a fixture (ADR 0116): a fixture is copied
    into the role's sandbox, so its path may not be absolute or hold a ``..`` or ``.git`` part, and
    the file it resolves to, symlinks followed, must lie inside the plugin directory."""
    path = Path(rel)
    if path.is_absolute() or path.anchor:
        return "holds an absolute path"
    bad = _FORBIDDEN_FILE_PARTS.intersection(path.parts)
    if bad:
        return "holds " + ", ".join(sorted(bad))
    if not _inside((plugin_dir / rel).resolve(), plugin_dir.resolve()):
        return "resolves outside the plugin directory"
    return None


def checked_fixture(plugin_dir: Path, rel: str) -> Path:
    """The source path of a case's fixture, or :class:`EvalsError` when
    :func:`fixture_path_problem` refuses it."""
    problem = fixture_path_problem(plugin_dir, rel)
    if problem:
        raise EvalsError(f"fixture path {rel} {problem}")
    return plugin_dir / rel


def eval_case_problems(label: str, cases: list[dict[str, Any]], plugin_dir: Path) -> list[str]:
    """Per-case wiring problems shared by the skill + agent Tier-2 readiness checks: no eval cases,
    a case with no assertions, an unknown ``workspace``, two fixtures landing on the same sandbox
    path (see :func:`fixture_dest` — a collision silently overwrites), a fixture path that is
    absolute or holds a ``..`` or ``.git`` part, and a missing fixture file."""
    problems: list[str] = []
    if not cases:
        problems.append(f"{label}: contract has no eval cases")
    for case in cases:
        cid = case.get("id")
        if not (case.get("assertions") or []):
            problems.append(f"{label} case {cid}: no assertions")
        workspace = case.get("workspace")
        if workspace is not None and workspace not in WORKSPACES:
            problems.append(
                f"{label} case {cid}: unknown workspace {workspace!r} (one of {list(WORKSPACES)})"
            )
        files = case.get("files") or []
        dests = [fixture_dest(rel) for rel in files]
        if len(set(dests)) != len(dests):
            problems.append(f"{label} case {cid}: duplicate fixture destinations {dests}")
        for rel in files:
            problem = fixture_path_problem(plugin_dir, rel)
            if problem:
                problems.append(f"{label} case {cid}: fixture path {rel} {problem}")
                continue
            if not (plugin_dir / rel).is_file():
                problems.append(f"{label} case {cid}: missing fixture {rel}")
    return problems


def workspace_case_ids(cases: list[dict[str, Any]]) -> list[Any]:
    """The ids of the cases that ask for a ``workspace``: they name their files instead of pasting
    them, so a runner without tools (``--runner api``) would grade a model that never saw them."""
    return [case.get("id") for case in cases if case.get("workspace") is not None]
