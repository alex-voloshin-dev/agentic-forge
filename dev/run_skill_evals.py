#!/usr/bin/env python3
"""Tier-2 quality eval runner for SKILLS that declare a tier2_quality contract — the nine
*-patterns packs + engineering-standards (knowledge skills, run as the software-engineer with
them loaded) and deep-review / skill-factory (run directly).

Usage:
    python dev/run_skill_evals.py --runner dry              # verify wiring, no model calls
    python dev/run_skill_evals.py --runner claude           # real run via your Claude subscription
    python dev/run_skill_evals.py --runner api              # real run via API key (per-token)
    python dev/run_skill_evals.py --skill python-patterns   # one skill (repeatable)

`dry` needs no credentials and never calls a model: it checks every skill's contract, cases,
fixtures, and (for knowledge skills) that the base role + engineering-standards are present.
`claude` (recommended) shells out to the `claude` CLI with the executing component's tools and
grades with the read-only grader role; keep ANTHROPIC_API_KEY unset to bill your subscription.
`api` uses the Anthropic Messages SDK (per-token). Each skill runs N times, graded, aggregated,
and gated at the contract's tier2 thresholds (mean - stddev >= 0.8). See docs/eval-runbook.md
and ADR 0017.

NOTE: the knowledge-skill runs are the most expensive eval — each is a full software-engineer
coding session per case x N runs. Use --skill / --runs to scope local runs; CI cost-gates it.

Exit code 0 if every selected skill's gate passes (or dry-run is clean), 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

import _eval_cli  # noqa: E402
from agentic_forge import agent_eval, skill_eval  # noqa: E402


def _build_runners(
    runner: str, skill: str, plugin_dir: Path, model: str
) -> tuple[agent_eval.Runner, agent_eval.Runner]:
    """Return (skill_runner, grader_runner) for the chosen transport.

    The skill runner gets the executing component's tools (the software-engineer's for a
    knowledge skill, the skill's own otherwise); the grader is read-only so it can verify
    on-disk artifacts (level-2) without ever modifying them.
    """
    if runner == "api":
        api = agent_eval.api_runner(model)
        return api, api
    if runner == "claude":
        run_fn = agent_eval.claude_cli_runner(
            allowed_tools=skill_eval.skill_tools(plugin_dir, skill), model=model, max_turns=40
        )
        grader_fn = agent_eval.claude_cli_runner(
            allowed_tools="Read,Grep,Glob", model=model, max_turns=20
        )
        return run_fn, grader_fn
    raise ValueError(f"unknown runner {runner!r}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run Tier-2 quality evals for skills.")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--skill", action="append", dest="skills")
    parser.add_argument("--runner", choices=["dry", "api", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--workdir", type=Path, default=None)
    args = parser.parse_args(argv[1:])

    plugin_dir: Path = args.plugin.resolve()
    discovered = skill_eval.discover_skills_with_tier2(plugin_dir)
    skills = args.skills or discovered
    for skill in skills:
        if skill not in discovered:
            print(
                f"warning: --skill {skill!r} has no tier2_quality contract "
                f"(known: {discovered})",
                file=sys.stderr,
            )

    if args.runner == "dry":
        ok = True
        for skill in skills:
            problems = skill_eval.check_wiring(skill, plugin_dir)
            if problems:
                ok = False
                print(f"{skill}: NOT READY")
                for problem in problems:
                    print(f"  - {problem}")
            else:
                print(f"{skill}: ready")
        print("\nDry-run:", "OK" if ok else "problems found")
        return 0 if ok else 1

    _eval_cli.warn_if_api_key_set(args.runner)

    all_passed = True
    for skill in skills:
        print(f"[{skill}] running via {args.runner} (model={args.model})...", flush=True)
        try:
            run_fn, grader_fn = _build_runners(args.runner, skill, plugin_dir, args.model)
            report = skill_eval.run_skill(
                skill,
                plugin_dir,
                run_skill_fn=run_fn,
                run_grader_fn=grader_fn,
                runs=args.runs,
                workdir=args.workdir,
            )
        except Exception as exc:  # keep going so one skill's failure doesn't lose the rest
            print(f"{skill}: ERROR — {exc}", flush=True)
            all_passed = False
            continue
        print(report.summary_line(), flush=True)
        all_passed = all_passed and report.passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
