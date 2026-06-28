from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forge import schedule
from agentic_forge.schedule import (
    CADENCES,
    JOBS,
    MAX_RETRIES,
    Job,
    JobState,
    due_jobs,
    format_health,
    health,
    load_state,
    record_run,
    save_state,
)

DAY = 24 * 60 * 60

JS = (
    Job("d", "daily", "", "a"),
    Job("w", "weekly", "", "b"),
)


def _ok(last: float) -> JobState:
    return JobState(last_run=last, status="ok", runs=1)


def test_registry_jobs_have_known_cadences() -> None:
    assert JOBS  # non-empty
    assert all(j.cadence in CADENCES for j in JOBS)


def test_cadences_ordered() -> None:
    assert CADENCES["daily"] < CADENCES["weekly"] < CADENCES["monthly"]


# --- due_jobs --------------------------------------------------------------------------


def test_due_jobs_all_when_never_run() -> None:
    assert [j.name for j in due_jobs(JS, {}, now=1_000_000.0)] == ["d", "w"]


def test_due_jobs_none_when_recent() -> None:
    now = 1_000_000.0
    state = {"d": _ok(now - 1), "w": _ok(now - 1)}
    assert due_jobs(JS, state, now=now) == []


def test_due_jobs_daily_elapsed_weekly_not() -> None:
    now = 10 * DAY
    state = {"d": _ok(now - (DAY + 5)), "w": _ok(now - 2 * DAY)}  # daily overdue, weekly fresh
    assert [j.name for j in due_jobs(JS, state, now=now)] == ["d"]


def test_due_jobs_exactly_at_interval_is_due() -> None:
    now = 10 * DAY
    state = {"d": _ok(now - DAY), "w": _ok(now - 1)}  # daily exactly due; weekly fresh
    assert [j.name for j in due_jobs(JS, state, now=now)] == ["d"]


def test_due_jobs_unknown_cadence_raises() -> None:
    with pytest.raises(ValueError, match="unknown cadence"):
        due_jobs((Job("x", "hourly", "", "z"),), {}, now=0.0)


def test_due_jobs_retries_recent_failure() -> None:
    now = 1_000_000.0
    # ran 1s ago (cadence NOT elapsed) but failed -> retried on the next poll
    state = {"d": JobState(last_run=now - 1, status="failed", runs=1, failures=1)}
    assert [j.name for j in due_jobs((JS[0],), state, now=now)] == ["d"]


def test_due_jobs_backs_off_after_max_retries() -> None:
    now = 1_000_000.0
    state = {"d": JobState(last_run=now - 1, status="failed", runs=9, failures=MAX_RETRIES + 1)}
    assert due_jobs((JS[0],), state, now=now) == []  # retries exhausted -> wait for cadence


def test_due_jobs_backs_off_exactly_at_max_retries() -> None:
    now = 1_000_000.0
    # the off-by-one boundary: failed exactly MAX_RETRIES times == exhausted -> NOT due.
    state = {"d": JobState(last_run=now - 1, status="failed", runs=9, failures=MAX_RETRIES)}
    assert due_jobs((JS[0],), state, now=now) == []


def test_due_jobs_retries_one_below_max_retries() -> None:
    now = 1_000_000.0
    # one short of the cap is still retried (cap is exactly MAX_RETRIES failed attempts).
    state = {"d": JobState(last_run=now - 1, status="failed", runs=9, failures=MAX_RETRIES - 1)}
    assert [j.name for j in due_jobs((JS[0],), state, now=now)] == ["d"]


# --- record_run ------------------------------------------------------------------------


def test_record_run_success() -> None:
    state = record_run({}, "d", 100.0, ok=True)
    assert state["d"] == JobState(last_run=100.0, status="ok", runs=1, failures=0)


def test_record_run_failures_accumulate_then_reset() -> None:
    state = record_run({}, "d", 100.0, ok=False)
    assert state["d"].status == "failed" and state["d"].failures == 1 and state["d"].runs == 1
    state = record_run(state, "d", 200.0, ok=False)
    assert state["d"].failures == 2 and state["d"].runs == 2
    state = record_run(state, "d", 300.0, ok=True)  # a success resets the failure streak
    assert state["d"].status == "ok" and state["d"].failures == 0 and state["d"].runs == 3


def test_record_run_is_pure() -> None:
    original: dict[str, JobState] = {}
    record_run(original, "d", 1.0, ok=True)
    assert original == {}  # input not mutated


# --- state I/O -------------------------------------------------------------------------


def test_load_state_absent_is_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path) == {}


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    state = {
        "d": JobState(last_run=123.0, status="ok", runs=2, failures=0),
        "w": JobState(last_run=456.0, status="failed", runs=1, failures=1),
    }
    save_state(tmp_path, state)
    assert load_state(tmp_path) == state


def test_load_state_migrates_legacy_flat(tmp_path: Path) -> None:
    p = tmp_path / schedule.STATE_PATH
    p.parent.mkdir(parents=True)
    p.write_text('{"d": 123.0, "w": 456}', encoding="utf-8")  # legacy flat {name: last_run}
    assert load_state(tmp_path) == {
        "d": JobState(last_run=123.0, status="ok", runs=1),
        "w": JobState(last_run=456.0, status="ok", runs=1),
    }


def test_save_state_creates_parent_dir(tmp_path: Path) -> None:
    path = save_state(tmp_path, {"d": JobState(last_run=1.0)})
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


def test_load_state_drops_bad_values(tmp_path: Path) -> None:
    p = tmp_path / schedule.STATE_PATH
    p.parent.mkdir(parents=True)
    # a string and a bool are not valid state values; an uncoercible mapping is dropped too
    p.write_text('{"d": 1.0, "s": "x", "b": true, "m": {"last_run": "nope"}}', encoding="utf-8")
    assert load_state(tmp_path) == {"d": JobState(last_run=1.0, status="ok", runs=1)}


# --- health report ---------------------------------------------------------------------


def test_health_never_run_ok_and_failed() -> None:
    state = {
        "deploy-digest": JobState(last_run=5.0, status="ok", runs=3, failures=0),
        "audit-digest": JobState(last_run=9.0, status="failed", runs=2, failures=1),
    }
    by_name = {h.name: h for h in health(JOBS, state)}
    assert by_name["kb-maintenance"].status == "never-run"  # no recorded state
    assert by_name["deploy-digest"].status == "ok" and by_name["deploy-digest"].runs == 3
    assert by_name["audit-digest"].status == "failed" and by_name["audit-digest"].failures == 1


def test_format_health_reports_failing_and_unrun() -> None:
    state = {"deploy-digest": JobState(last_run=1.0, status="failed", runs=1, failures=1)}
    out = format_health(health(JOBS, state))
    assert "Scheduled-job health" in out and "1 failing" in out
    assert "deploy-digest (daily) — failed" in out
    assert "never run" in out  # the jobs with no recorded state


def test_format_health_empty() -> None:
    assert format_health([]) == "No scheduled jobs."
