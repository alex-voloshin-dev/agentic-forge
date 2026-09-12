from __future__ import annotations

import gzip
import json

from agentic_forge.observability import Digest, digest, parse_lines, render


def _line(**kw: object) -> str:
    return json.dumps(kw)


SAMPLE = [
    _line(tool="Bash", input="ls", session_id="s1"),
    _line(tool="Read", input="a.py", session_id="s1"),
    _line(tool="Bash", input="git status", session_id="s2"),
    "",  # blank skipped
    "{not json",  # malformed skipped
    "[1,2]",  # non-dict skipped
]


# --- parse_lines -----------------------------------------------------------------------


def test_parse_lines_skips_blank_malformed_and_nondict() -> None:
    recs = parse_lines(SAMPLE)
    assert len(recs) == 3
    assert all(isinstance(r, dict) for r in recs)


# --- digest ----------------------------------------------------------------------------


def test_digest_counts_tools_sessions_and_top() -> None:
    d = digest(SAMPLE)
    assert d.total == 3
    assert d.by_tool == {"Bash": 2, "Read": 1}  # descending by count
    assert d.sessions == 2
    assert d.top_tool == "Bash"


def test_digest_empty() -> None:
    d = digest([])
    assert d == Digest(
        total=0, by_tool={}, sessions=0, top_tool=None, errors=0, by_error_tool={}
    )


def test_digest_counts_errors_and_ranks_failing_tools() -> None:
    # ADR 0058: records carrying `error: true` are counted and ranked per tool by failure.
    lines = [
        _line(tool="Bash", input="a", error=True),
        _line(tool="Bash", input="b", error=True),
        _line(tool="Bash", input="c"),  # success — not counted
        _line(tool="Read", input="d", error=True),
    ]
    d = digest(lines)
    assert d.errors == 3
    assert d.by_error_tool == {"Bash": 2, "Read": 1}  # descending by failure count


def test_render_shows_failures_section_only_when_errors() -> None:
    clean = render(digest([_line(tool="Bash", input="x")]))
    assert "Failures:" not in clean
    failing = render(digest([_line(tool="Bash", input="x", error=True)]))
    assert "Failures: 1 tool call(s) recorded an error." in failing
    assert "Bash: 1" in failing


def test_digest_tie_break_is_alphabetical() -> None:
    lines = [_line(tool="Zed", input="x"), _line(tool="Ack", input="y")]
    d = digest(lines)
    assert list(d.by_tool) == ["Ack", "Zed"]  # 1 each -> alphabetical
    assert d.top_tool == "Ack"


def test_digest_record_without_tool_or_session() -> None:
    d = digest([_line(input="x")])  # no tool, no session_id
    assert d.total == 1 and d.by_tool == {"unknown": 1} and d.sessions == 0


# --- render ----------------------------------------------------------------------------


def test_render_empty() -> None:
    assert "no tool-use records" in render(digest([]))


def test_render_summary() -> None:
    out = render(digest(SAMPLE))
    assert "3 tool uses across 2 session(s)" in out
    assert "Bash: 2" in out and "Read: 1" in out


# --- rotate_audit (field fix: the log grew ~2.6 MB/week with no bound) ---


