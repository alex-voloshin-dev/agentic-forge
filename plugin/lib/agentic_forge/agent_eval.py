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

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import benchmark, gate
from .evals import EvalsError, checked_fixture, eval_case_problems, fixture_dest, load_evals
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
    "role_body",
    "CLAUDE_MD_ENV_VAR",
    "OMIT_CLAUDE_MD_MODES",
    "omits_claude_md",
    "resolve_omit_claude_md",
    "claude_md_env",
    "claude_md_unloadable",
    "place_claude_md",
    "PROBE_PROMPT",
    "first_heading",
    "quotes_heading",
    "heading_problem",
    "claude_md_probe",
    "input_fingerprint",
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
    "reader",
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

    When the transport reports cached input, ``usage`` also has ``cache_read_input_tokens``,
    ``cache_creation_input_tokens`` and ``prompt_tokens`` (their sum with ``input_tokens``: every
    prompt token the model read). ``cost_usd`` is the transport's own cost figure when it gives one
    (the CLI's ``total_cost_usd``). Both exist for the ``omitClaudeMd`` A/B: a CLAUDE.md sits in the
    cached prompt prefix, which ``input_tokens`` leaves out (ADR 0113, amended).
    """

    usage: dict[str, int] | None
    cost_usd: float | None

    def __new__(
        cls, text: str, usage: dict[str, int] | None = None, cost_usd: float | None = None
    ) -> RunOutput:
        obj = super().__new__(cls, text)
        obj.usage = usage
        obj.cost_usd = cost_usd
        return obj


def _usage_from_counts(
    input_tokens: int,
    output_tokens: int,
    *,
    cache_creation: int | None = None,
    cache_read: int | None = None,
) -> dict[str, int]:
    """The usage mapping. The cache fields are added only when the transport reported one, so a
    reply without them keeps the three-key shape; ``prompt_tokens`` then counts every input token,
    cached or not."""
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if cache_creation is not None or cache_read is not None:
        created = int(cache_creation or 0)
        read = int(cache_read or 0)
        usage["cache_creation_input_tokens"] = created
        usage["cache_read_input_tokens"] = read
        usage["prompt_tokens"] = input_tokens + created + read
    return usage


def _prompt_tokens(output: str) -> int | None:
    """Every prompt token one reply's session read (cached included), or None without usage."""
    usage = getattr(output, "usage", None)
    if isinstance(usage, dict):
        return int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    return None


def _cost(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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


def permission_denials(stdout: str) -> int:
    """How many tool calls the envelope says were denied. Never what they asked for: that is the
    model's text, and the caller's message may reach a log. Anything else reads as none."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return 0
    denials = data.get("permission_denials") if isinstance(data, dict) else None
    return len(denials) if isinstance(denials, list) else 0


def _parse_cli_json(stdout: str) -> RunOutput:
    """Parse `claude -p --output-format json` stdout into the reply text + token usage.

    The expected shape is ``{"result": "<text>", "usage": {"input_tokens", "output_tokens", …},
    "total_cost_usd": …}``. Measured on Claude Code 2.1.331: ``usage`` is summed over the session's
    turns, and ``input_tokens`` excludes ``cache_read_input_tokens`` and
    ``cache_creation_input_tokens``, which are kept too (see :class:`RunOutput`). Degrades to the
    raw stdout with no usage if it is not that result-bearing JSON, so an odd or older CLI output
    can never crash a Tier-2 sweep (ADR 0038)."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return RunOutput(stdout)
    if not isinstance(data, dict) or "result" not in data:
        return RunOutput(stdout)
    cost = _cost(data.get("total_cost_usd"))
    usage = data.get("usage")
    if isinstance(usage, dict):
        counts = _usage_from_counts(
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
            cache_creation=usage.get("cache_creation_input_tokens"),
            cache_read=usage.get("cache_read_input_tokens"),
        )
        return RunOutput(str(data["result"]), counts, cost)
    return RunOutput(str(data["result"]), None, cost)

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


def role_body(plugin_dir: Path, role: str) -> str:
    """A role's system-prompt body, as :func:`run_role` passes it."""
    return _read_body(plugin_dir / "agents" / f"{role}.md")


def is_write_role(plugin_dir: Path, role: str) -> bool:
    """True if the role's frontmatter grants Write/Edit.

    Such roles can mutate files, so they MUST run isolated (a fresh per-case workdir) — never
    against the real repo. run_role enforces this regardless of the caller's ``isolate`` flag.
    """
    fm, _ = parse_frontmatter((plugin_dir / "agents" / f"{role}.md").read_text(encoding="utf-8"))
    tools = str(fm.get("tools", ""))
    return "Write" in tools or "Edit" in tools


# --- omitClaudeMd in an eval session (ADR 0113, amended) ---------------------
# Claude Code reads a role's `omitClaudeMd` only when a session delegates to it; a `claude -p` eval
# session is not a delegation, so the harness applies the field through the CLI's own switch. With
# this variable at "1" the memory loader reports "project memory is off" and looks for no CLAUDE.md
# / AGENTS.md; at "0" (or unset) it walks every ancestor of the working directory for them
# (measured on Claude Code 2.1.331 against a local capture server, no model call). Both values are
# always set, so an operator's exported value cannot decide an arm. Unlike the field, it also drops
# managed policy files.
CLAUDE_MD_ENV_VAR = "CLAUDE_CODE_DISABLE_CLAUDE_MDS"
OMIT_CLAUDE_MD_MODES: tuple[str, ...] = ("role", "on", "off")


# The one spelling that means "omit" to every reader. PyYAML (YAML 1.1, our parser) also reads
# `yes`/`on`/`True` as true, which Claude Code's agent schema need not; Tier-0 holds the field to
# the literal `true`/`false` (validation.validate_agent), and the harness reads only `true`.
_OMIT_TRUE = re.compile(r"^omitClaudeMd:[ \t]*true[ \t]*$", re.MULTILINE)


def omits_claude_md(plugin_dir: Path, role: str) -> bool:
    """True if the role's frontmatter sets ``omitClaudeMd: true`` — written as the literal ``true``,
    as Claude Code's agent schema takes a boolean. ``yes``/``on`` parse as true in YAML 1.1 but are
    not read as omission here (and Tier-0 refuses them)."""
    text = (plugin_dir / "agents" / f"{role}.md").read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(text)
    end = text.find("\n---", 3)
    head = text[:end] if end > 0 else ""
    return fm.get("omitClaudeMd") is True and _OMIT_TRUE.search(head) is not None


def resolve_omit_claude_md(mode: str, plugin_dir: Path, role: str) -> bool:
    """Whether the role under test runs without CLAUDE.md: ``role`` follows its frontmatter,
    ``on`` / ``off`` force it (the A/B override)."""
    if mode == "role":
        return omits_claude_md(plugin_dir, role)
    if mode in ("on", "off"):
        return mode == "on"
    raise ValueError(f"omit-claude-md mode must be one of {OMIT_CLAUDE_MD_MODES}, got {mode!r}")


def claude_md_env(omit: bool) -> dict[str, str]:
    """The session environment that applies ``omit`` (see :data:`CLAUDE_MD_ENV_VAR`)."""
    return {CLAUDE_MD_ENV_VAR: "1" if omit else "0"}


def claude_md_unloadable(path: Path) -> str | None:
    """Why Claude Code would refuse to load a CLAUDE.md under ``path``, or None.

    Claude Code 2.1.331 does not load one in a session's scratchpad, "a folder laid out like one
    (claude/<project>/<session id>/scratchpad)", or in a folder named ``.artifact-work`` — its
    debug log says so per file; the measured case was ``claude-1000/<project>/<session>/
    scratchpad``. A ``--claude-md`` workspace there would load nothing, and the A/B's "off" arm
    would silently be a second "on" arm. Checked on the path as given and as resolved, since the
    CLI follows links."""
    for candidate in (path, path.resolve()):
        parts = candidate.parts
        if ".artifact-work" in parts:
            return f"{candidate} is inside a .artifact-work folder"
        for i, part in enumerate(parts):
            if part == "scratchpad" and i >= 3 and parts[i - 3].startswith("claude"):
                return f"{candidate} is inside a Claude Code session scratchpad"
    return None


def place_claude_md(workdir: Path, text: str) -> None:
    """Write ``text`` as the workspace's ``CLAUDE.md``. A case whose fixtures already put one there
    is an error, not an overwrite: the A/B would then measure the fixture's file, not this one."""
    target = workdir / "CLAUDE.md"
    if target.exists():
        raise ValueError(
            f"the case's fixtures already provide {target.name}; --claude-md would replace it"
        )
    target.write_text(text, encoding="utf-8")


# The A/B's manipulation check (ADR 0113, amended). A token total over a role's sessions cannot
# tell two arms apart — it sums up to 40 turns that each re-read the whole cached context, so turn
# count alone moves it by more than a CLAUDE.md — so each arm also asks one question whose answer
# depends only on whether the file was loaded.
PROBE_PROMPT = (
    "Quote the first Markdown heading of the project CLAUDE.md you were given, or reply NONE. "
    "Reply with the heading text only."
)
_PROBE_ANSWER_CAP = 4000  # kept for validation; the console shows less
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_DASHES = re.compile("[\u2010-\u2015\u2212]")


def first_heading(text: str) -> str | None:
    """The text of the first Markdown ATX heading (``# Title`` → ``Title``), or None."""
    match = _HEADING.search(text)
    return match.group(1).strip() if match else None


def _normalized(text: str) -> str:
    return " ".join(_DASHES.sub("-", text).casefold().split())


_MIN_HEADING_CHARS = 12


def heading_problem(heading: str | None) -> str | None:
    """Why ``heading`` cannot tell the probe's two answers apart, or None. A heading that is short,
    a single word, part of :data:`PROBE_PROMPT` or of ``none`` could be "quoted" by a session that
    never saw the file — echoing the question, or answering NONE — so the off arm's probe would
    prove nothing."""
    if heading is None:
        return "it has no Markdown heading for the A/B probe to ask for"
    norm = _normalized(heading)
    if len(norm) < _MIN_HEADING_CHARS or len(norm.split()) < 2:
        return (
            f"its first heading {heading!r} is too generic for the A/B probe "
            f"(at least {_MIN_HEADING_CHARS} characters and two words)"
        )
    if norm in _normalized(PROBE_PROMPT) or norm in "none":
        return f"its first heading {heading!r} occurs in the probe's own question or answer"
    return None


def quotes_heading(answer: str, heading: str) -> bool:
    """Whether ``answer`` quotes ``heading`` — case, whitespace and dash style aside (a model may
    write an em dash as a hyphen)."""
    return _normalized(heading) in _normalized(answer)


def claude_md_probe(run_fn: Runner, system: str, claude_md: str) -> dict[str, Any]:
    """Run the probe once: a fresh workspace made as a case's is (``mkdtemp`` +
    :func:`place_claude_md`), :data:`PROBE_PROMPT`, ``system`` as the role's prompt. ``run_fn`` is
    meant to be built like the role's runner, with the same CLAUDE.md switch, one turn and no
    tools (so the answer reflects what was loaded, not what a tool read). Returns
    ``{answer, prompt_tokens}`` or ``{error}``."""
    work = Path(tempfile.mkdtemp(prefix="af-eval-"))
    try:
        place_claude_md(work, claude_md)
        try:
            output = run_fn(system, PROBE_PROMPT, work)
        except (SessionUndetermined, RuntimeError) as exc:
            return {"error": _flat(str(exc))}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # Whitespace-normalised and capped generously, never at the 200-character display cap: a heading
    # quoted after a preamble must still be found (round-4 review).
    answer = " ".join(str(output).split())[:_PROBE_ANSWER_CAP]
    return {"answer": answer, "prompt_tokens": _prompt_tokens(output)}


def input_fingerprint(plugin_dir: Path, role: str, claude_md: str) -> str:
    """SHA-256 over everything an A/B arm's sessions read from the tree: the role file, the judge
    (``grader.md``), the role's eval contract, every case fixture it references, and the workspace
    CLAUDE.md. Two arms pair only when it is equal — same inputs, only the switch differs."""
    contract = plugin_dir / "agents" / "evals" / f"{role}.evals.json"
    rels = [f"agents/{role}.md", "agents/grader.md", f"agents/evals/{role}.evals.json"]
    cases = load_evals(contract).get("evals") or []
    files = sorted({f for case in cases for f in case.get("files") or []})
    digest = hashlib.sha256()
    for rel in [*rels, *files]:
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update((plugin_dir / rel).read_bytes() + b"\0")
    digest.update(b"CLAUDE.md\0" + claude_md.encode("utf-8"))
    return digest.hexdigest()


def load_fixtures(plugin_dir: Path, files: list[str]) -> str:
    """Concatenate the case's context files into a labeled block.

    Files are labeled by their **sandbox destination** (:func:`fixture_dest` — the basename, or
    the path below a ``tree/`` segment), never their repo-relative path, so a prompt never hands
    a role a path it could resolve back to the real repository (see materialize_fixtures).
    """
    sources = [(rel, checked_fixture(plugin_dir, rel)) for rel in files]  # all, before any read
    blocks = [
        f"--- FILE: {fixture_dest(rel)} ---\n{path.read_text(encoding='utf-8')}"
        for rel, path in sources
    ]
    return "\n\n".join(blocks)


def materialize_fixtures(plugin_dir: Path, files: list[str], workdir: Path) -> None:
    """Copy a case's fixture files into the sandbox workdir — by basename, or with their layout
    below a ``tree/`` segment (:func:`fixture_dest`), so a case can seed ``src/lib.rs`` or a
    ``plugin/agents/`` skeleton rather than a flat pile.

    An isolated role then works on these copies in its own working directory and can never
    reach — or mutate — the real fixture files in the repo. This is the isolation guarantee for
    write roles (software-engineer, architect, qa-engineer).

    Every path is checked before the first write (ADR 0116): each source by
    :func:`~agentic_forge.evals.checked_fixture` (no absolute path, no ``..`` or ``.git`` part, and
    inside the plugin directory with symlinks followed), and each destination, resolved, inside
    ``workdir``. A refused path raises :class:`~agentic_forge.evals.EvalsError` and writes nothing.
    """
    root = workdir.resolve()
    plan: list[tuple[Path, Path]] = []
    for rel in files:
        source = checked_fixture(plugin_dir, rel)
        target = workdir / fixture_dest(rel)
        try:
            target.resolve().relative_to(root)
        except ValueError:
            raise EvalsError(f"fixture path {rel} lands outside the workspace") from None
        plan.append((source, target))
    for source, target in plan:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def build_role_prompt(
    case: dict[str, Any],
    fixture_text: str,
    *,
    in_workdir: bool = False,
    file_names: list[str] | None = None,
) -> str:
    """The role's prompt: the case's prompt, then its files. ``file_names`` (a ``workspace`` case,
    ADR 0116) names the files in the working directory instead of pasting them, so the role reads
    them with its own tools, as it does for a real brief; otherwise their text is appended."""
    parts = [str(case["prompt"])]
    if file_names:
        listed = "\n".join(f"- {name}" for name in file_names)
        parts.append(f"\nThese files are in your working directory; read them there:\n{listed}")
        return "\n".join(parts)
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
    return {
        "total": 0,
        "undetermined": 0,
        "ungraded": 0,
        "subtypes": {},
        "events": [],
        # The first case that failed an assertion, in its own words (run, case, the reply's
        # tail): a FAIL that names the assertion still leaves WHY to a paid re-run, and one
        # transcript is what cracked ADR 0097 (ADR 0098).
        "failed_sample": None,
        # What each run's role sessions spent, graded or not (ADR 0113, amended): one entry per run
        # in which at least one role session answered — {answered, prompt_tokens?, cost_usd?}.
        # Kept apart from `timing`, which only a run with a graded case gets.
        "spend": [],
    }


_SAMPLE_CAP = 600  # of a failing case's reply kept beside the summary


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
    claude_md: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Execute ``cases`` ``runs`` times under ``system_body``; return ``(gradings, timing,
    sessions)``.

    ``claude_md`` (isolated runs only) is written into each case's fresh workspace as
    ``CLAUDE.md`` after its fixtures (:func:`place_claude_md`), for the ``omitClaudeMd`` A/B.

    ``timing`` carries one entry per run with a graded case: ``{"duration_ms": …}`` (wall-clock for
    that run's cases), plus ``"total_tokens"`` when the transport reports usage (a
    :class:`RunOutput` — see ADR 0038), graded cases only, as ``max_overhead_tokens`` has always
    gated it. Only the component (``run_fn``) sessions are summed, not the grader's, so the Tier-2
    A-B delta reflects the skill's own token cost. A text-only transport reports no usage, so
    ``total_tokens`` is simply absent and token-overhead stays unmeasured.

    ``sessions["spend"]`` is what the role's sessions spent, independent of grading: per run with
    an answered session, how many answered, their ``prompt_tokens`` (cached input included) and
    ``cost_usd`` when reported — a run whose every case went ungraded still spent them.

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
        run_prompt = 0
        run_cost = 0.0
        saw_usage = False
        saw_prompt = False
        saw_cost = False
        answered = 0
        graded_cases = 0
        started = time.monotonic()
        for case_no, case in enumerate(cases, start=1):
            sessions["total"] += 1
            # A case that asks for a workspace (ADR 0116) always gets a fresh directory of its own.
            workspace = case.get("workspace")
            case_isolate = isolate or workspace is not None
            work = Path(tempfile.mkdtemp(prefix="af-eval-")) if case_isolate else default_work
            try:
                case_files = case.get("files") or []
                if case_isolate:
                    materialize_fixtures(plugin_dir, case_files, work)
                    if claude_md is not None:
                        place_claude_md(work, claude_md)
                if workspace is None:
                    prompt = build_role_prompt(
                        case, load_fixtures(plugin_dir, case_files), in_workdir=case_isolate
                    )
                else:
                    names = [fixture_dest(rel) for rel in case_files]
                    prompt = build_role_prompt(case, "", file_names=names)
                try:
                    output = run_fn(system_body, prompt, work)
                except SessionUndetermined as exc:
                    _record_unmeasured(sessions, "undetermined", run_no, case_no, exc)
                    continue
                # The role's prompt tokens and cost are spent once it answered, whatever the judge
                # does next: a case the grader fails to grade still cost its session.
                answered += 1
                prompt = _prompt_tokens(output)
                if prompt is not None:
                    saw_prompt = True
                    run_prompt += prompt
                cost = getattr(output, "cost_usd", None)
                if cost is not None:
                    saw_cost = True
                    run_cost += float(cost)
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
                if case_isolate:
                    shutil.rmtree(work, ignore_errors=True)
            tokens = _usage_tokens(output)
            if tokens is not None:
                saw_usage = True
                run_tokens += tokens
            graded_cases += 1
            if sessions.get("failed_sample") is None and any(
                not benchmark.passed_value(r.get("passed"))
                for r in graded["assertion_results"]
                if isinstance(r, dict)
            ):
                sessions["failed_sample"] = {
                    "run": run_no,
                    "case": case_no,
                    "text": _flat(output, _SAMPLE_CAP),
                }
            run_results.extend(graded["assertion_results"])
            # Aggregate over EXPECTED assertion counts (grade_output's summary), not len(results)
            # — so a grader that omits or duplicates results can't skew the run's pass-rate.
            run_total += graded["summary"]["total"]
            run_passed += graded["summary"]["passed"]
        if answered:  # before the skip below: an all-ungraded run still spent its sessions
            spend: dict[str, Any] = {"answered": answered}
            if saw_prompt:
                spend["prompt_tokens"] = run_prompt
            if saw_cost:
                spend["cost_usd"] = run_cost
            sessions["spend"].append(spend)
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
    claude_md: str | None = None,
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

    Every case's fixture paths are checked first (ADR 0116), so a refused path raises
    :class:`~agentic_forge.evals.EvalsError` before any case writes a file or calls a model.

    ``claude_md`` is a project CLAUDE.md placed in every case's workspace (both passes). It needs
    ``isolate``: the file must land in a fresh temp workspace, never in ``workdir`` or the repo.
    """
    if claude_md is not None and not isolate:
        raise ValueError("claude_md needs isolate=True: it is written into each case's workspace")
    for case in cases:
        for rel in case.get("files") or []:
            checked_fixture(plugin_dir, rel)
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
        claude_md=claude_md,
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
            claude_md=claude_md,
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
    claude_md: str | None = None,
) -> RoleReport:
    """Run a role's Tier-2 eval: N runs over its cases, graded, aggregated, and gated.

    ``isolate`` gives each case execution a fresh temp workdir (removed afterwards), so a run
    cannot see another run's files. It is **forced on for write roles** (software-engineer,
    architect, qa-engineer — anything with Write/Edit) so they can never mutate the real
    repo, regardless of the caller's flag. Read roles don't need it, except per case: a case with
    a ``workspace`` (ADR 0116) always runs in a fresh directory of its own.

    ``claude_md`` (the text of a project CLAUDE.md) is written into every case's workspace, and
    forces ``isolate`` for the same reason: the file must never land in the repo. Whether a session
    then loads it is the runner's business (:func:`claude_md_env`, ADR 0113 amended).
    """
    contract = load_evals(plugin_dir / "agents" / "evals" / f"{role}.evals.json")
    role_body = _read_body(plugin_dir / "agents" / f"{role}.md")
    grader_body = _read_body(plugin_dir / "agents" / "grader.md")
    if not isolate and is_write_role(plugin_dir, role):
        isolate = True  # safety: a write role must never run against the real repo
    if claude_md is not None:
        isolate = True  # the workspace CLAUDE.md goes into a fresh temp dir, never the repo
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
        claude_md=claude_md,
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
        # `block.type == "text"` (not getattr) so the SDK's typed content union narrows to
        # TextBlock under mypy once the eval extra is installed.
        text = "".join(block.text for block in message.content if block.type == "text")
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
                cache_creation=getattr(usage, "cache_creation_input_tokens", None),
                cache_read=getattr(usage, "cache_read_input_tokens", None),
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
    env: dict[str, str] | None = None,
    setting_sources: str = "project",
    strict_mcp_config: bool = False,
    tools: str | None = None,
    permission_mode: str | None = None,
    session_persistence: bool = True,
    denials_undetermined: bool = False,
    settings: str | None = None,
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

    ``setting_sources`` is ``--setting-sources``. An eval keeps ``project``: the project's settings
    are part of the repo under test. A session in a tree that is **not trusted** needs more, and
    ``pr_watch._fixer`` is the one that asks (ADR 0103, measured against the CLI): project settings
    run code as the operator, user settings can hand a session Bash or bypass its permissions, and
    ``--allowedTools`` only grants, so ``tools`` (``--tools``) is what removes a tool from the
    session and ``permission_mode`` (``--permission-mode``) what confines the rest to the working
    tree. ``session_persistence=False`` is ``--no-session-persistence``. With
    ``denials_undetermined`` a session in which a tool call was denied raises
    :class:`SessionUndetermined`: what it says afterwards was not its decision to make. ``settings``
    is ``--settings``, which applies whatever ``setting_sources`` says.

    Note the limit: this controls the *system prompt*, not the CLI's user-level ``CLAUDE.md``
    auto-discovery, which still applies. Only ``--bare`` disables that, and it forces
    ``ANTHROPIC_API_KEY`` auth — which would break the subscription-billed path the runbook
    recommends — so it is deliberately not used here. A role's ``omitClaudeMd`` is applied through
    ``env`` instead (:func:`claude_md_env`, ADR 0113 amended).
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
        cmd += ["--setting-sources", setting_sources]
        if strict_mcp_config:
            cmd.append("--strict-mcp-config")
        if tools is not None:
            cmd += ["--tools", tools]
        if permission_mode is not None:
            cmd += ["--permission-mode", permission_mode]
        if not session_persistence:
            cmd.append("--no-session-persistence")
        if settings is not None:
            cmd += ["--settings", settings]
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
                    env={**os.environ, **(env or {})},
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
                denied = permission_denials(completed.stdout)
                if denials_undetermined and denied:
                    print("!", end="", flush=True, file=sys.stderr)
                    raise SessionUndetermined("permission_denied", f"{denied} tool call(s) denied")
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
