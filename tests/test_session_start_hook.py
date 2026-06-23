from __future__ import annotations

import io
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "hooks" / "scripts"))

import session_start  # noqa: E402

from agentic_forge import vault  # noqa: E402


def test_build_context_no_vault(tmp_path: Path) -> None:
    assert session_start.build_context(str(tmp_path)) == ""


def test_build_context_with_vault(tmp_path: Path) -> None:
    vault.add_note(tmp_path, "central", "Central idea", "the hub")
    ctx = session_start.build_context(str(tmp_path))
    assert "Project knowledge" in ctx and "[[central]]" in ctx


def test_main_emits_injection_json(tmp_path: Path, monkeypatch, capsys) -> None:
    vault.add_note(tmp_path, "n", "N", "body")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert session_start.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Project knowledge" in data["hookSpecificOutput"]["additionalContext"]


def test_main_no_vault_emits_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert session_start.main() == 0
    assert capsys.readouterr().out.strip() == ""  # no vault -> no injection


def test_main_bad_stdin_is_safe(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert session_start.main() == 0  # never blocks the session
    assert capsys.readouterr().out.strip() == ""


def test_hooks_json_valid_session_start() -> None:
    hooks = json.loads((_REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = hooks["hooks"]["SessionStart"]
    handler = entries[0]["hooks"][0]
    assert handler["type"] == "command"
    assert "session_start.py" in handler["command"]
    assert "CLAUDE_PLUGIN_ROOT" in handler["command"]  # plugin-relative path
