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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import benchmark, gate
from .evals import eval_case_problems, load_evals
from .frontmatter import parse as parse_frontmatter

__all__ = [
    "ROLES",
    "DEFAULT_RUNS",
    "GRADING_INSTRUCTIONS",
    "Runner",
    "RunOutput",
    "RoleReport",
    "is_write_role",
    "load_fixtures",
    "materialize_fixtures",
    "build_role_prompt",
    "build_grading_prompt",
    "json_objects",
    "parse_grading",
    "grade_output",
    "check_wiring",
    "run_eval_cases",
    "run_role",
    "api_runner",
    "claude_cli_runner",
]

ROLES: tuple[str, ...] = (
    "reviewer",
    "grader",
    "software-engineer",
    "architect",
    "security-engineer",
    "qa-engineer",
)
DEFAULT_RUNS = 5

# Seam: given (system_prompt, user_prompt, workdir) return the model/agent's text output.
# A transport may return a RunOutput (a str subclass) to also report token usage; everything else
# treats the reply as a plain str, so the seam type is unchanged.
Runner = Callable[[str, str, Path], str]


class RunOutput(str):
    """A model reply that may carry token usage. It **is** a ``str`` — every existing consumer
    (grading, JSON parsing, equality, the ``Runner`` type) treats it as the reply text — so a
    transport can opt into reporting usage with no signature change. The Tier-2 timing capture
    reads ``.usage`` (``{input_tokens, output_tokens, total_tokens}``) when present to compute the
    token-overhead delta (ADR 0036/0038). A plain ``str`` (stubs, a text-only transport) carries
    no usage, so token-overhead stays unmeasured for it.
    """

    usage: dict[str, int] | None

    def __new__(cls, text: str, usage: dict[str, int] | None = None) -> RunOutput:
        obj = super().__new__(cls, text)
        obj.usage = usage
        return obj


def _usage_from_counts(input_tokens: int, output_tokens: int) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _usage_tokens(output: str) -> int | None:
    """Total tokens for one model reply, or None if the transport reported no usage."""
    usage = getattr(output, "usage", None)
    if isinstance(usage, dict):
        return int(usage.get("total_tokens", 0) or 0)
    return None


