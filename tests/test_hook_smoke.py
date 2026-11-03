"""The hook smoke (dev/hook_smoke.py, ADR 0094) — CI runs it under Python 3.9, the floor the
field's bare ``python3`` gives; here it runs under the dev interpreter so a broken hook, a missing
payload or a non-JSON stdout fails Tier-0 before it fails 3.9."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "dev"))

import hook_smoke  # noqa: E402


def test_every_hook_has_a_smoke_payload() -> None:
    hooks = {p.name for p in hook_smoke.HOOKS.glob("*.py")}
    assert hooks == set(hook_smoke.PAYLOADS), "a new hook must be smoked: add its payload"


def test_hook_reachable_closure_is_the_3_9_contract() -> None:
    mods = hook_smoke.hook_reachable_modules()
    assert {"guardrails", "diagnostics", "settings", "vault", "pre_router"} <= set(mods)
    assert "agent_eval" not in mods  # the eval harness is dev-side, not on the hook path


def test_smoke_passes_under_this_interpreter(capsys: object) -> None:
    assert hook_smoke.main([]) == 0


def _budget_count(tmp: Path) -> str:
    """Run the budget hook through the smoke's own runner and read its counter."""
    cwd, state, scratch = tmp / "repo", tmp / "state", tmp / "scratch"
    for path in (cwd, state, scratch):
        path.mkdir(exist_ok=True)
    hook = hook_smoke.HOOKS / "budget.py"
    assert hook_smoke.run_hook(hook, hook_smoke.PAYLOADS["budget.py"], cwd, state, scratch) is None
    counters = list(scratch.glob("agentic-forge-budget-*"))
    assert len(counters) == 1  # the hook wrote to the run's own scratch directory
    return counters[0].read_text(encoding="utf-8").strip()


def test_the_budget_counter_is_in_the_runs_own_scratch_directory(tmp_path: Path) -> None:
    assert _budget_count(tmp_path) == "1"
    assert _budget_count(tmp_path) == "2"  # same scratch, same session: it does count
    (tmp_path / "next-run").mkdir()
    assert _budget_count(tmp_path / "next-run") == "1"  # a new run starts from nothing


def test_repeated_smoke_runs_do_not_accumulate_in_the_shared_temp_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole smoke, past a hard cap of 1: this failed on any machine that had run it often.
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setenv("TMPDIR", str(shared))
    monkeypatch.setattr(tempfile, "tempdir", None)  # re-read TMPDIR, here and in the runs below
    assert tempfile.gettempdir() == str(shared)
    monkeypatch.setenv("AGENTIC_FORGE_SUBAGENT_HARD", "1")
    for _ in range(3):
        failures: list[str] = []
        hook_smoke.check_hooks(failures)
        assert failures == []
    assert os.listdir(shared) == []
