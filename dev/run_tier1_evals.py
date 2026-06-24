#!/usr/bin/env python3
"""Tier-1 trigger eval runner for the on-listing router skills (research, product, architecture,
plan, develop, code-review, deep-review, skill-factory) — measured on the LIVE skill listing.

Usage:
    python dev/run_tier1_evals.py --runner dry            # verify wiring, no model calls
    python dev/run_tier1_evals.py --runner claude         # real run via your Claude subscription
    python dev/run_tier1_evals.py --runner api            # real run via API key (per-token)
    python dev/run_tier1_evals.py --skill research ...    # one skill (repeatable)

`dry` needs no credentials and never calls a model: it checks that the live listing is
well-formed and every tier1 skill is on-listing with trigger prompts. `claude` (recommended)
shells out to the `claude` CLI with tools disabled and one turn, classifying each trigger prompt
against the live listing; keep ANTHROPIC_API_KEY unset to bill your subscription. `api` uses the
Anthropic Messages SDK (per-token). Grading is deterministic (did the router pick the skill?),
sampled majority-of-N, gated at recall/specificity >= 0.9. See docs/eval-runbook.md and ADR 0016.

Exit code 0 if every selected skill's Tier-1 gate passes (or dry-run is clean), 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import agent_eval, tier1_runner  # noqa: E402


def _build_router(runner: str, model: str) -> agent_eval.Runner:
    """Return the classification Runner for the chosen transport (tools off, capped turns).

    Tools are disabled (`allowed_tools=""`) so the router can only answer with a skill name. The
    turn cap leaves room for the model's own thinking before its final text — `max_turns=1` cut
    reasoning models off mid-think ("Reached max turns (1)"); a small cap (4) lets them finish
    while tools-off keeps it a pure one-shot classification.
    """
    if runner == "api":
        return agent_eval.api_runner(model)
    if runner == "claude":
        return agent_eval.claude_cli_runner(allowed_tools="", model=model, max_turns=4)
    raise ValueError(f"unknown runner {runner!r}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run Tier-1 trigger evals on live descriptions.")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--skill", action="append", dest="skills")
    parser.add_argument("--runner", choices=["dry", "api", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--runs", type=int, default=tier1_runner.DEFAULT_RUNS)
    args = parser.parse_args(argv[1:])

    plugin_dir: Path = args.plugin.resolve()

    if args.skills:
        known = {t.name for t in tier1_runner.load_triggers(plugin_dir)}
        for skill in args.skills:
            if skill not in known:
                print(
                    f"warning: --skill {skill!r} is not a Tier-1 skill (known: {sorted(known)})",
                    file=sys.stderr,
                )

    if args.runner == "dry":
        problems = tier1_runner.check_wiring(plugin_dir)
        for problem in problems:
            print(f"  - {problem}")
        print("\nDry-run:", "OK" if not problems else "problems found")
        return 0 if not problems else 1

    if args.runner == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "warning: ANTHROPIC_API_KEY is set; the claude CLI uses it before the subscription "
            "token. Unset it to bill this run to your Claude subscription.",
            file=sys.stderr,
        )

    run_fn = _build_router(args.runner, args.model)
    print(f"running Tier-1 via {args.runner} (model={args.model}, runs={args.runs})...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        reports = tier1_runner.run_tier1(
            plugin_dir, run_fn, skills=args.skills, runs=args.runs, workdir=Path(tmp)
        )
    for report in reports:
        print(report.summary_line(), flush=True)
    return 0 if tier1_runner.all_passed(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
