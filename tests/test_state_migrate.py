"""Tests for the legacy-state migration CLI (ADR 0080).

The failure this exists for is silent in **both directions at once**: a hand migration into a
guessed directory name orphans the history *and* keeps the in-repo directory alive, because reads
fall back to the legacy path when the resolved root has no file. Field-reported after it happened
to a real user with 16,676 records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "lib"))
sys.path.insert(0, str(_REPO / "plugin" / "bin"))

import state_migrate  # noqa: E402

from agentic_forge import diagnostics  # noqa: E402


def _legacy(repo: Path, name: str, records: list[dict[str, object]]) -> Path:
    legacy = repo / diagnostics.STATE_DIRNAME
    legacy.mkdir(parents=True, exist_ok=True)
    path = legacy / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_dry_run_moves_nothing(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    source = _legacy(tmp_path, "audit.jsonl", [{"tool": "Bash"}])
    assert state_migrate.main(["x", "--repo", str(tmp_path)]) == 0
    assert source.is_file()  # untouched
    assert "dry run" in capsys.readouterr().out


def test_apply_merges_and_removes_the_legacy_dir(tmp_path: Path) -> None:
    _legacy(tmp_path, "audit.jsonl", [{"tool": "Bash", "n": 1}, {"tool": "Read", "n": 2}])
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 0
    target = diagnostics.state_root(tmp_path) / "audit.jsonl"
    assert [json.loads(line)["n"] for line in target.read_text().splitlines()] == [1, 2]
    assert not (tmp_path / diagnostics.STATE_DIRNAME).exists()


def test_records_written_after_a_hand_copy_are_not_lost(tmp_path: Path) -> None:
    """The field case: an old install kept appending to the legacy path *after* the user copied
    it, so 102 records landed there afterwards. A move would drop them; a merge must not."""
    target = diagnostics.state_root(tmp_path) / "audit.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"n": 1}) + "\n", encoding="utf-8")  # the user's hand copy
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}, {"n": 2}])  # 1 duplicated, 2 arrived after
    state_migrate.main(["x", "--repo", str(tmp_path), "--apply"])
    assert [json.loads(line)["n"] for line in target.read_text().splitlines()] == [1, 2]


def test_rerunning_is_safe(tmp_path: Path) -> None:
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    state_migrate.main(["x", "--repo", str(tmp_path), "--apply"])
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])  # the same records show up again
    state_migrate.main(["x", "--repo", str(tmp_path), "--apply"])
    target = diagnostics.state_root(tmp_path) / "audit.jsonl"
    assert len(target.read_text().splitlines()) == 1  # de-duplicated, not doubled


def test_committed_config_is_never_touched(tmp_path: Path) -> None:
    legacy = tmp_path / diagnostics.STATE_DIRNAME
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text('{"diagnostics": {"enabled": true}}', encoding="utf-8")
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    state_migrate.main(["x", "--repo", str(tmp_path), "--apply"])
    assert (legacy / "config.json").is_file()  # the repo owns this file
    assert not (legacy / "audit.jsonl").exists()


def test_a_corrupt_line_aborts_before_anything_is_removed(tmp_path: Path) -> None:
    legacy = tmp_path / diagnostics.STATE_DIRNAME
    legacy.mkdir(parents=True)
    (legacy / "audit.jsonl").write_text('{"n": 1}\nnot json\n', encoding="utf-8")
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 1
    assert (legacy / "audit.jsonl").is_file()  # nothing destroyed


def test_nothing_to_migrate_is_not_an_error(tmp_path: Path) -> None:
    assert state_migrate.main(["x", "--repo", str(tmp_path)]) == 0


def test_state_in_repo_makes_it_a_no_op(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    home = tmp_path / "home"
    (home / diagnostics.STATE_DIRNAME).mkdir(parents=True)
    (home / diagnostics.STATE_DIRNAME / "config.json").write_text(
        '{"state": {"in_repo": true}}', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    source = _legacy(repo, "audit.jsonl", [{"n": 1}])
    assert state_migrate.main(["x", "--repo", str(repo), "--apply"]) == 0
    assert source.is_file()  # this IS the state root; leave it alone
    assert "state.in_repo" in capsys.readouterr().out


def test_a_repo_files_in_repo_does_not_stop_the_migration(tmp_path: Path) -> None:
    """Only the operator can keep state in the repo (ADR 0102), so a repo that set it migrates."""
    legacy = tmp_path / diagnostics.STATE_DIRNAME
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text('{"state": {"in_repo": true}}', encoding="utf-8")
    source = _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 0
    assert not source.exists()
    assert (legacy / "config.json").is_file()
    assert '"n": 1' in diagnostics.state_file(tmp_path, "audit.jsonl").read_text(encoding="utf-8")


def test_the_notice_names_the_resolved_root(tmp_path: Path) -> None:
    """`session_start` prints this; a wrong-guess migration is invisible without it."""
    assert diagnostics.legacy_state_notice(tmp_path) == ""
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    notice = diagnostics.legacy_state_notice(tmp_path)
    assert str(diagnostics.state_root(tmp_path)) in notice and "state_migrate.py" in notice


# --- the legacy directory must never receive a WRITE again (ADR 0081) ---------


def test_audit_hook_writes_to_the_state_root_even_when_a_legacy_log_exists(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """A field bundle found 18 765 records appended to `<repo>/.agentic-forge/audit.jsonl` weeks
    after that repo was migrated: the write path used the READER helper, so an existing legacy log
    captured every later append and the migration could never finish."""
    sys.path.insert(0, str(_REPO / "plugin" / "hooks" / "scripts"))
    import audit_log  # noqa: PLC0415

    legacy = _legacy(tmp_path, "audit.jsonl", [{"tool": "Bash", "n": 0}])
    before = legacy.read_text(encoding="utf-8")
    written = audit_log.write_audit(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}}, str(tmp_path)
    )
    assert written == diagnostics.state_file(tmp_path, "audit.jsonl")
    assert legacy.read_text(encoding="utf-8") == before  # the repo copy is frozen, not fed


def test_scheduler_state_saves_to_the_state_root_even_when_a_legacy_file_exists(
    tmp_path: Path,
) -> None:
    from agentic_forge import schedule  # noqa: PLC0415

    legacy = _legacy(tmp_path, "schedule-state.json", [])
    legacy.write_text(json.dumps({"digest": {"last_run": 1.0, "runs": 3}}), encoding="utf-8")
    assert schedule.load_state(tmp_path) == {}  # a repo can commit that file: not read (ADR 0103)
    saved = schedule.save_state(tmp_path, {})
    assert saved == diagnostics.state_file(tmp_path, schedule.STATE_FILE)


def test_a_bad_file_midway_keeps_what_was_merged_and_a_rerun_finishes(tmp_path: Path) -> None:
    """Files are merged one at a time, so a bad line in a later one comes after an earlier source is
    gone. Nothing may be lost in that state: the merged records are at the target, the bad file is
    where it was, the notice still says so, and repairing the file lets the same command finish."""
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    bad = _legacy(tmp_path, "diagnostics.jsonl", [{"e": 1}])
    bad.write_text('{"e": 1}\nnot json\n', encoding="utf-8")
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 1
    audit = diagnostics.state_file(tmp_path, "audit.jsonl")
    assert audit.read_text(encoding="utf-8") == '{"n": 1}\n'
    assert not diagnostics.state_file(tmp_path, "diagnostics.jsonl").exists()
    assert bad.read_text(encoding="utf-8") == '{"e": 1}\nnot json\n'
    assert "diagnostics.jsonl" in diagnostics.legacy_state_notice(tmp_path)

    bad.write_text('{"e": 1}\n', encoding="utf-8")
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 0
    assert audit.read_text(encoding="utf-8") == '{"n": 1}\n'
    merged = diagnostics.state_file(tmp_path, "diagnostics.jsonl")
    assert merged.read_text(encoding="utf-8") == '{"e": 1}\n'
    assert not (tmp_path / diagnostics.STATE_DIRNAME).exists()
    assert diagnostics.legacy_state_notice(tmp_path) == ""


# --- what is left behind, and errors that say which file (ADR 0102) -----------


def test_the_legacy_archive_left_behind_is_named(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The notice does not promise to remove it, and the migration says it stayed."""
    legacy = tmp_path / diagnostics.STATE_DIRNAME
    (legacy / "archive").mkdir(parents=True)
    (legacy / "archive" / "audit-20260101T000000Z.jsonl.gz").write_bytes(b"x")
    source = _legacy(tmp_path, "audit.jsonl", [{"n": 2}])
    notice = diagnostics.legacy_state_notice(tmp_path)
    assert "remove them from the repo" in notice and "remove it from" not in notice
    assert state_migrate.main(["x", "--repo", str(tmp_path)]) == 0
    assert "archive/: rotated logs, not moved" in capsys.readouterr().out
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 0
    assert "archive/: rotated logs, not moved" in capsys.readouterr().out
    assert not source.exists() and (legacy / "archive").is_dir()
    assert diagnostics.legacy_state_notice(tmp_path) == ""


