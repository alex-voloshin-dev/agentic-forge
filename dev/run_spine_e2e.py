#!/usr/bin/env python3
"""Tier-3 SDLC-spine E2E runner: carry `task-priorities` through architecture -> develop ->
code-review on an isolated copy of the taskstore fixture repo, checking per-phase artifacts +
that the code passes the repo's tests.

Usage:
    python dev/run_spine_e2e.py --runner dry         # verify wiring, no model calls
    python dev/run_spine_e2e.py --runner claude      # real run via the claude CLI (subscription)

`dry` needs no credentials. `claude` drives each phase headlessly with full tools in the copied
repo; keep ANTHROPIC_API_KEY unset to bill the subscription (see docs/eval-runbook.md).

Exit code 0 if every phase's checkpoints pass (or dry-run is clean), 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import agent_eval, spine_e2e  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the Tier-3 SDLC-spine E2E scenario.")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--runner", choices=["dry", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    plugin_dir: Path = args.plugin.resolve()

    if args.runner == "dry":
        problems = spine_e2e.check_wiring(plugin_dir)
        for p in problems:
            print(f"  - {p}")
        print("Dry-run:", "OK" if not problems else "problems found")
        return 0 if not problems else 1

    workspace = args.workspace or Path(tempfile.mkdtemp(prefix="spine-e2e-"))
    print(f"workspace: {workspace}", flush=True)
    run_phase = agent_eval.claude_cli_runner(
        allowed_tools="Read,Write,Edit,Bash,Grep,Glob", model=args.model, max_turns=40
    )
    results = spine_e2e.run_e2e(plugin_dir, run_phase=run_phase, workspace=workspace)
    for r in results:
        print(f"[{r.phase}] {'PASS' if r.passed else 'FAIL'}", flush=True)
        for c in r.checkpoints:
            print(c, flush=True)
    ok = spine_e2e.all_passed(results)
    print(f"\nTier-3 E2E: {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
