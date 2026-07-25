from __future__ import annotations

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
    log = repo / ".agentic-forge"
    log.mkdir(parents=True, exist_ok=True)
    (log / "audit.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log / "audit.jsonl"


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
