"""Ralph loop core (ADR 0048): bounded autonomous iteration over a persistent task.

An executor is re-run with a **stable prompt** each iteration in a **fresh context**; the filesystem
(code, a task / progress file, git) carries state across runs. The loop is **bounded** — it always
terminates — and stops early on a **done** signal or a **stall** (no progress).

This module is the **pure** loop-control core: the iteration state, the decision (continue / done /
exhausted / stalled), and the bounded driver over three injected **seams** (run one iteration, check
done, check progress). The live agent / test / git calls are the seams (the pr_watch pattern); the
real wiring lives in ``dev/ralph.py``. It **never** merges or pushes — there is no such seam here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = [
    "CONTINUE",
    "DONE",
    "EXHAUSTED",
    "STALLED",
    "LoopState",
    "RalphResult",
    "decide",
    "advance",
    "run_ralph",
]

# Loop decisions. CONTINUE means run another iteration; the rest are terminal outcomes.
CONTINUE = "continue"
DONE = "done"  # the is_done stop signal was observed
EXHAUSTED = "exhausted"  # hit max_iterations without finishing
STALLED = "stalled"  # stall_after consecutive iterations made no progress


@dataclass(frozen=True)
class LoopState:
    """The loop's running state: iterations completed, the consecutive-no-progress streak, and
    whether the done signal has been observed."""

    iteration: int = 0
    no_progress: int = 0
    done: bool = False


@dataclass
class RalphResult:
    """The outcome of a Ralph run (for the report + diagnostics)."""

    iterations: int
    outcome: str  # DONE | EXHAUSTED | STALLED
    history: list[str] = field(default_factory=list)


def decide(state: LoopState, *, max_iterations: int, stall_after: int) -> str:
    """The next action for ``state`` (pure). ``done`` wins (stop as soon as the task is finished,
    even if also at the budget); then ``exhausted`` (>= ``max_iterations``); then ``stalled``
    (``stall_after`` consecutive no-progress iterations — disabled when ``stall_after <= 0``);
    otherwise ``continue``."""
    if state.done:
        return DONE
    if state.iteration >= max_iterations:
        return EXHAUSTED
    if stall_after > 0 and state.no_progress >= stall_after:
        return STALLED
    return CONTINUE


def advance(state: LoopState, *, progressed: bool, done: bool) -> LoopState:
    """The state after one iteration: bump the count, reset the no-progress streak on progress (else
    grow it), and record the done signal (pure)."""
    return LoopState(
        iteration=state.iteration + 1,
        no_progress=0 if progressed else state.no_progress + 1,
        done=done,
    )


def run_ralph(
    *,
    run_iteration: Callable[[int], object],
    is_done: Callable[[], bool],
    progressed: Callable[[], bool],
    max_iterations: int,
    stall_after: int = 0,
    record: Callable[[str], object] | None = None,
) -> RalphResult:
    """Drive the bounded autonomous loop (ADR 0048). Each round: if :func:`decide` says stop, return
    the outcome; else run one iteration (``run_iteration(n)`` is the fresh-context executor), then
    check the stop signal (``is_done``) and whether it progressed (``progressed``). Bounded by
    ``max_iterations`` (and optionally ``stall_after``), so it always terminates. ``record`` (if
    given) logs each iteration. Never merges, never pushes."""
    state = LoopState()
    history: list[str] = []
    while True:
        decision = decide(state, max_iterations=max_iterations, stall_after=stall_after)
        if decision != CONTINUE:
            return RalphResult(iterations=state.iteration, outcome=decision, history=history)
        run_iteration(state.iteration + 1)  # 1-based iteration number for the executor
        made = bool(progressed())
        finished = bool(is_done())
        state = advance(state, progressed=made, done=finished)
        note = f"iteration {state.iteration}: progressed={made} done={finished}"
        history.append(note)
        if record:
            record(note)