def _seed_audit(repo, lines):
    """Seed the audit log where the WRITER puts it (the state root, ADR 0072/0081) — rotation
    trims the file that is being appended to, not a legacy copy that no longer grows."""
    from agentic_forge import diagnostics

    path = diagnostics.state_file(repo, "audit.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_rotate_audit_noop_under_threshold(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    path = _seed_audit(tmp_path, ['{"tool": "Bash"}'] * 10)
    assert rotate_audit(tmp_path, max_bytes=10_000, keep_bytes=5_000) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 10


def test_rotate_audit_trims_to_whole_line_tail(tmp_path) -> None:
    import json as _json

    from agentic_forge.observability import rotate_audit

    lines = [_json.dumps({"tool": "Bash", "input": "{}", "n": i}) for i in range(200)]
    path = _seed_audit(tmp_path, lines)
    assert rotate_audit(tmp_path, max_bytes=1_000, keep_bytes=800) is True
    kept = path.read_text(encoding="utf-8").splitlines()
    assert 0 < len(kept) < 200
    first = _json.loads(kept[0])  # the kept window starts at a COMPLETE record
    assert first["tool"] == "Bash"
    assert _json.loads(kept[-1])["n"] == 199  # ...and ends with the newest record


def test_rotate_audit_missing_file_is_false(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    assert rotate_audit(tmp_path) is False


def test_rotate_audit_keep_window_larger_than_file_is_noop(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    path = _seed_audit(tmp_path, ['{"tool": "Bash"}'] * 50)
    size = path.stat().st_size
    # misuse guard: max_bytes below the size but keep_bytes above it — nothing sensible to trim
    assert rotate_audit(tmp_path, max_bytes=size - 1, keep_bytes=size + 100) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 50  # unchanged, not shrunk by 1


def test_rotate_audit_newline_aligned_window_keeps_all_records(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    lines = ["aaaa", "bbbb", "cccc"]
    path = _seed_audit(tmp_path, lines)  # 15 bytes: each line 5 with newline
    assert rotate_audit(tmp_path, max_bytes=1, keep_bytes=10) is True
    assert path.read_text(encoding="utf-8").splitlines() == ["bbbb", "cccc"]  # bbbb NOT dropped


def test_load_audit_reads_from_main_root_for_worktree(tmp_path) -> None:
    from agentic_forge.observability import AUDIT_PATH, load_audit

    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    log = main / AUDIT_PATH
    log.parent.mkdir(parents=True)
    log.write_text('{"tool": "Bash"}\n', encoding="utf-8")
    assert load_audit(wt) == ['{"tool": "Bash"}']  # reader agrees with the writer's home


# --- rotation archives rather than discards (ADR 0081) -----------------------


def _dated(n: int, day: int) -> list[str]:
    import json as _json

    return [
        _json.dumps({"tool": "Bash", "input": "{}", "ts": f"2026-09-{day:02d}T0{i % 10}:00:00"})
        for i in range(n)
    ]


def test_rotate_audit_archives_the_discarded_records(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    path = _seed_audit(tmp_path, _dated(400, 1) + _dated(400, 20))
    assert rotate_audit(tmp_path, max_bytes=1_000, keep_bytes=800) is True
    archives = sorted((path.parent / "archive").glob("audit-*.jsonl.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt", encoding="utf-8") as handle:
        recovered = handle.read().splitlines()
    assert recovered  # the oldest records survive the rotation, compressed
    assert len(recovered) + len(path.read_text(encoding="utf-8").splitlines()) == 800


def test_rotate_audit_prunes_old_archives(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    path = _seed_audit(tmp_path, _dated(400, 1))
    for _ in range(3):
        rotate_audit(tmp_path, max_bytes=1_000, keep_bytes=800, archives=2)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(_dated(400, 2)) + "\n")
    assert len(list((path.parent / "archive").glob("*.jsonl.gz"))) <= 2


def test_rotate_audit_can_still_discard(tmp_path) -> None:
    from agentic_forge.observability import rotate_audit

    path = _seed_audit(tmp_path, _dated(400, 1))
    assert rotate_audit(tmp_path, max_bytes=1_000, keep_bytes=800, archives=0) is True
    assert not (path.parent / "archive").exists()


def test_rotation_notice_speaks_in_days(tmp_path, monkeypatch) -> None:
    """Bytes tell an operator nothing about what they just lost."""
    import json as _json

    from agentic_forge import diagnostics
    from agentic_forge.observability import record_days, rotate_audit

    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    _seed_audit(tmp_path, _dated(400, 1) + _dated(400, 20))
    assert rotate_audit(tmp_path, max_bytes=1_000, keep_bytes=800) is True
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    event = _json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert "days of records" in event["message"] and "archived to" in event["message"]
    assert record_days(b'{"ts": "2026-09-01T00:00:00"}\n{"ts": "2026-09-11T00:00:00"}\n') == 10.0
    assert record_days(b"not json\n") is None
