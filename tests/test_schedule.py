from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forge import schedule
from agentic_forge.schedule import CADENCES, JOBS, Job, due_jobs, load_state, save_state

DAY = 24 * 60 * 60


def test_registry_jobs_have_known_cadences() -> None:
    assert JOBS  # non-empty
    assert all(j.cadence in CADENCES for j in JOBS)


def test_cadences_ordered() -> None:
    assert CADENCES["daily"] < CADENCES["weekly"] < CADENCES["monthly"]


# --- due_jobs --------------------------------------------------------------------------

JS = (
    Job("d", "daily", "", "a"),
    Job("w", "weekly", "", "b"),
)


def test_due_jobs_all_when_never_run() -> None:
    assert [j.name for j in due_jobs(JS, {}, now=1_000_000.0)] == ["d", "w"]


def test_due_jobs_none_when_recent() -> None:
    now = 1_000_000.0
    last = {"d": now - 1, "w": now - 1}
    assert due_jobs(JS, last, now=now) == []


def test_due_jobs_daily_elapsed_weekly_not() -> None:
    now = 10 * DAY
    last = {"d": now - (DAY + 5), "w": now - (2 * DAY)}  # daily overdue, weekly fresh
    assert [j.name for j in due_jobs(JS, last, now=now)] == ["d"]


def test_due_jobs_exactly_at_interval_is_due() -> None:
    now = 10 * DAY
    last = {"d": now - DAY, "w": now - 1}  # daily exactly due; weekly fresh
    assert [j.name for j in due_jobs(JS, last, now=now)] == ["d"]


def test_due_jobs_unknown_cadence_raises() -> None:
    with pytest.raises(ValueError, match="unknown cadence"):
        due_jobs((Job("x", "hourly", "", "z"),), {}, now=0.0)


# --- state I/O -------------------------------------------------------------------------


def test_load_state_absent_is_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path) == {}


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    save_state(tmp_path, {"d": 123.0, "w": 456.0})
    assert load_state(tmp_path) == {"d": 123.0, "w": 456.0}


def test_save_state_creates_parent_dir(tmp_path: Path) -> None:
    path = save_state(tmp_path, {"d": 1.0})
    assert path.is_file() and path.name == "schedule-state.json"


def test_load_state_malformed_is_empty(tmp_path: Path) -> None:
    p = tmp_path / schedule.STATE_PATH
    p.parent.mkdir(parents=True)
    p.write_text("not json", encoding="utf-8")
    assert load_state(tmp_path) == {}


def test_load_state_non_dict_is_empty(tmp_path: Path) -> None:
    p = tmp_path / schedule.STATE_PATH
    p.parent.mkdir(parents=True)
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_state(tmp_path) == {}


def test_load_state_drops_non_numeric_values(tmp_path: Path) -> None:
    p = tmp_path / schedule.STATE_PATH
    p.parent.mkdir(parents=True)
    p.write_text('{"d": 1.0, "bad": "x"}', encoding="utf-8")
    assert load_state(tmp_path) == {"d": 1.0}
