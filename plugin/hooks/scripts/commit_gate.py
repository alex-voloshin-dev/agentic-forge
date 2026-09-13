#!/usr/bin/env python3
"""Test-gate hook (PreToolUse): block a git commit/push when the fast gate fails (ADR 0019).

On a `git commit`/`git push` Bash command, run the repo's fast gate (`dev/validate.py` if present,
else the detected stack's lint) and exit 2 (block) if it fails. Skippable via the `test_gate.skip`
setting (or AGENTIC_FORGE_SKIP_TEST_GATE — ADR 0041). Fails OPEN on any infrastructure error
(missing tool, etc.) — only a genuine gate failure blocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, guardrails, settings  # noqa: E402

# A fail-open is the RIGHT default — a broken toolchain must not block a commit (ADR 0058/0059) —
# but until 2026.9.1 it was announced only to the diagnostics log, which nobody reads. A field
# bundle: 69 fail-opens over two months, 50 of them one missing `ruff`, and the operator never knew
# the gate had stopped running. The notice below says it once per session (ADR 0081).
_FAIL_OPEN_MARKER = "commit-gate:fail-open"


_GATE_TIMEOUT = 110  # seconds; the hook itself is capped at 120 in hooks.json
_TAIL_CHARS = 400  # of a hung gate's output kept in the record (each context value caps at 500)


def _tail(raw: object) -> str:
    """The last ``_TAIL_CHARS`` of a captured stream. ``TimeoutExpired`` carries the partial output
    as BYTES on POSIX even in text mode; only ``str(exc)`` was recorded, so nothing said which test
    hung."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    return text.strip()[-_TAIL_CHARS:]


def fail_open_notice(gate: list[str], detail: str) -> str:
    """The one line an operator needs when the gate could not run: what did not run, and what to
    do about it. A timeout gets its own remedy — installing something is not the answer when the
    lint ran fine and merely took too long (a field case: `npm run lint` on a large Next.js app,
    ADR 0082)."""
    head = (
        f"agentic-forge test-gate: `{' '.join(gate)}` could not run — this commit was NOT gated "
    )
    if "TimeoutExpired" in detail:
        return (
            f"{head}(timed out after {_GATE_TIMEOUT}s). The gate is capped by the hook's own "
            f"{_GATE_TIMEOUT + 10}s budget, so a slow whole-repo lint can never fit: scope it to "
            "the staged files (lint-staged, `eslint --cache`), or set `test_gate.skip: true` in "
            ".agentic-forge/config.json and gate in CI instead."
        )
    return (
        f"{head}({detail}). Install the tool (or keep it in the project's .venv/node_modules), or "
        "set `test_gate.skip: true` in .agentic-forge/config.json to stop trying."
    )


def _announce(cwd: str, gate: list[str], detail: str, session_id: str | None) -> None:
    """Print the fail-open notice to the operator, once per session. Hook stdout is JSON, so the
    line goes in `systemMessage` — stderr from a hook that exits 0 reaches nobody."""
    if diagnostics.once_per_session(cwd, _FAIL_OPEN_MARKER, session_id):
        print(json.dumps({"systemMessage": fail_open_notice(gate, detail)}))


def gate_decision(payload: dict[str, Any]) -> guardrails.Decision:
    if payload.get("tool_name") != "Bash":
        return guardrails.ALLOW
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not guardrails.is_commit_or_push(command):
        return guardrails.ALLOW
    cwd = str(payload.get("cwd") or ".")
    # resolve config only once we know it's a commit/push (keep the cheap filters first)
    if settings.resolve(cwd).skip_test_gate:
        return guardrails.ALLOW
    gate = guardrails.choose_gate(cwd)
    if not gate:
        return guardrails.ALLOW
    # Resolve the tool the way the project does (project-local bins first) and hand the gate a PATH
    # that includes them, so a package script's own linter resolves too (ADR 0081).
    gate = guardrails.resolve_gate(gate, cwd)
    try:
        result = subprocess.run(
            gate,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GATE_TIMEOUT,
            env=guardrails.gate_env(cwd),
        )
    except Exception as exc:
        # Infra error (tool missing, timeout) -> don't block, but RECORD the fail-open: a gate
        # that silently never runs is indistinguishable from a healthy one in the diagnostics
        # log (a real 7-day bundle had zero events — this makes that reading trustworthy).
        context: dict[str, Any] = {"gate": " ".join(gate)}
        for stream in ("stdout", "stderr"):  # a timeout's partial output: WHICH test hung
            tail = _tail(getattr(exc, stream, None))
            if tail:
                context[stream] = tail
        diagnostics.emit(
            cwd, kind="anomaly", component="commit-gate",
            message=f"gate fail-open (infra): {type(exc).__name__}: {exc}",
            severity="minor", context=context,
            session_id=payload.get("session_id"),
        )
        _announce(cwd, gate, f"{type(exc).__name__}: {exc}", payload.get("session_id"))
        return guardrails.ALLOW
    if result.returncode != 0:
        # Join with a newline so a signature can't be spuriously formed or destroyed across the
        # stdout/stderr boundary (ADR 0059).
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        tail = combined.strip()[-500:]
        unrunnable = (
            guardrails.gate_unrunnable(combined)
            or result.returncode in guardrails.GATE_UNRUNNABLE_EXIT_CODES
        )
        if unrunnable:
            # The gate couldn't RUN (missing lint script / uninstalled linter / shell exit 127/126)
            # — environment breakage, not a code-quality failure. Fail OPEN (don't block a commit
            # for it), but record the downgrade so it's auditable (ADR 0058/0059).
            diagnostics.emit(
                cwd, kind="anomaly", component="commit-gate",
                message=f"gate unrunnable (fail-open): (`{' '.join(gate)}`)\n{tail}",
                severity="minor", context={"gate": " ".join(gate)},
                session_id=payload.get("session_id"),
            )
            _announce(cwd, gate, tail.splitlines()[-1] if tail else "no output",
                      payload.get("session_id"))
            return guardrails.ALLOW
        return guardrails.Decision(True, f"blocked: gate failed (`{' '.join(gate)}`)\n{tail}")
    return guardrails.ALLOW


def main() -> int:
    cwd = "."
    session_id: str | None = None
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        decision = gate_decision(payload)
    except Exception as exc:  # fail open, but record + announce the hook crash (ADR 0039)
        crash = diagnostics.hook_crash(cwd, "commit-gate", exc, session_id=session_id)
        if crash:
            print(json.dumps(crash))
        return 0
    if decision.block:
        print(f"agentic-forge test-gate {decision.message}", file=sys.stderr)
        diagnostics.emit(
            str(payload.get("cwd") or "."), kind="block", component="commit-gate",
            message=decision.message, severity="major", session_id=payload.get("session_id"),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
