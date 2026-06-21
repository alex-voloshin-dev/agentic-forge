"""Tier-2 quality eval runner for subagent roles.

skill-creator evaluates *skills* (with/without-skill deltas, activation/triggering). Subagent
roles are delegated to, not activated, so none of that applies; they need a thin dedicated
runner. This module keeps the agentic-forge policy layer intact — it runs each role on its
fixture tasks, grades the output with the `grader` role, aggregates with
:func:`agentic_forge.benchmark.summarize`, and gates with
:func:`agentic_forge.gate.tier2_quality`.

The model/agent invocation is a seam (:data:`Runner`) so the orchestration is unit-tested
with stubs; the real Anthropic-API and headless-`claude` runners live behind the seam and
are excluded from coverage. See docs/eval-runbook.md and ADR 0011.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import benchmark, gate
from .evals import load_evals
from .frontmatter import parse as parse_frontmatter

ROLES: tuple[str, ...] = ("reviewer", "grader", "implementer", "architect")
DEFAULT_RUNS = 5

# Seam: given (system_prompt, user_prompt, workdir) return the model/agent's text output.
Runner = Callable[[str, str, Path], str]

GRADING_INSTRUCTIONS = (
    "Grade the WORK OUTPUT against each assertion independently; no partial credit. If the "
    "work created files, you MAY read them (read-only) to verify its claims, but never modify "
    "anything. Return ONLY a JSON object: "
    '{"assertion_results":[{"text":"<assertion>","passed":true,"evidence":"<quote>"}],'
    '"summary":{"total":0,"passed":0,"pass_rate":0.0}}'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class RoleReport:
    """The Tier-2 outcome for one role."""

    role: str
    runs: int
    benchmark: dict[str, Any]
    gate: gate.GateResult
    gradings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.gate.passed

    def summary_line(self) -> str:
        ws = (self.benchmark.get("run_summary") or {}).get("with_skill") or {}
        pr = ws.get("pass_rate") or {}
        mean = pr.get("mean", 0.0)
        stddev = pr.get("stddev", 0.0)
        lower = mean - stddev
        status = "PASS" if self.passed else "FAIL"
        detail = "" if self.passed else " — " + "; ".join(self.gate.reasons)
        return (
            f"{self.role}: {status} "
            f"(mean={mean:.3f}, stddev={stddev:.3f}, lower_bound={lower:.3f}, "
            f"n={ws.get('n', 0)}){detail}"
        )


def _read_body(md_path: Path) -> str:
    """Return a role file's system-prompt body (frontmatter stripped)."""
    _, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    return body.strip()


def load_fixtures(plugin_dir: Path, files: list[str]) -> str:
    """Concatenate the case's context files into a labeled block."""
    blocks = []
    for rel in files:
        path = plugin_dir / rel
        blocks.append(f"--- FILE: {rel} ---\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(blocks)


def build_role_prompt(case: dict[str, Any], fixture_text: str) -> str:
    parts = [str(case["prompt"])]
    if fixture_text:
        parts.append("\nContext files:\n" + fixture_text)
    return "\n".join(parts)


def build_grading_prompt(assertions: list[str], output: str) -> str:
    numbered = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(assertions))
    return f"ASSERTIONS:\n{numbered}\n\nWORK OUTPUT:\n{output}\n\n{GRADING_INSTRUCTIONS}"


def parse_grading(text: str) -> dict[str, Any]:
    """Extract the JSON grading object from a grader's (possibly prose-wrapped) reply."""
    match = _JSON_RE.search(text)
    if not match:
        raise ValueError("no JSON object found in grader output")
    data: dict[str, Any] = json.loads(match.group(0))
    return data


def grade_output(
    assertions: list[str], output: str, grader_body: str, run_grader: Runner, workdir: Path
) -> dict[str, Any]:
    """Grade one output against its assertions and return a normalized grading.json mapping."""
    raw = run_grader(grader_body, build_grading_prompt(assertions, output), workdir)
    data = parse_grading(raw)
    results = data.get("assertion_results") or []
    total = len(assertions)
    passed = sum(1 for r in results if r.get("passed") is True)
    data["assertion_results"] = results
    data["summary"] = {
        "total": total,
        "passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
    }
    return data


def check_wiring(role: str, plugin_dir: Path) -> list[str]:
    """Return setup problems for a role without invoking any model. Empty list means ready."""
    problems: list[str] = []
    contract_path = plugin_dir / "agents" / "evals" / f"{role}.evals.json"
    role_path = plugin_dir / "agents" / f"{role}.md"
    if not contract_path.is_file():
        problems.append(f"missing contract: {contract_path}")
    if not role_path.is_file():
        problems.append(f"missing role file: {role_path}")
    if problems:
        return problems
    contract = load_evals(contract_path)
    cases = contract.get("evals") or []
    if not cases:
        problems.append(f"{role}: contract has no eval cases")
    for case in cases:
        cid = case.get("id")
        if not (case.get("assertions") or []):
            problems.append(f"{role} case {cid}: no assertions")
        for rel in case.get("files") or []:
            if not (plugin_dir / rel).is_file():
                problems.append(f"{role} case {cid}: missing fixture {rel}")
    return problems


