#!/usr/bin/env python3
"""Smoke-run every hook under the interpreter this script runs on (ADR 0094).

Hooks run under the user's bare ``python3`` — on a stock macOS that is CPython 3.9.6 — while the
repo's own tooling requires 3.11. A 3.10+ construct on a hook-reachable path fails to even parse
there, and a hook that fails to start fails OPEN: the guardrail is silently gone and nothing says
so. CI runs this file under 3.9 (the ``hooks-py39`` job in ``ci.yml``); it needs nothing installed.

Three checks, stdlib only:

1. every shipped ``.py`` (hooks, lib, bin, skill scripts) byte-compiles under this interpreter;
2. every lib module a hook imports — transitively — imports;
3. every hook runs to exit 0 on a minimal payload for its event and prints nothing or JSON.

A hook script with no payload in :data:`PAYLOADS` is a failure too: a new hook must be smoked.
State goes to a temp directory (``AGENTIC_FORGE_STATE_HOME``), never to the operator's.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
LIB = PLUGIN / "lib"
HOOKS = PLUGIN / "hooks" / "scripts"

_BASH = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
_POST = {"tool_response": {"stdout": "", "stderr": "", "interrupted": False}}

# One minimal payload per hook, for the event hooks.json registers it under. Nothing here should
# trigger a gate or a block: the point is "the hook starts and answers", not its verdict.
PAYLOADS: dict[str, dict[str, object]] = {
    "session_start.py": {"hook_event_name": "SessionStart", "source": "startup"},
    "security.py": {"hook_event_name": "PreToolUse", **_BASH},
    "commit_gate.py": {"hook_event_name": "PreToolUse", **_BASH},
    "merge_preflight.py": {"hook_event_name": "PreToolUse", **_BASH},
    "budget.py": {"hook_event_name": "PreToolUse", "tool_name": "Task",
                  "tool_input": {"prompt": "smoke", "subagent_type": "Explore"}},
    "audit_log.py": {"hook_event_name": "PostToolUse", **_BASH, **_POST},
    "pr_created.py": {"hook_event_name": "PostToolUse", **_BASH, **_POST},
    "pre_router.py": {"hook_event_name": "UserPromptSubmit", "prompt": "hello"},
}


def shipped_python() -> list[Path]:
    globs = ("hooks/scripts/*.py", "lib/agentic_forge/*.py", "bin/*.py", "skills/*/scripts/*.py")
    out: list[Path] = []
    for g in globs:
        out.extend(sorted(PLUGIN.glob(g)))
    return out


def _lib_imports(path: Path) -> set[str]:
    """The ``agentic_forge`` modules ``path`` imports directly."""
    mods: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            "agentic_forge"
        ):
            parts = node.module.split(".")
            if len(parts) == 1:
                mods.update(alias.name for alias in node.names)
            else:
                mods.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("agentic_forge."):
                    mods.add(alias.name.split(".")[1])
    return mods


def hook_reachable_modules() -> list[str]:
    """Every lib module some hook imports, transitively — the 3.9 contract's exact scope."""
    seen: set[str] = set()
    todo: set[str] = set()
    for hook in HOOKS.glob("*.py"):
        todo |= _lib_imports(hook)
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        src = LIB / "agentic_forge" / f"{mod}.py"
        if src.is_file():
            todo |= _lib_imports(src)
    return sorted(seen)


def check_compiles(failures: list[str]) -> int:
    n = 0
    for path in shipped_python():
        n += 1
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"compile: {path.relative_to(REPO)}: {exc.msg}")
    return n


def check_imports(failures: list[str]) -> list[str]:
    mods = hook_reachable_modules()
    sys.path.insert(0, str(LIB))
    for mod in mods:
        try:
            importlib.import_module(f"agentic_forge.{mod}")
        except Exception as exc:  # noqa: BLE001 — any import failure is the finding
            failures.append(f"import: agentic_forge.{mod}: {type(exc).__name__}: {exc}")
    return mods


def run_hook(hook: Path, payload: dict[str, object], cwd: Path, state: Path) -> str | None:
    """Run one hook; None when it behaved, else the reason."""
    env = dict(os.environ)
    env["AGENTIC_FORGE_STATE_HOME"] = str(state)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)
    body = dict(payload)
    body.setdefault("cwd", str(cwd))
    body.setdefault("session_id", "hook-smoke")
    try:
        done = subprocess.run(
            [sys.executable, str(hook)], input=json.dumps(body), capture_output=True, text=True,
            cwd=str(cwd), env=env, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "timed out after 60s"
    if done.returncode != 0:
        tail = " ".join((done.stderr or "").split())[-300:]
        return f"exit {done.returncode}: {tail}"
    out = done.stdout.strip()
    if out:
        try:
            json.loads(out)
        except json.JSONDecodeError:
            return f"stdout is neither empty nor JSON: {out[:120]!r}"
    return None


def check_hooks(failures: list[str]) -> list[str]:
    hooks = sorted(HOOKS.glob("*.py"))
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp) / "repo"
        cwd.mkdir()
        state = Path(tmp) / "state"
        for hook in hooks:
            payload = PAYLOADS.get(hook.name)
            if payload is None:
                failures.append(f"hook: {hook.name}: no smoke payload in dev/hook_smoke.py")
                continue
            problem = run_hook(hook, payload, cwd, state)
            if problem:
                failures.append(f"hook: {hook.name}: {problem}")
    return [h.name for h in hooks]


def main(argv: list[str]) -> int:
    failures: list[str] = []
    compiled = check_compiles(failures)
    mods = check_imports(failures)
    hooks = check_hooks(failures)
    version = ".".join(str(v) for v in sys.version_info[:3])
    print(
        f"hook smoke on Python {version}: {compiled} files compiled, "
        f"{len(mods)} hook-reachable modules imported ({' '.join(mods)}), "
        f"{len(hooks)} hooks run"
    )
    for line in failures:
        print(f"  FAIL {line}")
    print("hook smoke:", "OK" if not failures else f"{len(failures)} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
