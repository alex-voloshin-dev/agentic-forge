#!/usr/bin/env python3
"""Tier-1b activation eval (ADR 0088): does a live Claude Code session invoke the skill unprompted?

Runs each on-listing skill's should_trigger prompts through a real ``claude -p`` session with the
plugin loaded, and scans the transcript for a ``Skill`` tool call naming that skill. Reports the
activation rate; a MEASUREMENT by default (no gate) — pass ``--min-activation`` to gate once a
baseline justifies a threshold. Wiring dry-run needs no credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
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


def _cli_runner(
    plugin_dir: Path, model: str, max_turns: int, timeout: int, env: dict[str, str]
) -> Runner:
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
                cmd, cwd=str(workdir), capture_output=True, text=True, timeout=timeout,
                env={**os.environ, **env},
            )
        except subprocess.TimeoutExpired as exc:
            return (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        print(".", end="", flush=True, file=sys.stderr)
        return done.stdout

    return run


def _why_runner(
    plugin_dir: Path, model: str, timeout: int, env: dict[str, str]
) -> Callable[[str, str], str]:
    """Resume a miss's session and ask it why (ADR 0088, step 4). One turn, no tools."""

    def ask(session_id: str, question: str) -> str:  # pragma: no cover -- real CLI
        cmd = [
            "claude", "-p", question, "--resume", session_id,
            "--plugin-dir", str(plugin_dir),
            "--output-format", "json", "--max-turns", "1", "--allowedTools", "",
            "--setting-sources", "project",
        ]
        if model:
            cmd += ["--model", model]
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **env}
        )
        try:
            data = json.loads(done.stdout)
            return str(data.get("result", "")) if isinstance(data, dict) else done.stdout
        except json.JSONDecodeError:
            return done.stdout

    return ask


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Tier-1b: unprompted skill activation (ADR 0088).")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--skill", dest="skills", action="append")
    parser.add_argument("--runner", choices=["dry", "claude"], default="dry")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--ask-why", action="store_true",
        help="For every miss, resume the session and ask why it did the work by hand "
        "(ADR 0088, step 4). Self-reports, bucketed and printed raw.",
    )
    parser.add_argument(
        "--env", action="append", default=[], metavar="KEY=VALUE",
        help="Environment for the sessions under test, e.g. AGENTIC_FORGE_PRE_ROUTER=1 — the "
        "condition you measured, made explicit.",
    )
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
    env = dict(kv.split("=", 1) for kv in args.env if "=" in kv)
    run_fn = _cli_runner(plugin_dir, args.model, args.max_turns, args.timeout, env)
    ask = _why_runner(plugin_dir, args.model, args.timeout, env) if args.ask_why else None
    gate = "measure only" if args.min_activation is None else f"gate >= {args.min_activation}"
    cond = f", env={env}" if env else ""
    print(
        f"running Tier-1b activation via claude (model={args.model}, {gate}{cond})...",
        flush=True,
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            reports = activation.run_activation(
                plugin_dir, run_fn, skills=args.skills,
                workdir=Path(tmp), min_activation=args.min_activation, ask_why=ask,
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
    if args.ask_why:
        _print_why(reports)
    return 0 if all(r.passed for r in reports) else 1


def _print_why(reports: list[activation.ActivationReport]) -> None:
    """The stated reasons: a bucket tally first, then every answer raw — the tally is a lens, the
    text is the evidence."""
    tally: dict[str, int] = {}
    for r in reports:
        for _, answer in r.why:
            b = activation.bucket_why(answer)
            tally[b] = tally.get(b, 0) + 1
    total = sum(tally.values())
    print(f"\n=== why the {total} misses did the work by hand (self-reported) ===")
    for b, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {b:22} {n:3}  ({n / total:.0%})" if total else "")
    for r in reports:
        if not r.why:
            continue
        print(f"\n[{r.skill}]")
        for prompt, answer in r.why:
            flat = " ".join(answer.split())[:260]
            print(f"  - {prompt[:60]}\n      [{activation.bucket_why(answer)}] {flat}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
