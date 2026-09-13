#!/usr/bin/env python3
"""Pre-router hook (UserPromptSubmit): name the clearly-matching skill in the prompt's context.

The deterministic classifier in :mod:`agentic_forge.pre_router` scores the prompt against every
skill's own trigger examples and, only on a clear win, emits one line of ``additionalContext``
naming that skill (ADR 0089). It suggests; it never invokes. It fails OPEN on any error — a
routing hint must never cost a prompt — and records the crash (ADR 0039). Off with
``pre_router.enabled: false`` or ``AGENTIC_FORGE_PRE_ROUTER=0``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))

from agentic_forge import diagnostics, pre_router, settings  # noqa: E402


def decide(payload: dict[str, Any], plugin_dir: Path = _PLUGIN_ROOT) -> str:
    """The context line for this prompt, or "" (no clear match, disabled, or not a prompt)."""
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return ""
    cwd = str(payload.get("cwd") or ".")
    if not settings.resolve(cwd).pre_router_enabled:
        return ""
    index = pre_router.build_index(plugin_dir)
    if not index.skills:
        # Without PyYAML every SKILL.md fails to parse, the index is empty, and the hook never
        # suggests — and never said why. One anomaly names the cause; the prompt goes on unhinted.
        why = index.skipped[0] if index.skipped else f"no skills under {plugin_dir / 'skills'}"
        diagnostics.emit(
            cwd, kind="anomaly", component="pre-router",
            message=f"pre-router index is empty ({len(index.skipped)} skill(s) skipped): {why}",
            severity="minor", session_id=payload.get("session_id"),
        )
        return ""
    suggestion = pre_router.suggest(prompt, index)
    return pre_router.render_context(suggestion, index.namespace) if suggestion else ""


def main() -> int:
    cwd = "."
    session_id: str | None = None
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        context = decide(payload)
        if context:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": context,
                        }
                    }
                )
            )
    except Exception as exc:  # fail open, but record + announce the hook crash (ADR 0039)
        crash = diagnostics.hook_crash(
            cwd, "pre-router", exc, session_id=session_id, severity="minor"
        )
        if crash:
            print(json.dumps(crash))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
