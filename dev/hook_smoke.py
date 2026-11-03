#!/usr/bin/env python3
"""Smoke-run every hook under the interpreter this script runs on (ADR 0094).

Hooks run under the user's bare ``python3`` — on a stock macOS that is CPython 3.9.6 — while the
repo's own tooling requires 3.11. A 3.10+ construct on a hook-reachable path fails to even parse
there, and a hook that fails to start fails OPEN: the guardrail is silently gone and nothing says
so. CI runs this file under 3.9 (the ``hooks-py39`` job in ``ci.yml``); it needs nothing installed.

Four checks, stdlib only:

1. every shipped ``.py`` (hooks, lib, bin, skill scripts) byte-compiles under this interpreter;
2. every lib module a hook or a skill's command imports — transitively — imports;
3. every hook runs to exit 0 on a minimal payload for its event and prints nothing or JSON;
4. ``bin/af.py``, what skills run on this same interpreter (ADR 0104), answers, as a real process.

A hook script with no payload in :data:`PAYLOADS` is a failure too: a new hook must be smoked.
State goes to a temp directory (``AGENTIC_FORGE_STATE_HOME``), never to the operator's, and so does
the hooks' scratch (``TMPDIR``): a counter in the shared temp directory, such as the budget hook's,
would otherwise grow across runs until the hook blocks.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
LIB = PLUGIN / "lib"
HOOKS = PLUGIN / "hooks" / "scripts"
# What a skill body runs, on the same bare `python3` as a hook (ADR 0104).
SKILL_COMMANDS = (PLUGIN / "bin" / "af.py", PLUGIN / "bin" / "external_review.py")

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
    """Every lib module some hook or skill command imports, transitively — the 3.9 contract's exact
    scope."""
    seen: set[str] = set()
    todo: set[str] = set()
    for hook in (*HOOKS.glob("*.py"), *SKILL_COMMANDS):
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


def run_hook(
    hook: Path, payload: dict[str, object], cwd: Path, state: Path, scratch: Path,
    extra_env: dict[str, str] | None = None,
) -> str | None:
    """Run one hook; None when it behaved, else the reason."""
    env = {**os.environ, **(extra_env or {})}
    env["AGENTIC_FORGE_STATE_HOME"] = str(state)
    env["TMPDIR"] = str(scratch)  # `tempfile.gettempdir` reads it, so each run starts from nothing
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
        scratch = Path(tmp) / "tmp"
        scratch.mkdir()
        for hook in hooks:
            payload = PAYLOADS.get(hook.name)
            if payload is None:
                failures.append(f"hook: {hook.name}: no smoke payload in dev/hook_smoke.py")
                continue
            problem = run_hook(hook, payload, cwd, state, scratch)
            if problem:
                failures.append(f"hook: {hook.name}: {problem}")
    return [h.name for h in hooks]


def check_narrowed_commit(failures: list[str], hook_env: dict[str, str] | None = None) -> str:
    """The commit gate's own path, which the `git status` payload above never reaches: a real repo,
    an empty commit from a package, and a stand-in ruff that fails if it runs at all (ADR 0101).

    A slim image has no git. Saying so is the honest result there; on CI it is a failure, since a
    floor test that cannot run proves nothing (ADR 0082)."""
    if not shutil.which("git"):
        if os.environ.get("CI"):
            failures.append("narrowed commit: no git on CI")
        return "narrowed commit NOT run: no git here"
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        package = base / "repo" / "pkg"
        package.mkdir(parents=True)
        (package / "pyproject.toml").write_text("[project]\nname = 'smoke'\n", encoding="utf-8")
        ruff_ran = base / "ruff-ran"
        tools = base / "bin"
        tools.mkdir()
        (tools / "ruff").write_text(f'#!/bin/sh\ntouch "{ruff_ran}"\nexit 1\n', encoding="utf-8")
        (tools / "ruff").chmod(0o755)
        (base / "tmp").mkdir()
        identity = ("-c", "user.name=smoke", "-c", "user.email=smoke@example.invalid")
        for args in (("init", "-q"), ("add", "."), (*identity, "commit", "-qm", "init")):
            subprocess.run(["git", *args], cwd=str(package.parent), check=True, capture_output=True)
        payload: dict[str, object] = {
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "git commit --allow-empty -m empty"},
        }
        env = {"PATH": f"{tools}{os.pathsep}{os.environ.get('PATH', '')}", **(hook_env or {})}
        problem = run_hook(
            HOOKS / "commit_gate.py", payload, package, base / "state", base / "tmp", env
        )
        if problem or ruff_ran.exists():
            failures.append(f"narrowed commit: {problem or 'ruff ran on an empty commit'}")
    return "narrowed commit run"


def check_commands(failures: list[str]) -> int:
    """Run ``af.py`` as a skill does: ``python3 -E``, a script, from a temp directory."""
    calls = (["--help"], ["incident-classify", "--outage"], ["vault-recall", "--query", "x"],
             ["review-decision", "--verdict", "approve", "--iteration", "1", "--gate-green", "yes"])
    with tempfile.TemporaryDirectory() as tmp:
        for args in calls:
            done = subprocess.run(
                [sys.executable, "-E", str(SKILL_COMMANDS[0]), *args], capture_output=True,
                text=True, cwd=tmp, timeout=60, check=False,
            )
            if done.returncode != 0:
                tail = " ".join(done.stderr.split())[-300:]
                failures.append(f"af.py {args[0]}: exit {done.returncode}: {tail}")
    return len(calls)


def main(argv: list[str]) -> int:
    failures: list[str] = []
    compiled = check_compiles(failures)
    mods = check_imports(failures)
    hooks = check_hooks(failures)
    narrowed = check_narrowed_commit(failures)
    commands = check_commands(failures)
    version = ".".join(str(v) for v in sys.version_info[:3])
    print(
        f"hook smoke on Python {version}: {compiled} files compiled, "
        f"{len(mods)} hook-reachable modules imported ({' '.join(mods)}), "
        f"{len(hooks)} hooks run, {narrowed}, "
        f"{commands} af.py calls"
    )
    for line in failures:
        print(f"  FAIL {line}")
    print("hook smoke:", "OK" if not failures else f"{len(failures)} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
