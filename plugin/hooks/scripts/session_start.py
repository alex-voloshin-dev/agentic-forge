#!/usr/bin/env python3
"""SessionStart hook: inject the target repo's knowledge-vault map (ADR 0018).

Reads the hook payload on stdin (using ``cwd`` as the repo root), builds a compact map of the
project's knowledge vault via :func:`agentic_forge.vault.session_summary`, and emits it as
SessionStart ``additionalContext``, after the skill-routing note and any once-per-session notices
(a half-done state migration, a config file that had to be dropped). It **never blocks the
session**: any error exits 0 — recorded regardless of the diagnostics toggle and announced once —
because a knowledge injection must never break session startup.
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
# `skill-factory` (no by-hand path; a maintainer skill since ADR 0105) fired 1.000, `code-review` /
# `develop` fired 0.000. A skill's description makes it findable; nothing told the model that
# finding it is the point. This line does, in the one channel that reaches every session, and its
# whole cost is these two sentences. It used to add "*especially* when doing it directly looks
# straightforward", which a fleet reported fighting `develop`'s own small-change path and project
# rules like "subagents only when the work needs them": the skill sizes its process to the change,
# so the note says that instead of pushing the full process onto a one-line fix. The hook runs on
# every SessionStart source, compaction included; that re-injection is deliberate (it is what
# keeps the routing alive in a long session).
SKILL_ROUTING_NOTE = (
    "agentic-forge skills are WORKFLOWS, not reference material: each one runs a multi-step "
    "process (fan-out, review gates, handoff artifacts) that doing the task by hand skips. When a "
    "request matches an agentic-forge skill's description — reviewing a change, implementing a "
    "planned step, designing, planning, researching, cutting a release — invoke that skill rather "
    "than doing the work directly; the skill itself scales its process to the size of the change."
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


_CONFIG_MARKER = "settings:dropped-config"
_OUTSIDE_VAULT_MARKER = "knowledge:outside-repo"


def config_notice(cwd: str, resolved: settings.Settings, session_id: str | None) -> str:
    """The warnings for config ``resolve`` had to ignore — the FIRST time this session, then "".

    A malformed or schema-invalid ``config.json`` is ignored whole (`test_gate.skip`,
    `pr_watcher.enabled`, every key in it silently at its default), and the stderr line every hook
    printed on every tool call reached nobody. This is the one place a session can read it."""
    if not resolved.warnings:
        return ""
    if not diagnostics.once_per_session(cwd, _CONFIG_MARKER, session_id):
        return ""
    return "\n".join(resolved.warnings)


def outside_vault_notice(cwd: str, session_id: str | None) -> str:
    """Say once per session that a vault is not being read: without this, one kept elsewhere would
    just vanish from the session on upgrade (ADR 0102)."""
    notice = vault.outside_repo_notice(cwd)
    if notice and diagnostics.once_per_session(cwd, _OUTSIDE_VAULT_MARKER, session_id):
        return notice
    return ""


def main() -> int:
    cwd = "."
    session_id: str | None = None
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        # Once-per-session log rotation (size-bounded; never raises) — the natural place for it:
        # cheap here, and the per-event hooks stay pure appends. The diagnostics log gets the
        # audit log's bounds: every hook crash is recorded regardless of the toggle now, so it
        # can no longer be left to grow forever.
        limits = settings.resolve(cwd)
        root = diagnostics.main_repo_root(cwd)
        bounds = {
            "max_bytes": limits.logs_max_bytes,
            "keep_bytes": limits.logs_keep_bytes,
            "archives": limits.logs_archives,
        }
        observability.rotate_audit(root, **bounds)
        observability.rotate_diagnostics(root, **bounds)
        # Surface a half-done state migration ONCE per session: it is otherwise silent in
        # both directions — orphaned history and a resurrected in-repo directory (ADR 0080).
        # It used to go to stderr, which a SessionStart hook exiting 0 does not show anyone: the
        # field bundle that reported the orphan was collected two months after this notice
        # "fired". It now goes where a session can actually read it (ADR 0081). A dropped config
        # file is the same story and takes the same channel.
        notices = [
            diagnostics.legacy_state_notice(cwd),
            config_notice(cwd, limits, session_id),
            outside_vault_notice(cwd, session_id),
        ]
        notice = "\n\n".join(n for n in notices if n)
        # Separately: its failure must not throw away notices whose once-per-session marker has
        # just been spent, or a repo could hide warnings about itself (ADR 0102).
        context = ""
        try:
            context = build_context(cwd)
        except Exception as exc:
            crash = diagnostics.hook_crash(
                cwd, "session-start", exc, session_id=session_id, severity="minor", type_only=True
            )
            notice = "\n\n".join(n for n in (notice, crash.get("systemMessage", "")) if n)
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
        # crash (regardless of the diagnostics toggle) and say so, so a vault/injection bug isn't
        # silent (parity with the other hooks, ADR 0039).
        crash = diagnostics.hook_crash(
            cwd, "session-start", exc, session_id=session_id, severity="minor", type_only=True
        )
        if crash:
            print(json.dumps(crash))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
