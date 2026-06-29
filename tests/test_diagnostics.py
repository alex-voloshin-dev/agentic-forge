"""Tests for the self-diagnostics channel (ADR 0039)."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_forge import diagnostics

_ON = {"AGENTIC_FORGE_DIAGNOSTICS": "1"}
_OFF: dict[str, str] = {}
_SECRET = "ghp_aaaaaaaaaaaaaaaaaaaaaaaa"  # a GitHub-token shape redact_secrets blanks


# --- enabled flag ------------------------------------------------------------


def test_enabled_recognises_truthy_values() -> None:
    for v in ("1", "true", "YES", "on"):
        assert diagnostics.enabled({"AGENTIC_FORGE_DIAGNOSTICS": v})
    for v in ("", "0", "false", "no"):
        assert not diagnostics.enabled({"AGENTIC_FORGE_DIAGNOSTICS": v})
    assert not diagnostics.enabled({})  # absent -> off by default


# --- signature ---------------------------------------------------------------


def test_signature_normalises_volatile_bits() -> None:
    a = diagnostics.signature("h", "error", "failed at /tmp/af-eval-123/x.py line 5")
    b = diagnostics.signature("h", "error", "failed at /tmp/af-eval-999/y.py line 87")
    assert a == b  # paths + numbers normalised -> one signature for the same problem
    assert diagnostics.signature("h", "error", "x") != diagnostics.signature("h", "block", "x")


# --- make_event --------------------------------------------------------------


def test_make_event_redacts_secrets_in_message_and_context() -> None:
    ev = diagnostics.make_event(
        ts="2026-06-28T00:00:00Z",
        kind="error",
        component="lib:release",
        message=f"crash with token {_SECRET}",
        context={"cmd": f"deploy {_SECRET}"},
    )
    assert _SECRET not in ev["message"] and "[REDACTED]" in ev["message"]
    assert _SECRET not in ev["context"]["cmd"]


def test_make_event_unknown_kind_falls_back_to_anomaly() -> None:
    ev = diagnostics.make_event(ts="t", kind="weird", component="c", message="m")
    assert ev["kind"] == "anomaly"


def test_make_event_optional_fields() -> None:
    bare = diagnostics.make_event(ts="t", kind="block", component="c", message="m")
    assert "context" not in bare and "session_id" not in bare
    full = diagnostics.make_event(
        ts="t", kind="block", component="c", message="m", session_id="s1", context={"k": "v"}
    )
    assert full["session_id"] == "s1" and full["context"] == {"k": "v"}


# --- record_event (I/O seam) -------------------------------------------------


def _event() -> dict[str, object]:
    return diagnostics.make_event(ts="t", kind="error", component="c", message="boom")


def test_record_event_disabled_writes_nothing(tmp_path: Path) -> None:
    assert diagnostics.record_event(tmp_path, _event(), env=_OFF) is None
    assert not (tmp_path / diagnostics.DIAGNOSTICS_PATH).exists()


def test_record_event_enabled_appends(tmp_path: Path) -> None:
    path = diagnostics.record_event(tmp_path, _event(), env=_ON)
    assert path is not None and path.is_file()
    diagnostics.record_event(tmp_path, _event(), env=_ON)
    assert len(path.read_text().splitlines()) == 2  # appends, one JSON line each


def test_record_event_io_error_returns_none(tmp_path: Path) -> None:
    blocker = tmp_path / "afile"
    blocker.write_text("not a dir")  # repo path is a FILE -> mkdir under it fails
    assert diagnostics.record_event(blocker, _event(), env=_ON) is None


# --- emit (the emitter entry point) ------------------------------------------


def test_emit_disabled_is_a_noop(tmp_path: Path) -> None:
    assert diagnostics.emit(tmp_path, kind="error", component="c", message="m", env=_OFF) is False
    assert not (tmp_path / diagnostics.DIAGNOSTICS_PATH).exists()


def test_emit_writes_with_fixed_now(tmp_path: Path) -> None:
    ok = diagnostics.emit(
        tmp_path, kind="block", component="security-hook", message="blocked rm",
        severity="major", now="2026-06-28T12:00:00Z", env=_ON,
    )
    assert ok
    rec = json.loads((tmp_path / diagnostics.DIAGNOSTICS_PATH).read_text().splitlines()[0])
    assert rec["ts"] == "2026-06-28T12:00:00Z" and rec["kind"] == "block"


def test_emit_stamps_now_when_omitted(tmp_path: Path) -> None:
    assert diagnostics.emit(tmp_path, kind="error", component="c", message="m", env=_ON)
    rec = json.loads((tmp_path / diagnostics.DIAGNOSTICS_PATH).read_text().splitlines()[0])
    assert rec["ts"]  # a real timestamp was stamped


def test_emit_never_raises_on_internal_error(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(**kw: object) -> dict[str, object]:
        raise RuntimeError("internal")

    monkeypatch.setattr(diagnostics, "make_event", boom)  # force the build to fail
    assert diagnostics.emit(tmp_path, kind="error", component="c", message="m", env=_ON) is False


# --- parse_lines / digest / render -------------------------------------------


def test_parse_lines_skips_blank_and_malformed() -> None:
    recs = diagnostics.parse_lines(['{"a":1}', "", "  ", "not json", "[1,2]"])
    assert recs == [{"a": 1}]  # only the valid object


def _line(**kw: object) -> str:
    return json.dumps(diagnostics.make_event(**kw))  # type: ignore[arg-type]


def test_digest_groups_ranks_and_counts() -> None:
    lines = [
        _line(ts="1", kind="block", component="security-hook", message="blocked rm at line 5"),
        _line(ts="2", kind="block", component="security-hook", message="blocked rm at line 9"),
        _line(ts="3", kind="block", component="security-hook", message="blocked rm at line 40"),
        _line(ts="4", kind="error", component="commit-gate", message="gate failed"),
    ]
    d = diagnostics.digest(lines)
    assert d.total == 4
    assert d.by_kind == {"block": 3, "error": 1}
    assert d.by_component == {"security-hook": 3, "commit-gate": 1}
    assert d.problems[0].count == 3 and d.problems[0].component == "security-hook"  # ranked first
    assert d.problems[0].first_ts == "1" and d.problems[0].last_ts == "3"


def test_digest_worst_severity_and_sessions() -> None:
    def boom(ts: str, sev: str, sess: str) -> str:
        return _line(
            ts=ts, kind="error", component="c", message="boom", severity=sev, session_id=sess
        )

    d = diagnostics.digest(
        [boom("1", "minor", "s1"), boom("2", "blocker", "s1"), boom("3", "major", "s2")]
    )
    assert d.problems[0].severity == "blocker"  # worst of the group
    assert d.sessions == 2


def test_render_empty_and_populated() -> None:
    assert "no events" in diagnostics.render(diagnostics.digest([]))
    one = [_line(ts="1", kind="error", component="c", message="boom")]
    out = diagnostics.render(diagnostics.digest(one))
    assert "Top problems:" in out and "boom" in out


# --- load --------------------------------------------------------------------


def test_load_absent_and_window(tmp_path: Path) -> None:
    assert diagnostics.load(tmp_path) == []  # no file yet
    for i in range(5):
        diagnostics.record_event(tmp_path, diagnostics.make_event(
            ts=str(i), kind="error", component="c", message="m"), env=_ON)
    assert len(diagnostics.load(tmp_path)) == 5
    assert len(diagnostics.load(tmp_path, max_lines=2)) == 2  # bounded window