def _parse_cli_json(stdout: str) -> RunOutput:
    """Parse `claude -p --output-format json` stdout into the reply text + token usage.

    The expected shape is ``{"result": "<text>", "usage": {"input_tokens", "output_tokens", …}}``.
    Degrades to the raw stdout with no usage if it is not that result-bearing JSON, so an odd or
    older CLI output can never crash a Tier-2 sweep (ADR 0038)."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return RunOutput(stdout)
    if not isinstance(data, dict) or "result" not in data:
        return RunOutput(stdout)
    usage = data.get("usage")
    if isinstance(usage, dict):
        counts = _usage_from_counts(
            int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
        )
        return RunOutput(str(data["result"]), counts)
    return RunOutput(str(data["result"]))

GRADING_INSTRUCTIONS = (
    "Grade the WORK OUTPUT against each assertion independently; no partial credit. If the "
    "work created files, you MAY read them (read-only) to verify its claims, but never modify "
    "anything. Return ONLY a JSON object: "
    '{"assertion_results":[{"text":"<assertion>","passed":true,"evidence":"<quote>"}],'
    '"summary":{"total":0,"passed":0,"pass_rate":0.0}}'
)

def _json_candidates(text: str) -> list[str]:
    """Yield JSON-object candidate substrings from a possibly prose/fence-wrapped reply.

    Prefers fenced ```json blocks, then balanced ``{...}`` spans (braces inside strings are
    ignored). This is robust where a greedy ``\\{.*\\}`` regex was not — a stray brace or
    surrounding prose can no longer corrupt the extracted object.
    """
    candidates: list[str] = [
        m.group(1) for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    ]
    # Single left-to-right pass with a brace stack: O(n), where the old per-'{' rescan was O(n^2)
    # (a brace-heavy adversarial reply could stall a Tier-2 sweep). Spans are ordered outer-first
    # (by start index) to match the old scan order, so grade_output still tries the outermost
    # object first; braces inside strings are ignored.
    spans: list[tuple[int, str]] = []
    stack: list[int] = []
    in_str = False
    esc = False
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            stack.append(i)
        elif c == "}" and stack:
            start = stack.pop()
            spans.append((start, text[start : i + 1]))
    candidates.extend(span for _, span in sorted(spans, key=lambda s: s[0]))
    return candidates


@dataclass
class RoleReport:
    """The Tier-2 outcome for one role."""

    role: str
    runs: int
    benchmark: dict[str, Any]
    gate: gate.GateResult
    gradings: list[dict[str, Any]] = field(default_factory=list)
    thresholds: dict[str, Any] = field(default_factory=dict)  # for the version-over-version check

    @property
    def passed(self) -> bool:
        return self.gate.passed

    def summary_line(self) -> str:
        return gate.format_tier2_summary(
            self.role, passed=self.passed, benchmark=self.benchmark, reasons=self.gate.reasons
        )


def _read_body(md_path: Path) -> str:
    """Return a role file's system-prompt body (frontmatter stripped)."""
    _, body = parse_frontmatter(md_path.read_text(encoding="utf-8"))
    return body.strip()


def is_write_role(plugin_dir: Path, role: str) -> bool:
    """True if the role's frontmatter grants Write/Edit.

    Such roles can mutate files, so they MUST run isolated (a fresh per-case workdir) — never
    against the real repo. run_role enforces this regardless of the caller's ``isolate`` flag.
    """
    fm, _ = parse_frontmatter((plugin_dir / "agents" / f"{role}.md").read_text(encoding="utf-8"))
    tools = str(fm.get("tools", ""))
    return "Write" in tools or "Edit" in tools


def load_fixtures(plugin_dir: Path, files: list[str]) -> str:
    """Concatenate the case's context files into a labeled block.

    Files are labeled by **basename**, not their repo-relative path, so a prompt never hands a
    role a path it could resolve back to the real repository (see materialize_fixtures).
    """
    blocks = []
    for rel in files:
        path = plugin_dir / rel
        blocks.append(f"--- FILE: {Path(rel).name} ---\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(blocks)


def materialize_fixtures(plugin_dir: Path, files: list[str], workdir: Path) -> None:
    """Copy a case's fixture files into the sandbox workdir (by basename).

    An isolated role then works on these copies in its own working directory and can never
    reach — or mutate — the real fixture files in the repo. This is the isolation guarantee for
    write roles (software-engineer, architect, qa-engineer).
    """
    for rel in files:
        (workdir / Path(rel).name).write_text(
            (plugin_dir / rel).read_text(encoding="utf-8"), encoding="utf-8"
        )


def build_role_prompt(
    case: dict[str, Any], fixture_text: str, *, in_workdir: bool = False
) -> str:
    parts = [str(case["prompt"])]
    if fixture_text:
        header = (
            "\nThese files are in your working directory — do the task there:\n"
            if in_workdir
            else "\nContext files:\n"
        )
        parts.append(header + fixture_text)
    return "\n".join(parts)


def build_grading_prompt(assertions: list[str], output: str) -> str:
    numbered = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(assertions))
    return f"ASSERTIONS:\n{numbered}\n\nWORK OUTPUT:\n{output}\n\n{GRADING_INSTRUCTIONS}"


def json_objects(text: str) -> list[dict[str, Any]]:
    """Every JSON object parseable from ``text`` (prose/fence-tolerant, outer-first). Used where a
    reply may contain several JSON objects and the caller must pick the right-shaped one."""
    objects: list[dict[str, Any]] = []
    for cand in _json_candidates(text):
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        # _json_candidates only yields `{...}` object spans, so a parsed candidate is always a
        # dict; the guard is defensive depth, and its false edge is unreachable (no-branch).
        if isinstance(data, dict):  # pragma: no branch
            objects.append(data)
    return objects


def parse_grading(text: str) -> dict[str, Any]:
    """Extract the (first) JSON grading object from a possibly prose/fence-wrapped grader reply."""
    objects = json_objects(text)
    if objects:
        return objects[0]
    raise ValueError("no valid JSON object found in grader output")


def grade_output(
    assertions: list[str], output: str, grader_body: str, run_grader: Runner, workdir: Path
) -> dict[str, Any]:
    """Grade one output against its assertions and return a normalized grading.json mapping."""
    prompt = build_grading_prompt(assertions, output)
    raw = run_grader(grader_body, prompt, workdir)
    try:
        data = parse_grading(raw)
    except ValueError:
        # One retry with a stronger instruction — graders occasionally wrap JSON in prose.
        stricter = prompt + "\n\nReturn ONLY the JSON object — no prose, no code fences."
        raw = run_grader(grader_body, stricter, workdir)
        data = parse_grading(raw)
    results = data.get("assertion_results") or []
    total = len(assertions)
    # Cap at the assertion count: a grader that returns extra/duplicate results must not push
    # passed > total (pass_rate > 1.0 would inflate the Tier-2 gate). Missing results are
    # implicitly failures because total is the assertion count, not len(results).
    passed = min(sum(1 for r in results if r.get("passed") is True), total)
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
    problems += eval_case_problems(role, contract.get("evals") or [], plugin_dir)
    return problems


def _run_passes(
    system_body: str,
    cases: list[dict[str, Any]],
    *,
    run_fn: Runner,
    grader_body: str,
    grader_fn: Runner,
    plugin_dir: Path,
    runs: int,
    isolate: bool,
    workdir: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute ``cases`` ``runs`` times under ``system_body``; return ``(gradings, timing)``.

    ``timing`` carries one entry per run: ``{"duration_ms": …}`` (wall-clock for that run's cases),
    plus ``"total_tokens"`` when the transport reports usage (a :class:`RunOutput` — see ADR 0038).
    Only the component (``run_fn``) tokens are summed, not the grader's, so the Tier-2 A-B delta
    reflects the skill's own token cost. A text-only transport reports no usage, so ``total_tokens``
    is simply absent and token-overhead stays unmeasured.
    """
    default_work = workdir or plugin_dir
    gradings: list[dict[str, Any]] = []
    timing: list[dict[str, Any]] = []
    for _ in range(runs):
        run_results: list[dict[str, Any]] = []
        run_total = 0
        run_passed = 0
        run_tokens = 0
        saw_usage = False
        started = time.monotonic()
        for case in cases:
            work = Path(tempfile.mkdtemp(prefix="af-eval-")) if isolate else default_work
            try:
                case_files = case.get("files") or []
                fixture_text = load_fixtures(plugin_dir, case_files)
                if isolate:
                    materialize_fixtures(plugin_dir, case_files, work)
                output = run_fn(
                    system_body, build_role_prompt(case, fixture_text, in_workdir=isolate), work
                )
                tokens = _usage_tokens(output)
                if tokens is not None:
                    saw_usage = True
                    run_tokens += tokens
                graded = grade_output(
                    case.get("assertions") or [], output, grader_body, grader_fn, work
                )
            finally:
                if isolate:
                    shutil.rmtree(work, ignore_errors=True)
            run_results.extend(graded["assertion_results"])
            # Aggregate over EXPECTED assertion counts (grade_output's summary), not len(results)
            # — so a grader that omits or duplicates results can't skew the run's pass-rate.
            run_total += graded["summary"]["total"]
            run_passed += graded["summary"]["passed"]
        entry: dict[str, Any] = {"duration_ms": (time.monotonic() - started) * 1000.0}
        if saw_usage:
            entry["total_tokens"] = run_tokens
        timing.append(entry)
        gradings.append(
            {
                "assertion_results": run_results,
                "summary": {
                    "total": run_total,
                    "passed": run_passed,
                    "pass_rate": (run_passed / run_total) if run_total else 0.0,
                },
            }
        )
    return gradings, timing


def run_eval_cases(
    *,
    system_body: str,
    grader_body: str,
    cases: list[dict[str, Any]],
    thresholds: dict[str, Any],
    plugin_dir: Path,
    run_fn: Runner,
    grader_fn: Runner,
    runs: int,
    isolate: bool,
    workdir: Path | None = None,
    baseline_system_body: str | None = None,
) -> tuple[dict[str, Any], gate.GateResult, list[dict[str, Any]]]:
    """Shared Tier-2 core: run ``cases`` ``runs`` times under ``system_body``, grade each output
    against its assertions, aggregate, and gate. Returns ``(benchmark, gate_result, gradings)``.

    Per-run wall-clock timing is always captured and fed to the benchmark. When
    ``baseline_system_body`` is given, every case is ALSO run under it — the same executor with the
    skill under test removed — to produce the with/without A-B pass-rate lift and the time-overhead
    delta that :func:`gate.tier2_quality` checks (ADR 0036). A subagent role passes no baseline
    (it has no "without itself").

    ``isolate`` gives each case a fresh temp workdir (removed after) so a write component never
    sees another run's files or the real repo. Used by both the role runner (:func:`run_role`)
    and the skill runner (``skill_eval.run_skill``).
    """
    gradings, timing = _run_passes(
        system_body,
        cases,
        run_fn=run_fn,
        grader_body=grader_body,
        grader_fn=grader_fn,
        plugin_dir=plugin_dir,
        runs=runs,
        isolate=isolate,
        workdir=workdir,
    )
    if baseline_system_body is not None:
        base_gradings, base_timing = _run_passes(
            baseline_system_body,
            cases,
            run_fn=run_fn,
            grader_body=grader_body,
            grader_fn=grader_fn,
            plugin_dir=plugin_dir,
            runs=runs,
            isolate=isolate,
            workdir=workdir,
        )
        bench = benchmark.summarize(
            gradings,
            base_gradings,
            with_skill_timing=timing,
            without_skill_timing=base_timing,
        )
    else:
        bench = benchmark.summarize(gradings, with_skill_timing=timing)
    result = gate.tier2_quality(bench, thresholds)
    return bench, result, gradings


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

    ``isolate`` gives each case execution a fresh temp workdir (removed afterwards), so a run
    cannot see another run's files. It is **forced on for write roles** (software-engineer,
    architect, qa-engineer — anything with Write/Edit) so they can never mutate the real repo,
    regardless of the caller's flag. Read roles don't need it.
    """
    contract = load_evals(plugin_dir / "agents" / "evals" / f"{role}.evals.json")
    role_body = _read_body(plugin_dir / "agents" / f"{role}.md")
    grader_body = _read_body(plugin_dir / "agents" / "grader.md")
    if not isolate and is_write_role(plugin_dir, role):
        isolate = True  # safety: a write role must never run against the real repo
    thresholds = contract.get("thresholds") or {}
    if runs is not None and runs <= 0:
        raise ValueError("runs must be a positive integer")
    contract_runs = (thresholds.get("tier2_quality") or {}).get("runs") or DEFAULT_RUNS
    n = runs if runs is not None else contract_runs
    cases = contract.get("evals") or []
    bench, result, gradings = run_eval_cases(
        system_body=role_body,
        grader_body=grader_body,
        cases=cases,
        thresholds=thresholds,
        plugin_dir=plugin_dir,
        run_fn=run_role_fn,
        grader_fn=run_grader_fn,
        runs=n,
        isolate=isolate,
        workdir=workdir,
    )
    return RoleReport(
        role=role, runs=n, benchmark=bench, gate=result, gradings=gradings, thresholds=thresholds
    )


def api_runner(model: str, *, max_tokens: int = 4096) -> Runner:
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
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(message, "usage", None)
        if usage is None:
            return RunOutput(text)
        return RunOutput(
            text,
            _usage_from_counts(
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
            ),
        )

    return run


def claude_cli_runner(
    *,
    allowed_tools: str | None = "Read,Grep,Glob",
    model: str | None = None,
    max_turns: int | None = None,
    retries: int = 3,
    call_timeout: int = 900,
    replace_system: bool = False,
) -> Runner:
    """Level-2 seam: run the role headlessly via `claude -p` (Claude Code auth).

    Uses whatever auth the `claude` CLI is configured with — a Claude subscription via
    CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`), or ANTHROPIC_API_KEY (which takes
    precedence if set, billing per token). Tools run for real in ``workdir``, so
    software-engineer/architect get level-2 fidelity. ``allowed_tools`` semantics: ``None`` omits
    the flag (CLI default tools); ``""`` passes an empty allowlist that **disables** tools
    (use for grading, which must not call tools); a list grants exactly those. Retries with
    backoff on a failed/timed-out call so a long multi-call run survives transient errors;
    prints a '.' heartbeat per call.

    ``replace_system`` picks which flag carries ``system`` (ADR 0064):

    * ``False`` (default) — ``--append-system-prompt``: the role runs *on top of* Claude Code's
      default agent prompt. Right for **role** evals (Tier-2), where the role is an agent.
    * ``True`` — ``--system-prompt``: the given text becomes the whole system prompt. Right for
      **classification** (Tier-1 routing), where inheriting an agent persona makes the model behave
      like one — exploring and answering in prose instead of emitting a single skill name. That
      off-format reply was previously scored as a routing decision; the parser now rejects it, and
      this flag reduces how often it happens.

    Note the limit: this controls the *system prompt*, not the CLI's user-level ``CLAUDE.md``
    auto-discovery, which still applies. Only ``--bare`` disables that, and it forces
    ``ANTHROPIC_API_KEY`` auth — which would break the subscription-billed path the runbook
    recommends — so it is deliberately not used here.
    """
    import subprocess
    import sys
    import time

    system_flag = "--system-prompt" if replace_system else "--append-system-prompt"

    def run(system: str, prompt: str, workdir: Path) -> str:
        # `--setting-sources project` drops the OPERATOR's user-level settings and `CLAUDE.md`
        # (ADR 0077). Without it an eval inherits whoever is running it: a personal "always answer
        # in <language>" rule reached the graded artifacts here, so the same case scored differently
        # on different machines. Project settings stay — they are part of the repo under test.
        cmd = ["claude", "-p", prompt, system_flag, system, "--output-format", "json"]
        cmd += ["--setting-sources", "project"]
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
                return _parse_cli_json(completed.stdout)
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
