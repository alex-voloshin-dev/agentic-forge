"""Tests for the Ralph loop core (ADR 0048)."""

from __future__ import annotations

from agentic_forge import ralph


def test_decide_outcomes() -> None:
    d = ralph.decide
    assert d(ralph.LoopState(done=True), max_iterations=5, stall_after=2) == ralph.DONE
    assert d(ralph.LoopState(iteration=5), max_iterations=5, stall_after=2) == ralph.EXHAUSTED
    assert d(ralph.LoopState(no_progress=2), max_iterations=5, stall_after=2) == ralph.STALLED
    assert d(ralph.LoopState(iteration=1), max_iterations=5, stall_after=2) == ralph.CONTINUE
    # stall_after <= 0 disables stall detection (0 and negative)
    assert d(ralph.LoopState(no_progress=9), max_iterations=5, stall_after=0) == ralph.CONTINUE
    assert d(ralph.LoopState(no_progress=9), max_iterations=5, stall_after=-1) == ralph.CONTINUE
    # done wins even when also at the budget
    assert d(ralph.LoopState(iteration=5, done=True), max_iterations=5, stall_after=2) == ralph.DONE


def test_advance_tracks_progress_and_done() -> None:
    s = ralph.advance(ralph.LoopState(no_progress=3), progressed=True, done=False)
    assert s.iteration == 1 and s.no_progress == 0  # progress resets the streak
    s2 = ralph.advance(s, progressed=False, done=True)
    assert s2.iteration == 2 and s2.no_progress == 1 and s2.done is True


def test_run_ralph_stops_on_done() -> None:
    runs: list[int] = []
    dones = iter([False, True])  # done on the 2nd check
    result = ralph.run_ralph(
        run_iteration=lambda n: runs.append(n),
        is_done=lambda: next(dones),
        progressed=lambda: True,
        max_iterations=10,
        stall_after=0,
    )
    assert result.outcome == ralph.DONE and result.iterations == 2
    assert runs == [1, 2]  # 1-based iteration numbers


def test_run_ralph_done_on_final_allowed_iteration() -> None:
    # finishing on the LAST allowed iteration is reported DONE, not EXHAUSTED (done wins)
    dones = iter([False, True])
    result = ralph.run_ralph(
        run_iteration=lambda n: None,
        is_done=lambda: next(dones),
        progressed=lambda: True,
        max_iterations=2,
        stall_after=0,
    )
    assert result.outcome == ralph.DONE and result.iterations == 2


def test_run_ralph_exhausts_budget() -> None:
    runs: list[int] = []
    result = ralph.run_ralph(
        run_iteration=lambda n: runs.append(n),
        is_done=lambda: False,
        progressed=lambda: True,
        max_iterations=3,
        stall_after=0,
    )
    assert result.outcome == ralph.EXHAUSTED and result.iterations == 3 and runs == [1, 2, 3]


def test_run_ralph_stalls_on_no_progress() -> None:
    rec: list[str] = []
    result = ralph.run_ralph(
        run_iteration=lambda n: None,
        is_done=lambda: False,
        progressed=lambda: False,  # never makes progress
        max_iterations=10,
        stall_after=2,
        record=rec.append,
    )
    assert result.outcome == ralph.STALLED and result.iterations == 2  # 2 no-progress -> stop
    assert len(rec) == 2 and "progressed=False" in rec[0]
    assert result.history == rec  # history mirrors the per-iteration records


def test_run_ralph_zero_budget_runs_nothing() -> None:
    runs: list[int] = []
    result = ralph.run_ralph(
        run_iteration=lambda n: runs.append(n),
        is_done=lambda: False,
        progressed=lambda: True,
        max_iterations=0,
    )
    assert result.outcome == ralph.EXHAUSTED and result.iterations == 0 and runs == []
