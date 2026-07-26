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


def test_state_in_repo_makes_it_a_no_op(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    legacy = tmp_path / diagnostics.STATE_DIRNAME
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text('{"state": {"in_repo": true}}', encoding="utf-8")
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    assert state_migrate.main(["x", "--repo", str(tmp_path), "--apply"]) == 0
    assert (legacy / "audit.jsonl").is_file()  # this IS the state root; leave it alone
    assert "state.in_repo" in capsys.readouterr().out


def test_the_notice_names_the_resolved_root(tmp_path: Path) -> None:
    """`session_start` prints this; a wrong-guess migration is invisible without it."""
    assert diagnostics.legacy_state_notice(tmp_path) == ""
    _legacy(tmp_path, "audit.jsonl", [{"n": 1}])
    notice = diagnostics.legacy_state_notice(tmp_path)
    assert str(diagnostics.state_root(tmp_path)) in notice and "state_migrate.py" in notice
