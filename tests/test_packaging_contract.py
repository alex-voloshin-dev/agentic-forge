"""Contract tests for the packaging + state boundary (ADR 0072).

Both invariants this file pins were violated in production and fixed once; nothing stopped them
from coming back. A fix without a gate is a fix with a half-life:

1. **Only ``plugin/`` ships.** A shipped artifact that tells a user to run ``dev/<cli>.py`` names a
   path their installation does not contain (field report AF-06).
2. **The plugin does not write into a repo it does not own.** Generated state belongs under
   ``diagnostics.state_root()``; the only in-repo ``.agentic-forge`` paths allowed in shipped code
   are the committed *config* and the *legacy read-fallback* constants (field report AF-05).

Note that ``conftest``'s ``AGENTIC_FORGE_STATE_HOME`` fixture would *hide* a regression of (2):
a hard-coded ``root / ".agentic-forge" / …`` write lands harmlessly in a ``tmp_path`` and no
behavioural test fails. So this has to be a structural check.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
sys.path.insert(0, str(_PLUGIN / "lib"))

from agentic_forge import diagnostics  # noqa: E402

# The three runtime CLIs. A shipped file may reference them under `plugin/bin/` or
# `${CLAUDE_PLUGIN_ROOT}/bin/`, never under `dev/`.
_RUNTIME_CLIS = ("run_scheduled.py", "pr_watch.py", "external_review.py")

_TEXT_SUFFIXES = {".md", ".py", ".json", ".txt", ".yml", ".yaml"}


def _shipped_text_files() -> list[Path]:
    return sorted(
        p
        for p in _PLUGIN.rglob("*")
        if p.is_file() and p.suffix in _TEXT_SUFFIXES and "__pycache__" not in p.parts
    )


def test_no_shipped_file_points_at_a_dev_cli() -> None:
    offenders = [
        f"{p.relative_to(_REPO)}: dev/{cli}"
        for p in _shipped_text_files()
        for cli in _RUNTIME_CLIS
        if f"dev/{cli}" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "shipped files reference a `dev/` CLI that is NOT installed with the plugin "
        f"(use ${{CLAUDE_PLUGIN_ROOT}}/bin/…): {offenders}"
    )


def test_runtime_clis_live_in_the_shipped_tree() -> None:
    for cli in _RUNTIME_CLIS:
        assert (_PLUGIN / "bin" / cli).is_file(), f"plugin/bin/{cli} is missing"
        assert not (_REPO / "dev" / cli).exists(), f"dev/{cli} came back — it must ship, not stay"


def test_shipped_clis_import_only_stdlib_and_agentic_forge() -> None:
    """A shipped CLI may not import a maintainer-side module — the user has no `dev/` tree."""
    maintainer_modules = {p.stem for p in (_REPO / "dev").glob("*.py")}
    for cli in _RUNTIME_CLIS:
        tree = ast.parse((_PLUGIN / "bin" / cli).read_text(encoding="utf-8"))
        imported = {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        leaked = imported & maintainer_modules
        assert not leaked, f"plugin/bin/{cli} imports maintainer-only module(s): {sorted(leaked)}"


# Every in-repo `.agentic-forge/...` path literal allowed in shipped Python, and why. A new entry
# here is a deliberate decision; an unlisted one fails the gate.
_ALLOWED_IN_REPO_PATHS = {
    ("agentic_forge/diagnostics.py", ".agentic-forge/diagnostics.jsonl"),  # legacy read-fallback
    ("agentic_forge/observability.py", ".agentic-forge/audit.jsonl"),  # legacy read-fallback
    ("agentic_forge/schedule.py", ".agentic-forge/schedule-state.json"),  # legacy read-fallback
    ("agentic_forge/pr_watch.py", ".agentic-forge/pr-watch-queue.json"),  # legacy read-fallback
}
# The committed config is the REPO's file, not generated state — any shipped module may name it.
_ALWAYS_ALLOWED = {".agentic-forge/config.json"}


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


@pytest.mark.parametrize(
    "root", [_PLUGIN / "lib", _PLUGIN / "hooks" / "scripts", _PLUGIN / "bin"], ids=str
)
def test_no_undeclared_in_repo_state_path(root: Path) -> None:
    """State must resolve through ``state_root()``; only declared literals may name an in-repo path.

    Docstrings and messages are literals too, so this also catches a doc claim that drifts back to
    the old location — the doc-truth class this repo keeps rediscovering.
    """
    offenders = []
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        rel = str(py.relative_to(_PLUGIN / "lib" if root.name == "lib" else root.parent))
        for literal in _string_literals(py):
            for line in literal.splitlines():
                idx = line.find(".agentic-forge/")
                while idx != -1:
                    span = "." + line[idx + 1 :].split()[0].rstrip("`,.'\");:")
                    home_relative = idx > 0 and line[idx - 1] == "~"
                    names_a_file = span.endswith((".json", ".jsonl"))
                    if (
                        not home_relative
                        and names_a_file
                        and span not in _ALWAYS_ALLOWED
                        and (rel, span) not in _ALLOWED_IN_REPO_PATHS
                    ):
                        offenders.append(f"{py.relative_to(_REPO)}: {span!r}")
                    idx = line.find(".agentic-forge/", idx + 1)
    assert not offenders, (
        "undeclared in-repo state path(s) in shipped code — generated state belongs under "
        f"diagnostics.state_root(): {sorted(set(offenders))}"
    )


def test_state_root_is_outside_the_repo_by_default(tmp_path: Path) -> None:
    """The headline promise: a repo the plugin does not own stays clean."""
    root = diagnostics.state_root(tmp_path)
    assert tmp_path not in root.parents and root != tmp_path
    assert root.name.startswith(tmp_path.name)  # keyed by the repo, just not stored inside it
