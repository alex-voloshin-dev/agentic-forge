"""The hook smoke (dev/hook_smoke.py, ADR 0094) — CI runs it under Python 3.9, the floor the
field's bare ``python3`` gives; here it runs under the dev interpreter so a broken hook, a missing
payload or a non-JSON stdout fails Tier-0 before it fails 3.9."""

from __future__ import annotations

import sys
from pathlib import Path

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
