from __future__ import annotations

import io
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "hooks" / "scripts"))

import session_start  # noqa: E402

from agentic_forge import diagnostics, vault  # noqa: E402


def test_build_context_is_the_routing_note_when_there_is_no_vault(tmp_path: Path) -> None:
    """The routing note is unconditional (ADR 0088): a session with no vault still needs to be
    told that skills are workflows to invoke, which is the whole intervention."""
    ctx = session_start.build_context(str(tmp_path))
    assert ctx == session_start.SKILL_ROUTING_NOTE
    assert "invoke that skill" in ctx


def test_build_context_with_vault(tmp_path: Path) -> None:
    vault.add_note(tmp_path, "central", "Central idea", "the hub")
    ctx = session_start.build_context(str(tmp_path))
    assert "Project knowledge" in ctx and "[[central]]" in ctx
    assert ctx.startswith(session_start.SKILL_ROUTING_NOTE)  # note first, then the vault map


def test_main_emits_injection_json(tmp_path: Path, monkeypatch, capsys) -> None:
    vault.add_note(tmp_path, "n", "N", "body")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert session_start.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Project knowledge" in data["hookSpecificOutput"]["additionalContext"]


def test_main_injects_the_routing_note_without_a_vault(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert session_start.main() == 0
    data = json.loads(capsys.readouterr().out)
    injected = data["hookSpecificOutput"]["additionalContext"]
    assert injected == session_start.SKILL_ROUTING_NOTE  # no vault, but the note still lands


def test_main_bad_stdin_is_safe(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert session_start.main() == 0  # never blocks the session
    assert capsys.readouterr().out.strip() == ""


def test_main_records_diagnostics_on_error(tmp_path: Path, monkeypatch, capsys) -> None:
    # A crash inside the hook must still fail open (exit 0) but be recorded, not silent (ADR 0039)
    # — WITHOUT the diagnostics toggle (off on a default install), and said to the operator.
    monkeypatch.delenv("AGENTIC_FORGE_DIAGNOSTICS", raising=False)

    def _boom(_cwd: str) -> str:
        raise RuntimeError("vault exploded")

    monkeypatch.setattr(session_start, "build_context", _boom)
    payload = {"cwd": str(tmp_path), "session_id": "s-boom"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert session_start.main() == 0  # never blocks the session
    out = json.loads(capsys.readouterr().out)
    assert "session-start hook crashed: RuntimeError: vault exploded" in out["systemMessage"]

    events = [json.loads(line) for line in diagnostics.load(tmp_path)]
    assert any(e["component"] == "session-start" and e["kind"] == "error" for e in events)


def test_dropped_config_is_announced_once_per_session(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A schema-invalid config is dropped WHOLE — `test_gate.skip`, `pr_watcher.enabled`, all of it
    silently at defaults — and the stderr line every hook printed reached nobody. Session start is
    the one place a session can read it, once."""
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir()
    (cfg / "config.json").write_text('{"review": {"passes": 0}}', encoding="utf-8")  # min is 1
    payload = {"cwd": str(tmp_path), "session_id": "s-cfg"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert session_start.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "ignoring invalid" in out["systemMessage"] and "config.json" in out["systemMessage"]
    assert "ignoring invalid" in out["hookSpecificOutput"]["additionalContext"]

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))  # same session
    assert session_start.main() == 0
    again = json.loads(capsys.readouterr().out)
    assert "systemMessage" not in again
    assert "ignoring" not in again["hookSpecificOutput"]["additionalContext"]

    payload["session_id"] = "s-cfg-2"  # a new session hears it again
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert session_start.main() == 0
    assert "ignoring invalid" in json.loads(capsys.readouterr().out)["systemMessage"]


def test_session_start_rotates_the_diagnostics_log(tmp_path: Path, monkeypatch, capsys) -> None:
    """The diagnostics log was appended per event and never rotated (the audit log is). Same
    bounds (`logs.*`), same archive shape, from the same place."""
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir()
    (cfg / "config.json").write_text(
        '{"logs": {"max_bytes": 1000, "keep_bytes": 800}}', encoding="utf-8"
    )
    log = diagnostics.state_file(tmp_path, diagnostics.DIAGNOSTICS_FILE)
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": "2026-09-01T00:00:00", "kind": "error", "n": i}) for i in range(200)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = log.stat().st_size
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert session_start.main() == 0
    capsys.readouterr()
    assert log.stat().st_size < before
    assert list((log.parent / "archive").glob("diagnostics-*.jsonl.gz"))
    last = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert last["component"] == "diagnostics-rotation"  # the trim is recorded, in the trimmed log


def test_hooks_json_valid_session_start() -> None:
    hooks = json.loads((_REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = hooks["hooks"]["SessionStart"]
    handler = entries[0]["hooks"][0]
    assert handler["type"] == "command"
    assert "session_start.py" in handler["command"]
    assert "CLAUDE_PLUGIN_ROOT" in handler["command"]  # plugin-relative path


def test_routing_note_has_an_off_switch(tmp_path: Path, monkeypatch) -> None:
    """ADR 0091: the note's contribution is measured with it OFF; the switch is the same shape as
    every other hook's."""
    monkeypatch.setenv("AGENTIC_FORGE_ROUTING_NOTE", "0")
    assert session_start.build_context(str(tmp_path)) == ""
    vault.add_note(tmp_path, "central", "Central idea", "the hub")
    ctx = session_start.build_context(str(tmp_path))
    assert "Project knowledge" in ctx and session_start.SKILL_ROUTING_NOTE not in ctx
