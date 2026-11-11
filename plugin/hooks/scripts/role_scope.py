#!/usr/bin/env python3
"""Role-scope hook (PreToolUse): hold the read-only roles to their tool scope (ADR 0106).

A tool call made inside one of the plugin's read-only subagents (``reviewer``,
``security-engineer``, ``grader``, ``architect``) carries its ``agent_type``; what to answer is
``role_scope.respond``'s, pure and tested:

- a refusal is the PreToolUse ``deny`` decision in ``hookSpecificOutput``, with exit 0; a hook's
  ``deny`` applies in every permission mode, ``bypassPermissions`` included, and its reason
  reaches the model;
- an allowed git call is answered with ``allow`` and an ``updatedInput`` holding the command
  rebuilt in its hardened form, so what runs is exactly what was checked;
- anything else gets exit 0 and no output.

Callers that are not these roles, the main session and the plugin's other roles included, exit
before the library is imported: the matcher reaches nearly every tool call, so they pay one Python
start and a JSON parse.

**Fails closed for a held role.** A payload that does not parse cannot name a role, so it exits 0
with no output, as every hook here does (ADR 0019/0039). Once the payload names a held role, any
error (an import, a path that cannot be encoded, a bug) refuses the call and records the crash: a
boundary that opens on an error is no boundary against content written to cause one. A hook that
cannot start at all still fails open, silently, which is why this file and what it imports stay on
Python 3.9.
"""

from __future__ import annotations

import json
import sys

# Only `json` and `sys` load before the early exit: every tool call but Read, Grep and Glob reaches
# this hook, and `pathlib` and `typing` would add about 9 ms to each (ADR 0106 has the figures).

_COMPONENT = "role-scope-hook"
# The held roles, known here so every other caller exits before an import, and so a failed import
# still refuses; a test keeps this equal to role_scope.ROLE_TOOLS.
HELD_ROLES = frozenset({
    "agentic-forge:reviewer", "agentic-forge:security-engineer", "agentic-forge:grader",
    "agentic-forge:architect",
})


def _use_lib() -> None:
    """Put the plugin's ``lib/`` on the import path (``hooks/scripts/<this>`` -> ``lib``)."""
    import os

    here = os.path.dirname(os.path.realpath(__file__))
    lib = os.path.join(os.path.dirname(os.path.dirname(here)), "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)


def _fail_closed(payload: dict[str, object], exc: BaseException) -> None:
    """Refuse the call (printed first, so a failing record cannot cost the refusal), then record
    the crash and add its once-per-session notice."""
    role = str(payload.get("agent_type")).split(":", 1)[-1]
    reason = (
        f"agentic-forge role scope: this call could not be checked ({type(exc).__name__}), so it "
        f"is refused for the {role} role. Tests, linters and other tools are run by the "
        "orchestrating skill."
    )
    out: dict[str, object] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    try:
        from agentic_forge import diagnostics

        session_id = payload.get("session_id")
        crash = diagnostics.hook_crash(
            str(payload.get("cwd") or "."), _COMPONENT, exc,
            session_id=session_id if isinstance(session_id, str) else None,
            type_only=True, failed_closed=True,
        )
        out.update(crash)
    except Exception:  # the refusal stands without its record
        pass
    print(json.dumps(out))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # unparseable input names no role: fail open, silently
        return 0
    if not isinstance(payload, dict):
        return 0
    agent_type = payload.get("agent_type")
    if not isinstance(agent_type, str) or agent_type not in HELD_ROLES:
        return 0  # not a held role (a list or dict cannot even be looked up): exit, no import
    try:
        _use_lib()
        from agentic_forge import role_scope

        decision, out = role_scope.respond(payload)
    except Exception as exc:
        _fail_closed(payload, exc)
        return 0
    if out is None:
        return 0
    print(json.dumps(out))
    if decision.block:
        _record_block(payload, decision.message, decision.rule, decision.evidence)
    return 0


def _record_block(payload: dict[str, object], message: str, rule: str, evidence: str) -> None:
    """Record a refusal when diagnostics are on. The decision is already printed; nothing here may
    turn it into a failing exit, which would make Claude Code ignore it."""
    try:
        from agentic_forge import diagnostics

        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        diagnostics.emit(
            cwd, kind="block", component=_COMPONENT, message=message, severity="major",
            context={
                "agent_type": payload.get("agent_type"),
                "tool": str(payload.get("tool_name")),
                "rule": rule,
                "evidence": evidence,
            },
            session_id=session_id if isinstance(session_id, str) else None,
        )
    except Exception:  # the refusal stands without its record
        pass


if __name__ == "__main__":
    raise SystemExit(main())
