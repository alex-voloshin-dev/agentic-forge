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
from .evals import eval_case_problems, fixture_dest, load_evals
from .frontmatter import parse as parse_frontmatter

__all__ = [
    "ROLES",
    "DEFAULT_RUNS",
    "GRADING_INSTRUCTIONS",
    "Runner",
    "RunOutput",
    "RoleReport",
    "SessionUndetermined",
    "TurnCapHit",
    "SessionTimedOut",
    "GradingUnparseable",
    "session_outcome",
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


class SessionUndetermined(RuntimeError):
    """The session produced no reply to grade — and would not on a retry.

    An API error (``is_error`` in the CLI envelope), a usage-limit refusal, a session with no
    assistant turn, a ``--max-turns`` cap (:class:`TurnCapHit`), a timeout
    (:class:`SessionTimedOut`) or an API reply cut at ``max_tokens``. Neither a pass nor a fail:
    the component never decided anything, so every tier records the case as *undetermined* — out
    of the rate, counted, and capped by :data:`gate.MAX_UNDETERMINED` (ADR 0093's ``session_ran``
    rule, applied to every runner). A ``RuntimeError``, so a caller that only knows the old
    contract still catches it.

    ``subtype`` is the CLI's own word for what happened (``error_max_turns``, ``error`` …) or a
    synthesized one (``api_error_404``, ``no_turns``, ``timeout``, ``max_tokens``); ``text`` is what
    the session said, flattened and capped; ``num_turns`` is the envelope's count when it has one.
    """

    marker = "!"  # printed on the progress line in place of the '.' heartbeat

    def __init__(self, subtype: str, text: str = "", *, num_turns: int | None = None) -> None:
        self.subtype = subtype
        self.text = text
        self.num_turns = num_turns
        turns = f", num_turns={num_turns}" if num_turns is not None else ""
        super().__init__(f"session undetermined ({subtype}{turns}): {text or '<no result text>'}")


class TurnCapHit(SessionUndetermined):
    """``--max-turns`` reached mid-task (``subtype: error_max_turns``, no ``result`` key). It is
    deterministic — the same prompt at the same cap hits it again — and a re-run in the same
    workdir would let a write role see its own partial files, so it is never retried."""

    marker = "C"


class SessionTimedOut(SessionUndetermined):
    """``call_timeout`` elapsed on every attempt a timeout gets (one retry by default). ``text``
    keeps the tail of the partial stdout — decoded from the bytes ``TimeoutExpired`` carries on
    POSIX whatever the text mode, which used to be dropped to a 400-char repr."""

    marker = "T"


_TEXT_CAP = 200  # a result text, flattened, for a message or an event
_TAIL = 1000  # of a failed call's stdout/stderr kept in the raised message


def _flat(text: object, cap: int = _TEXT_CAP) -> str:
    return " ".join(str(text).split())[:cap]


def _decoded(value: object) -> str:
    """A subprocess exception's captured output as text: bytes on POSIX for a killed process
    whatever the text mode, str otherwise, "" when absent."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value) if value else ""


def session_outcome(stdout: str) -> SessionUndetermined | None:
    """Read a ``claude -p --output-format json`` envelope for a session that never produced a
    gradable reply; ``None`` when it did — or when ``stdout`` is not an envelope at all, which is a
    transport failure and the caller's business.

    Measured on Claude Code 2.1.270 (the eval audit): an API error exits 1 with ``{"is_error":
    true, "subtype": "success", "api_error_status": 404, "result": "…"}``; a ``--max-turns`` hit
    exits 1 with ``{"is_error": true, "subtype": "error_max_turns", "terminal_reason":
    "max_turns"}`` and NO ``result``; a usage-limit refusal arrives as the ``result`` text with no
    assistant turn and an exit code that is not pinned down. So the envelope is read on the
    failure AND the success path, and ``num_turns == 0`` — the ``json`` format's "no assistant
    turn" (:func:`activation.session_ran` for a stream) — counts as never having run."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    subtype = str(data.get("subtype") or "")
    turns = data.get("num_turns")
    num_turns = turns if isinstance(turns, int) and not isinstance(turns, bool) else None
    text = _flat(data.get("result") or data.get("error") or "")
    if subtype == "error_max_turns" or data.get("terminal_reason") == "max_turns":
        return TurnCapHit(subtype or "error_max_turns", text, num_turns=num_turns)
    if data.get("is_error"):
        if subtype in ("", "success"):  # the API-error shape: flagged, but subtype says success
            status = data.get("api_error_status")
            subtype = f"api_error_{status}" if status is not None else "error"
        return SessionUndetermined(subtype, text, num_turns=num_turns)
    if subtype and subtype != "success":
        return SessionUndetermined(subtype, text, num_turns=num_turns)
    if num_turns == 0:
        return SessionUndetermined("no_turns", text, num_turns=0)
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

    def evidence_lines(self) -> list[str]:
        """The sessions that produced no measurement, one line each (run, case, subtype,
        ``num_turns``) — printed under the summary line by the CLI."""
        return gate.tier2_evidence_lines(self.benchmark)


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

    Files are labeled by their **sandbox destination** (:func:`fixture_dest` — the basename, or
    the path below a ``tree/`` segment), never their repo-relative path, so a prompt never hands
    a role a path it could resolve back to the real repository (see materialize_fixtures).
    """
    blocks = []
    for rel in files:
        path = plugin_dir / rel
        blocks.append(f"--- FILE: {fixture_dest(rel)} ---\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(blocks)


def materialize_fixtures(plugin_dir: Path, files: list[str], workdir: Path) -> None:
    """Copy a case's fixture files into the sandbox workdir — by basename, or with their layout
    below a ``tree/`` segment (:func:`fixture_dest`), so a case can seed ``src/lib.rs`` or a
    ``plugin/agents/`` skeleton rather than a flat pile.

    An isolated role then works on these copies in its own working directory and can never
    reach — or mutate — the real fixture files in the repo. This is the isolation guarantee for
    write roles (software-engineer, architect, qa-engineer).
    """
    for rel in files:
        target = workdir / fixture_dest(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((plugin_dir / rel).read_text(encoding="utf-8"), encoding="utf-8")


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


class GradingUnparseable(ValueError):
    """The grader's reply carried no ``{"assertion_results": [...]}`` object, even after the retry
    with a stricter instruction. The case is *ungraded* — not scored 0 (a 0 says the work failed
    every assertion; nobody checked it) but counted, printed on the summary line and capped with
    the undetermined sessions (eval audit, C5)."""


def parse_grading(text: str) -> dict[str, Any]:
    """The grading object — the FIRST JSON object carrying an ``assertion_results`` list — from a
    possibly prose/fence-wrapped grader reply.

    Shape-aware on purpose: the first *parseable* object used to be taken whatever it was, so a
    grader that wrote another object before its grading (an echo of the assertions, a plan) had
    THAT scored — 0/N, silently. Raises :class:`GradingUnparseable` when no object has the shape.
    """
    for obj in json_objects(text):
        if isinstance(obj.get("assertion_results"), list):
            return obj
    raise GradingUnparseable(
        "no valid JSON grading object (an assertion_results list) in the grader output"
    )


def grade_output(
    assertions: list[str], output: str, grader_body: str, run_grader: Runner, workdir: Path
) -> dict[str, Any]:
    """Grade one output against its assertions and return a normalized grading.json mapping.

    Raises :class:`GradingUnparseable` when neither the grader's reply nor its one retry (with a
    stricter instruction — graders occasionally wrap the JSON in prose or emit another object
    first) carries a grading object; the run loop records the case as ungraded."""
    prompt = build_grading_prompt(assertions, output)
    raw = run_grader(grader_body, prompt, workdir)
    try:
        data = parse_grading(raw)
    except GradingUnparseable:
        stricter = prompt + "\n\nReturn ONLY the JSON object — no prose, no code fences."
        raw = run_grader(grader_body, stricter, workdir)
        data = parse_grading(raw)
    results = data.get("assertion_results") or []
    total = len(assertions)
    # Cap at the assertion count: a grader that returns extra/duplicate results must not push
    # passed > total (pass_rate > 1.0 would inflate the Tier-2 gate). Missing results are
    # implicitly failures because total is the assertion count, not len(results). `passed` is read
    # by `benchmark.passed_value`: True and the spellings a model reaches for ("true", "PASS",
    # "passed"), never "false" — a "PASS" used to score as a fail (eval audit, C5).
    passed = min(sum(1 for r in results if benchmark.passed_value(r.get("passed"))), total)
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


def _new_sessions() -> dict[str, Any]:
    return {"total": 0, "undetermined": 0, "ungraded": 0, "subtypes": {}, "events": []}


def _record_unmeasured(
    sessions: dict[str, Any], kind: str, run_no: int, case_no: int, exc: Exception
) -> None:
    """Tally a session that produced no measurement: ``kind`` is ``undetermined`` (the component
    never answered — :class:`SessionUndetermined`) or ``ungraded`` (the grader never graded —
    :class:`GradingUnparseable`, or a :class:`SessionUndetermined` raised by the grader's own
    session). The event keeps run/case, the subtype, ``num_turns`` and what
    was said, so the CLI can print WHY under the summary line (ADR 0084's rule)."""
    sessions[kind] += 1
    dead = exc if isinstance(exc, SessionUndetermined) else None
    subtype = dead.subtype if dead is not None else "grading-unparseable"
    if dead is not None:
        sessions["subtypes"][subtype] = sessions["subtypes"].get(subtype, 0) + 1
    event: dict[str, Any] = {
        "run": run_no,
        "case": case_no,
        "kind": kind,
        "subtype": subtype,
        "text": _flat(dead.text if dead is not None else str(exc), 160),
    }
    if dead is not None and dead.num_turns is not None:
        event["num_turns"] = dead.num_turns
    sessions["events"].append(event)


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Execute ``cases`` ``runs`` times under ``system_body``; return ``(gradings, timing,
    sessions)``.

    ``timing`` carries one entry per run: ``{"duration_ms": …}`` (wall-clock for that run's cases),
    plus ``"total_tokens"`` when the transport reports usage (a :class:`RunOutput` — see ADR 0038).
    Only the component (``run_fn``) tokens are summed, not the grader's, so the Tier-2 A-B delta
    reflects the skill's own token cost. A text-only transport reports no usage, so ``total_tokens``
    is simply absent and token-overhead stays unmeasured.

    ``sessions`` is the tally of sessions that produced no measurement: a case whose session
    raised :class:`SessionUndetermined` (never answered) or whose grading was
    :class:`GradingUnparseable` (never graded) is left out of that run's pass-rate — neither a pass
    nor a fail (ADR 0093) — counted under ``undetermined`` / ``ungraded`` with its ``subtypes``
    and one ``events`` entry each. Before this, one dead session raised out of the loop and the
    whole role was printed as ERROR with every finished session ungraded (eval audit, C8/C13).
    """
    default_work = workdir or plugin_dir
    gradings: list[dict[str, Any]] = []
    timing: list[dict[str, Any]] = []
    sessions = _new_sessions()
    for run_no in range(1, runs + 1):
        run_results: list[dict[str, Any]] = []
        run_total = 0
        run_passed = 0
        run_tokens = 0
        saw_usage = False
        graded_cases = 0
        started = time.monotonic()
        for case_no, case in enumerate(cases, start=1):
            sessions["total"] += 1
            work = Path(tempfile.mkdtemp(prefix="af-eval-")) if isolate else default_work
            try:
                case_files = case.get("files") or []
                fixture_text = load_fixtures(plugin_dir, case_files)
                if isolate:
                    materialize_fixtures(plugin_dir, case_files, work)
                try:
                    output = run_fn(
                        system_body, build_role_prompt(case, fixture_text, in_workdir=isolate), work
                    )
                except SessionUndetermined as exc:
                    _record_unmeasured(sessions, "undetermined", run_no, case_no, exc)
                    continue
                try:
                    graded = grade_output(
                        case.get("assertions") or [], output, grader_body, grader_fn, work
                    )
                except (GradingUnparseable, SessionUndetermined) as exc:
                    # Either way the case was never graded. SessionUndetermined here is the
                    # GRADER's session — a usage limit, or its own turn cap. ADR 0094 caught it
                    # for the component call and for the grading PARSE but not for this one, so a
                    # grader that hit its cap still aborted the whole skill with every finished
                    # session discarded — the exact behaviour that fix set out to remove. Found by
                    # running the gate on the content that fix changed (ADR 0094, amended).
                    _record_unmeasured(sessions, "ungraded", run_no, case_no, exc)
                    continue
            finally:
                if isolate:
                    shutil.rmtree(work, ignore_errors=True)
            tokens = _usage_tokens(output)
            if tokens is not None:
                saw_usage = True
                run_tokens += tokens
            graded_cases += 1
            run_results.extend(graded["assertion_results"])
            # Aggregate over EXPECTED assertion counts (grade_output's summary), not len(results)
            # — so a grader that omits or duplicates results can't skew the run's pass-rate.
            run_total += graded["summary"]["total"]
            run_passed += graded["summary"]["passed"]
        if cases and not graded_cases:
            # Every session of this run went unmeasured: there is no run to summarize. It leaves
            # `n` (so the runs floor sees it) and the cap says why — a 0.0 here would be the
            # fabricated failure ADR 0093 refused for Tier-1b.
            continue
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
    return gradings, timing, sessions


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

    Sessions that produced no measurement (see :func:`_run_passes`) ride along in the benchmark
    under ``run_summary.with_skill.sessions``; :func:`gate.tier2_quality` fails the run when more
    than :data:`gate.MAX_UNDETERMINED` of them went unmeasured, and the summary line prints the
    count either way.
    """
    gradings, timing, sessions = _run_passes(
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
        base_gradings, base_timing, base_sessions = _run_passes(
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
            with_skill_sessions=sessions,
            without_skill_sessions=base_sessions,
        )
    else:
        bench = benchmark.summarize(
            gradings, with_skill_timing=timing, with_skill_sessions=sessions
        )
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
    """Level-1 seam: one Anthropic Messages call per task (no tools; lightweight).

    A reply the API cut at ``max_tokens`` (``stop_reason == "max_tokens"``) is raised as
    :class:`SessionUndetermined` (``subtype: max_tokens``) rather than graded: grading a truncated
    artifact grades the cap, not the role, and ``stop_reason`` used to go unread (eval audit, C13).
    """
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
        if getattr(message, "stop_reason", None) == "max_tokens":
            raise SessionUndetermined(
                "max_tokens", f"reply cut at max_tokens={max_tokens}; tail: {_flat(text[-200:])}"
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
    timeout_retries: int = 1,
) -> Runner:
    """Level-2 seam: run the role headlessly via `claude -p` (Claude Code auth).

    Uses whatever auth the `claude` CLI is configured with — a Claude subscription via
    CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`), or ANTHROPIC_API_KEY (which takes
    precedence if set, billing per token). Tools run for real in ``workdir``, so
    software-engineer/architect get level-2 fidelity. ``allowed_tools`` semantics: ``None`` omits
    the flag (CLI default tools); ``""`` passes an empty allowlist that **disables** tools
    (use for grading, which must not call tools); a list grants exactly those. Prints a '.'
    heartbeat per successful call.

    What a failed call means decides whether it is retried (eval audit, C7/C8/C13/C14):

    * The session **answered "no"** — the ``--output-format json`` envelope says ``is_error``, a
      non-``success`` ``subtype`` (a ``--max-turns`` hit is ``error_max_turns``), or no assistant
      turn (:func:`session_outcome`, read on the failure and the success path alike). That is a
      refusal or deterministic, so it is raised at once as :class:`SessionUndetermined` — ``C`` on
      the progress line for a cap hit, ``!`` otherwise — and never re-run: a cap hit re-run in the
      same workdir would let a write role see its own partial files, and three more sessions of up
      to ``call_timeout`` against a dead API measure nothing. The runners record it per case.
    * A **timeout** prints ``T`` and is retried at most ``timeout_retries`` times (one: a session
      that needed more than ``call_timeout`` twice will need it a third time), then raises
      :class:`SessionTimedOut` carrying the decoded partial stdout.
    * A **transport failure** (a non-zero exit with no envelope to read) keeps the backoff
      retries (15/30/45 s) and raises a plain ``RuntimeError`` after ``retries`` + 1 attempts.

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
        attempts = 0
        timeouts = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(workdir),
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=call_timeout,
                )
            except subprocess.CalledProcessError as exc:
                dead = session_outcome(_decoded(exc.stdout))
                if dead is not None:  # the session said no — a refusal or deterministic: no re-run
                    print(dead.marker, end="", flush=True, file=sys.stderr)
                    raise dead from None
                last_exc = exc
            except subprocess.TimeoutExpired as exc:
                print("T", end="", flush=True, file=sys.stderr)
                last_exc = exc
                timeouts += 1
                if timeouts > timeout_retries:
                    break
            else:
                dead = session_outcome(completed.stdout)
                if dead is not None:  # exit 0, but the envelope says the session never ran
                    print(dead.marker, end="", flush=True, file=sys.stderr)
                    raise dead
                print(".", end="", flush=True, file=sys.stderr)
                return _parse_cli_json(completed.stdout)
            if attempt < retries:
                time.sleep(15 * (attempt + 1))
        assert last_exc is not None
        out = _decoded(getattr(last_exc, "stdout", None))[-_TAIL:]
        err = _decoded(getattr(last_exc, "stderr", None))[-_TAIL:]
        if isinstance(last_exc, subprocess.TimeoutExpired):
            raise SessionTimedOut(
                "timeout",
                f"{attempts} attempt(s) of {call_timeout}s each; partial stdout: {out!r}",
            )
        raise RuntimeError(
            f"claude call failed after {attempts} attempts: {last_exc}: "
            f"stdout={out!r} stderr={err!r}"
        )

    return run