def run_role(
    role: str,
    plugin_dir: Path,
    *,
    run_role_fn: Runner,
    run_grader_fn: Runner,
    runs: int | None = None,
    workdir: Path | None = None,
    isolate: bool = False,
) -> RoleReport:
    """Run a role's Tier-2 eval: N runs over its cases, graded, aggregated, and gated.

    ``isolate`` gives each case execution a fresh temp workdir (removed afterwards), so write
    roles (implementer/architect) cannot see another run's files — required for independent
    measurement. Read roles don't need it.
    """
    contract = load_evals(plugin_dir / "agents" / "evals" / f"{role}.evals.json")
    role_body = _read_body(plugin_dir / "agents" / f"{role}.md")
    grader_body = _read_body(plugin_dir / "agents" / "grader.md")
    thresholds = contract.get("thresholds") or {}
    n = runs or (thresholds.get("tier2_quality") or {}).get("runs") or DEFAULT_RUNS
    cases = contract.get("evals") or []
    default_work = workdir or plugin_dir

    gradings: list[dict[str, Any]] = []
    for _ in range(n):
        run_results: list[dict[str, Any]] = []
        for case in cases:
            work = Path(tempfile.mkdtemp(prefix="af-eval-")) if isolate else default_work
            try:
                fixture_text = load_fixtures(plugin_dir, case.get("files") or [])
                output = run_role_fn(role_body, build_role_prompt(case, fixture_text), work)
                graded = grade_output(
                    case.get("assertions") or [], output, grader_body, run_grader_fn, work
                )
            finally:
                if isolate:
                    shutil.rmtree(work, ignore_errors=True)
            run_results.extend(graded["assertion_results"])
        total = len(run_results)
        passed = sum(1 for r in run_results if r.get("passed") is True)
        gradings.append(
            {
                "assertion_results": run_results,
                "summary": {
                    "total": total,
                    "passed": passed,
                    "pass_rate": (passed / total) if total else 0.0,
                },
            }
        )

    bench = benchmark.summarize(gradings)
    result = gate.tier2_quality(bench, thresholds)
    return RoleReport(role=role, runs=n, benchmark=bench, gate=result, gradings=gradings)


def api_runner(model: str, *, max_tokens: int = 4096) -> Runner:  # pragma: no cover
    """Level-1 seam: one Anthropic Messages call per task (no tools; lightweight)."""
    import anthropic

    client = anthropic.Anthropic()

    def run(system: str, prompt: str, workdir: Path) -> str:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )

    return run


def claude_cli_runner(
    *,
    allowed_tools: str | None = "Read,Grep,Glob",
    model: str | None = None,
    max_turns: int | None = None,
    retries: int = 3,
    call_timeout: int = 900,
) -> Runner:  # pragma: no cover
    """Level-2 seam: run the role headlessly via `claude -p` (Claude Code auth).

    Uses whatever auth the `claude` CLI is configured with — a Claude subscription via
    CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`), or ANTHROPIC_API_KEY (which takes
    precedence if set, billing per token). Tools run for real in ``workdir``, so
    implementer/architect get level-2 fidelity. ``allowed_tools`` semantics: ``None`` omits
    the flag (CLI default tools); ``""`` passes an empty allowlist that **disables** tools
    (use for grading, which must not call tools); a list grants exactly those. Retries with
    backoff on a failed/timed-out call so a long multi-call run survives transient errors;
    prints a '.' heartbeat per call.
    """
    import subprocess
    import sys
    import time

    def run(system: str, prompt: str, workdir: Path) -> str:
        cmd = ["claude", "-p", prompt, "--append-system-prompt", system, "--output-format", "text"]
        if allowed_tools is not None:
            cmd += ["--allowedTools", allowed_tools]
        if model:
            cmd += ["--model", model]
        if max_turns is not None:
            cmd += ["--max-turns", str(max_turns)]
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=call_timeout,
                )
                print(".", end="", flush=True, file=sys.stderr)
                return completed.stdout
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(15 * (attempt + 1))
        assert last_exc is not None
        out = (getattr(last_exc, "output", "") or "")[-400:]
        err = (getattr(last_exc, "stderr", "") or "")[-400:]
        raise RuntimeError(
            f"claude call failed after {retries + 1} attempts: {last_exc}: "
            f"stdout={out!r} stderr={err!r}"
        )

    return run
