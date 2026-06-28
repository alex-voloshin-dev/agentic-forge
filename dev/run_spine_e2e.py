#!/usr/bin/env python3
"""Tier-3 E2E runner: carry a feature through a scenario's phases on an isolated fixture copy,
checking deterministic per-phase artifacts/outcomes. The `spine` scenario is the six-phase SDLC
slice; the domain scenarios (`quality-gate`, `ops-incident`) chain the Stage 4-6 skills
(docs/architecture/domain-e2e.md, ADR 0030).

Usage:
    python dev/run_spine_e2e.py --runner dry                       # verify wiring, no model calls
    python dev/run_spine_e2e.py --runner claude                    # spine, via the claude CLI
    python dev/run_spine_e2e.py --runner claude --scenario quality-gate --scenario ops-incident
    python dev/run_spine_e2e.py --runner dry --scenario all        # wiring for every scenario

`dry` needs no credentials. `claude` drives each phase headlessly with full tools in a copied
repo; keep ANTHROPIC_API_KEY unset to bill the subscription (see docs/eval-runbook.md). Without
`--scenario` only the spine runs. Exit code 0 if every selected scenario's checkpoints pass (or
dry-run is clean), 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import agent_eval, spine_e2e  # noqa: E402


def _selected(names: list[str] | None) -> list[str]:
    """Resolve --scenario into scenario names (default: spine; ``all`` -> every registered one)."""
    if not names:
        return ["spine"]
    if "all" in names:
        return list(spine_e2e.SCENARIOS)
    return names


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run Tier-3 E2E scenarios.")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--runner", choices=["dry", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        choices=[*spine_e2e.SCENARIOS, "all"],
        help="scenario(s) to run; repeatable; 'all' for every one (default: spine)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="re-run a phase whose checkpoints fail, up to N times (default 1; 0 disables)",
    )
    args = parser.parse_args(argv[1:])
    plugin_dir: Path = args.plugin.resolve()
    names = _selected(args.scenarios)

    if args.runner == "dry":
        problems: list[str] = []
        for name in names:
            problems += spine_e2e.scenario_wiring(plugin_dir, spine_e2e.SCENARIOS[name])
        for problem in problems:
            print(f"  - {problem}")
        print(f"Dry-run ({', '.join(names)}):", "OK" if not problems else "problems found")
        return 0 if not problems else 1

    run_phase = agent_eval.claude_cli_runner(
        allowed_tools="Read,Write,Edit,Bash,Grep,Glob", model=args.model, max_turns=40
    )
    base = args.workspace or Path(tempfile.mkdtemp(prefix="tier3-e2e-"))
    ok = True
    for name in names:
        scenario = spine_e2e.SCENARIOS[name]
        workspace = base / name
        print(f"\n=== scenario: {name} (workspace: {workspace}) ===", flush=True)
        results = spine_e2e.run_scenario(
            plugin_dir, scenario, run_phase=run_phase, workspace=workspace, retries=args.retries
        )
        for r in results:
            print(f"[{r.phase}] {'PASS' if r.passed else 'FAIL'}", flush=True)
            for c in r.checkpoints:
                print(c, flush=True)
        passed = spine_e2e.all_passed(results)
        print(f"-> {name}: {'PASS' if passed else 'FAIL'}", flush=True)
        ok = ok and passed
    print(f"\nTier-3 E2E ({', '.join(names)}): {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