def test_no_archive_is_not_mentioned(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _legacy(tmp_path, "audit.jsonl", [{"n": 2}])
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 0
    assert "archive/" not in capsys.readouterr().out


def test_the_error_says_which_file_and_what_has_already_gone(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    moved = _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    bad = moved.with_name("diagnostics.jsonl")
    bad.write_text("not json\n", encoding="utf-8")
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 1
    assert not moved.exists() and bad.is_file()
    err = capsys.readouterr().err
    assert "nothing was removed" not in err
    assert "diagnostics.jsonl cannot be parsed" in err and "have gone from it" in err


def test_the_error_names_the_file_it_stopped_at_not_the_last_one_listed(  # type: ignore[no-untyped-def]
    tmp_path: Path, capsys
) -> None:
    bad = _legacy(tmp_path, "audit.jsonl", [])
    bad.write_text("not json\n", encoding="utf-8")
    later = _legacy(tmp_path, "diagnostics.jsonl", [{"n": 1}])
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 1
    assert "audit.jsonl cannot be parsed" in capsys.readouterr().err
    assert later.is_file()


@pytest.mark.parametrize("flags", [[], ["--apply"]], ids=["dry-run", "apply"])
def test_a_legacy_log_that_is_not_utf8_is_an_error_not_a_traceback(  # type: ignore[no-untyped-def]
    tmp_path: Path, capsys, flags: list[str]
) -> None:
    source = _legacy(tmp_path, "audit.jsonl", [])
    source.write_bytes(b'{"n":1}\n\xff\xfe\n')
    assert state_migrate.main(["x", "--repo", str(tmp_path), *flags]) == 1
    assert "audit.jsonl cannot be parsed (UnicodeDecodeError)" in capsys.readouterr().err
    assert source.is_file()


def test_an_error_quotes_nothing_from_the_file(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _legacy(tmp_path, "audit.jsonl", []).write_text("SENTINEL-FROM-THE-REPO\n", encoding="utf-8")
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 1
    assert "SENTINEL" not in capsys.readouterr().err
