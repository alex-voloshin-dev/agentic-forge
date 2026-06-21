#!/usr/bin/env python3
"""Tier-2 quality eval runner for the engine roles (reviewer/grader/implementer/architect).

Usage:
    python dev/run_agent_evals.py --runner dry            # verify wiring, no model calls
    python dev/run_agent_evals.py --runner claude         # real run via your Claude subscription
    python dev/run_agent_evals.py --runner api            # real run via API key (per-token)
    python dev/run_agent_evals.py --role reviewer ...     # one role (repeatable)

`dry` needs no credentials and never calls a model: it checks that every contract, role
prompt, and fixture resolves. `claude` (recommended) shells out to the `claude` CLI, so it
uses your Claude Code auth — a subscription via CLAUDE_CODE_OAUTH_TOKEN (`claude
setup-token`); make sure ANTHROPIC_API_KEY is unset or it takes precedence and bills per
token. `api` uses the Anthropic Messages SDK and always bills per token. Both run each role's
cases N times, grade with the grader role, aggregate, and gate against the contract's tier2
thresholds. See docs/eval-runbook.md.

Exit code 0 if every selected role's gate passes (or dry-run is clean), 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import agent_eval  # noqa: E402
from agentic_forge.frontmatter import parse as parse_frontmatter  # noqa: E402


def _role_tools(plugin_dir: Path, role: str) -> str:
    fm, _ = parse_frontmatter((plugin_dir / "agents" / f"{role}.md").read_text(encoding="utf-8"))
    return str(fm.get("tools", "Read, Grep, Glob"))


def _build_runners(
    runner: str, role: str, plugin_dir: Path, model: str
) -> tuple[agent_eval.Runner, agent_eval.Runner]:
    """Return (role_runner, grader_runner) for the chosen transport.

    `claude` keeps everything (role and grading) on the `claude` CLI so the whole run uses
    your Claude subscription with no API key; the grader gets no tools and a single turn.
    `api` uses the Anthropic Messages SDK for both (per-token billing).
    """
    if runner == "api":
        api = agent_eval.api_runner(model)
        return api, api
    if runner == "claude":
        role_fn = agent_eval.claude_cli_runner(
            allowed_tools=_role_tools(plugin_dir, role), model=model, max_turns=40
        )
        # Grader: read-only tools so it can verify on-disk artifacts (level-2) without ever
        # modifying them; generous turns so reading several files never hits the limit.
        grader_fn = agent_eval.claude_cli_runner(
            allowed_tools="Read,Grep,Glob", model=model, max_turns=20
        )
        return role_fn, grader_fn
    raise ValueError(f"unknown runner {runner!r}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run Tier-2 quality evals for engine roles.")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--role", action="append", dest="roles", choices=agent_eval.ROLES)
    parser.add_argument("--runner", choices=["dry", "api", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument(
        "--isolate",
        action="store_true",
        help="give each case execution a fresh temp workdir (use for write roles)",
    )
    args = parser.parse_args(argv[1:])

    plugin_dir: Path = args.plugin.resolve()
    roles = args.roles or list(agent_eval.ROLES)

    if args.runner == "dry":
        ok = True
        for role in roles:
            problems = agent_eval.check_wiring(role, plugin_dir)
            if problems:
                ok = False
                print(f"{role}: NOT READY")
                for problem in problems:
                    print(f"  - {problem}")
            else:
                print(f"{role}: ready")
        print("\nDry-run:", "OK" if ok else "problems found")
        return 0 if ok else 1

    if args.runner == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "warning: ANTHROPIC_API_KEY is set; the claude CLI uses it before the "
            "subscription token. Unset it to bill this run to your Claude subscription.",
            file=sys.stderr,
        )

    all_passed = True
    for role in roles:
        print(f"[{role}] running via {args.runner} (model={args.model})...", flush=True)
        try:
            role_fn, grader_fn = _build_runners(args.runner, role, plugin_dir, args.model)
            report = agent_eval.run_role(
                role,
                plugin_dir,
                run_role_fn=role_fn,
                run_grader_fn=grader_fn,
                runs=args.runs,
                workdir=args.workdir,
                isolate=args.isolate,
            )
        except Exception as exc:  # keep going so one role's failure doesn't lose the rest
            print(f"{role}: ERROR — {exc}", flush=True)
            all_passed = False
            continue
        print(report.summary_line(), flush=True)
        all_passed = all_passed and report.passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
