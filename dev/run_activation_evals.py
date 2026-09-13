#!/usr/bin/env python3
"""Tier-1b activation eval (ADR 0088): does a live Claude Code session invoke the skill unprompted?

Runs each on-listing skill's should_trigger prompts through a real ``claude -p`` session with the
plugin loaded, and scans the transcript for a ``Skill`` tool call naming that skill. Reports the
activation rate; a MEASUREMENT by default (no gate) — pass ``--min-activation`` to gate once a
baseline justifies a threshold. Wiring dry-run needs no credentials.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _eval_cli  # noqa: E402
from agentic_forge import activation  # noqa: E402
from agentic_forge.agent_eval import Runner  # noqa: E402

# The tools a real session has when deciding whether to reach for a skill or just do the work. The
# point is to let it do the work (Bash/Read/…) so a Skill call means it CHOSE the skill over that.
_ACTIVATION_TOOLS = "Skill,Bash,Read,Grep,Glob,Write,Edit"


def _cli_runner(plugin_dir: Path, model: str, max_turns: int, timeout: int) -> Runner:
    def run(system: str, prompt: str, workdir: Path) -> str:  # pragma: no cover -- real CLI
        cmd = [
            "claude", "-p", prompt,
            "--plugin-dir", str(plugin_dir),
            "--output-format", "stream-json", "--verbose",
            "--allowedTools", _ACTIVATION_TOOLS,
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
            "--setting-sources", "project",
        ]
        if model:
            cmd += ["--model", model]
        try:
            done = subprocess.run(
                cmd, cwd=str(workdir), capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            return (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        print(".", end="", flush=True, file=sys.stderr)
        return done.stdout

    return run


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Tier-1b: unprompted skill activation (ADR 0088).")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--skill", dest="skills", action="append")
    parser.add_argument("--runner", choices=["dry", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--min-activation", type=float, default=None,
        help="Gate: fail a skill below this rate. Omit to MEASURE only (the default; no baseline "
        "exists yet, ADR 0088).",
    )
    args = parser.parse_args(argv[1:])
    plugin_dir: Path = args.plugin.resolve()

    from agentic_forge import tier1_runner

    if args.runner == "dry":
        problems = tier1_runner.check_wiring(plugin_dir)
        for problem in problems:
            print(f"  - {problem}")
        print("\nDry-run:", "OK" if not problems else "problems found")
        return 0 if not problems else 1

    _eval_cli.warn_if_api_key_set(args.runner)
    run_fn = _cli_runner(plugin_dir, args.model, args.max_turns, args.timeout)
    gate = "measure only" if args.min_activation is None else f"gate >= {args.min_activation}"
    print(f"running Tier-1b activation via claude (model={args.model}, {gate})...", flush=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            reports = activation.run_activation(
                plugin_dir, run_fn, skills=args.skills,
                workdir=Path(tmp), min_activation=args.min_activation,
            )
    except Exception as exc:  # a crash (mis-wired plugin) — record, then fail
        print(f"Tier-1b ERROR — {exc}", flush=True)
        _eval_cli.record_failure("tier1b-activation", f"{type(exc).__name__}: {exc}")
        return 1

    rates = [r.rate for r in reports]
    mean = sum(rates) / len(rates) if rates else 0.0
    for report in sorted(reports, key=lambda r: r.rate):
        print(report.summary_line(), flush=True)
        if not report.passed:
            _eval_cli.record_failure(
                f"tier1b-activation:{report.skill}", "; ".join(report.reasons), kind="anomaly"
            )
    print(f"\nmean activation across {len(reports)} skill(s): {mean:.3f}", flush=True)
    return 0 if all(r.passed for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
