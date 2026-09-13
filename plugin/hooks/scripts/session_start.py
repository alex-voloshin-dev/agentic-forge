#!/usr/bin/env python3
"""SessionStart hook: inject the target repo's knowledge-vault map (ADR 0018).

Reads the hook payload on stdin (using ``cwd`` as the repo root), builds a compact map of the
project's knowledge vault via :func:`agentic_forge.vault.session_summary`, and emits it as
SessionStart ``additionalContext``. It is a **no-op** (no output) when there is no vault, and it
**never blocks the session**: any error exits 0 silently — a knowledge injection must never break
session startup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The hook ships inside the plugin; add the plugin's lib to the path so we can import the shared,
# tested vault helpers. <plugin>/hooks/scripts/session_start.py -> <plugin>/lib
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, observability, settings, vault  # noqa: E402

# The measured problem (ADR 0088): a session reaches for the matching skill on ~0.35 of the
# requests squarely in its domain, and the rate falls the EASIER the task is to just do by hand —
# `skill-factory` (no by-hand path) fires 1.000, `code-review` / `develop` fire 0.000. A skill's
# description makes it findable; nothing told the model that finding it is the point. This line
# does, in the one channel that reaches every session, and its whole cost is these two sentences.
SKILL_ROUTING_NOTE = (
    "agentic-forge skills are WORKFLOWS, not reference material: each one runs a multi-step "
    "process (fan-out, review gates, handoff artifacts) that doing the task by hand skips. When a "
    "request matches an agentic-forge skill's description — reviewing a change, implementing a "
    "planned step, designing, planning, researching, cutting a release — invoke that skill rather "
    "than doing the work directly, *especially* when doing it directly looks straightforward."
)


def build_context(cwd: str) -> str:
    """The ``additionalContext`` to inject for repo ``cwd``.

    The routing note goes first, whether or not the repo has a knowledge vault, unless
    ``routing_note.enabled`` is off (``AGENTIC_FORGE_ROUTING_NOTE=0`` — the switch its own A/B uses,
    ADR 0091). The vault map follows when there is one."""
    summary = vault.session_summary(cwd)
    note = SKILL_ROUTING_NOTE if settings.resolve(cwd).routing_note_enabled else ""
    parts = [p for p in (note, summary) if p.strip()]
    return "\n\n".join(parts)


def main() -> int:
    cwd = "."
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        # Once-per-session audit-log rotation (size-bounded; never raises) — the natural place
        # for it: cheap here, and the per-tool-call logging hook stays a pure append.
        limits = settings.resolve(cwd)
        observability.rotate_audit(
            diagnostics.main_repo_root(cwd),
            max_bytes=limits.logs_max_bytes,
            keep_bytes=limits.logs_keep_bytes,
            archives=limits.logs_archives,
        )
        # Surface a half-done state migration ONCE per session: it is otherwise silent in
        # both directions — orphaned history and a resurrected in-repo directory (ADR 0080).
        # It used to go to stderr, which a SessionStart hook exiting 0 does not show anyone: the
        # field bundle that reported the orphan was collected two months after this notice
        # "fired". It now goes where a session can actually read it (ADR 0081).
        notice = diagnostics.legacy_state_notice(cwd)
        context = build_context(cwd)
        if notice:
            context = f"{notice}\n\n{context}" if context.strip() else notice
        if context.strip():
            output: dict[str, object] = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
            if notice:
                output["systemMessage"] = notice  # shown to the operator, not just to the model
            print(json.dumps(output))
    except Exception as exc:
        # A knowledge injection must never block session start — fail open (exit 0), but record the
        # crash so a vault/injection bug isn't silent (parity with the other hooks, ADR 0039).
        diagnostics.emit(
            cwd, kind="error", component="session-start",
            message=f"{type(exc).__name__}: {exc}", severity="minor",
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
