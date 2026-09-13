#!/usr/bin/env python3
"""Tier-1b activation eval (ADR 0088): does a live Claude Code session invoke the skill unprompted?

Runs each on-listing skill's should_trigger prompts through a real ``claude -p`` session with the
plugin loaded, and scans the transcript for a ``Skill`` tool call naming that skill. Reports the
activation rate per skill and POOLED over the run; a MEASUREMENT by default — ``--min-activation``
gates the pooled rate (per-skill n is 4-9, too small to gate; ADR 0093). Wiring dry-run needs no
credentials.
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
            # A session that ran out of `timeout` counts as a miss unless it had already invoked
            # the skill — so its partial transcript is kept (bytes on POSIX whatever the text
            # mode; it used to be dropped, so the Skill call and the session id went with it) and
            # the progress line shows "T", not nothing: two silent timeouts once read as two
            # `research` misses with no reason attached (ADR 0093).
            print("T", end="", flush=True, file=sys.stderr)
            out = exc.stdout
            return out.decode("utf-8", "replace") if isinstance(out, bytes) else (out or "")
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
    # 4, not 3: at 3 the cap stopped `develop` between reading the plan and invoking the skill
    # (ADR 0091) — investigate-first skills need one more turn to reach the decision.
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--empty-workdir", action="store_true",
        help="Run every prompt in an EMPTY temp dir (the condition of the first runs, kept only "
        "to reproduce them). Default: a fresh fixture repo per prompt (ADR 0090).",
    )
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
        help="Gate: fail when the rate POOLED over every prompt in the run is below this — one "
        "binomial, not seventeen (per-skill n is 4-9; the per-skill lines are a lens, ADR 0093). "
        "Omit to MEASURE only (the default).",
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
    floor = args.min_activation
    gate = "measure only" if floor is None else f"pooled gate >= {floor}"
    stand = ", EMPTY workdir" if args.empty_workdir else ", fixture repo per prompt"
    cond = (f", env={env}" if env else "") + stand
    print(
        f"running Tier-1b activation via claude (model={args.model}, {gate}{cond})...",
        flush=True,
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            counter = [0]

            def fresh_workspace() -> Path:  # pragma: no cover -- exercised by the lib's own test
                counter[0] += 1
                return activation.prepare_workspace(plugin_dir, Path(tmp) / f"p{counter[0]}")

            reports = activation.run_activation(
                plugin_dir, run_fn, skills=args.skills,
                workdir=Path(tmp), ask_why=ask,
                workspace_factory=None if args.empty_workdir else fresh_workspace,
            )
    except Exception as exc:  # a crash (mis-wired plugin) — record, then fail
        print(f"Tier-1b ERROR — {exc}", flush=True)
        _eval_cli.record_failure("tier1b-activation", f"{type(exc).__name__}: {exc}")
        return 1

    verdict = activation.pooled(reports, args.min_activation)
    for report in sorted(reports, key=lambda r: r.rate):  # weakest first: the lens
        print(report.summary_line(), flush=True)
    for report in reports:  # a session that never ran is out of the rate, never out of sight
        for prompt, error in report.undetermined:
            print(f"  never ran [{report.skill}] {prompt[:60]}: {error}", flush=True)
    print(f"\n{verdict.summary_line()}", flush=True)
    if not verdict.passed:
        _eval_cli.record_failure("tier1b-activation", "; ".join(verdict.reasons), kind="anomaly")
    if args.ask_why:
        _print_why(reports)
    return 0 if verdict.passed else 1


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
