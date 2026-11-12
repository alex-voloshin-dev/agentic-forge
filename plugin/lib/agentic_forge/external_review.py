"""External reviewer seam (ADR 0042): run a third-party reviewer CLI (codex) as an independent lens.

A different model is an independent review lens — it catches what a same-family ``reviewer`` pass
misses (adversarial-review.md). This is a **pure parser + a thin subprocess seam**, in the
connectors style: it **never raises** and **degrades gracefully** when the CLI is absent. Gated by
the ``external_reviewer.*`` settings (ADR 0041).

:func:`review_outcome` says what happened: a review, a skip, or a failure, with its reason (ADR
0100). A **skip** means the reviewer was not there to ask: absent, disabled, or not the configured
one. A **failure** means it was there and enabled, and the attempt produced no review: a timeout, a
non-zero exit, a reply with no verdict, or isolation it cannot honour. Neither carries a verdict,
so neither can read as approval, but a failure is a review lens that dropped out and must be
reported as such. :func:`review` is what the skills call: it runs only the reviewer the settings
name, and only if they enable it, and returns only the review or ``None``. The operator's CLI calls
:func:`review_outcome` directly, because its ``--command`` may name any program and its ``--force``
may override the opt-out.

The prompt goes to the CLI on **stdin** (``codex exec ... -``), not as an argv element, so its size
is bounded by the model's context and not by the OS limit on one argument (128 KiB on Linux), and a
NUL byte in the target cannot stop the call. ``--skip-git-repo-check`` lets it run from a directory
that is not a trusted git repo: the review reads a text it is given, under the read-only sandbox.

Opt-in isolation (``external_reviewer.isolated``, ADR 0100) runs the CLI without the operator's user
config and without persisting session files. A CLI that cannot honour it is not run, and the
attempt fails (``isolation-unsupported``); it is never run without it.

A reply's verdict is decided by any review-shaped ``changes`` in it, because the reviewer may quote
the target, and an approve is refused when the reply also says ``changes`` in a shape that did not
decode, or when the scan gave up before the end of the reply.

Pure + tested: :func:`build_prompt` / :func:`parse_review`. Injectable seams: :data:`Runner` (the
review call) and :data:`HelpProbe` (the capability check).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import guardrails, settings

__all__ = [
    "FAILURE_REASONS",
    "KINDS",
    "SKIP_REASONS",
    "ReviewOutcome",
    "ReviewerOptions",
    "build_prompt",
    "configured_review_outcome",
    "is_available",
    "run_external",
    "parse_review",
    "review",
    "review_outcome",
]

# Review focus per target kind. One entry per **review-criteria set** — the failure modes of what a
# phase hands off — so each phase's external lens is criticised on its own terms (an unknown kind
# falls back to `code`, which would be actively wrong for a non-code artifact). A phase whose
# deliverables share one failure mode needs only one entry: `marketing` covers its brief, strategy,
# offer doc, content, and audit report, which all fail the same way (fluff). ADR 0042, extended by
# 0061 / 0062.
KINDS: dict[str, str] = {
    "code": "Review this code change for correctness, bugs, security, and integration/API breaks.",
    "marketing": (
        "Review this marketing deliverable: every market-size, competitor, or performance claim "
        "cited or explicitly labelled an assumption, no invented figures, competitors named "
        "specifically (never 'various players'), and no unsupported superlative — every claim "
        "tracing to a real proof point."
    ),
    "plan": "Review this plan for completeness, task sequencing (a cycle-free order), and risk.",
    "product": (
        "Review this product spec: testable acceptance criteria, measurable metrics, complete "
        "non-goals, traceability to the brief."
    ),
    "research": (
        "Review this research brief: every load-bearing claim supported by a cited source, no "
        "unsourced assertion, disagreements between sources reconciled rather than averaged, and a "
        "recommendation that actually follows from the findings."
    ),
    "technical": "Review this technical design for soundness, rejected alternatives, and risks.",
    "ux": (
        "Review this UX spec: every screen covering its empty / loading / error / success states, "
        "no dead-end flow, and concrete accessibility requirements (keyboard and focus order, "
        "contrast, ARIA/semantics, input labels)."
    ),
}

_FORMAT = (
    'Return ONLY a JSON object: {"verdict":"approve|changes","findings":'
    '[{"severity":"blocker|major|minor|nit","location":"file:line","issue":"...",'
    '"suggestion":"..."}]}. Use "approve" only when no blocker/major remains.'
)

# Subprocess seam: (command, prompt, workdir, timeout) -> stdout. Injected in tests; the default
# shells out to the real CLI.
Runner = Callable[[str, str, Path, int], str]
# Capability-check seam: (command, timeout) -> the output of `<command> exec --help`.
HelpProbe = Callable[[str, int], str]

# Skipped: there was no reviewer to ask, so nothing ran. Not a problem with the review.
SkipReason = Literal["missing-cli", "command-not-configured", "disabled"]
SKIP_REASONS: tuple[str, ...] = ("missing-cli", "command-not-configured", "disabled")
# Failed: the reviewer was present and enabled, and the attempt produced no review. The lens dropped
# out of this round, which the caller must report rather than treat as a skip.
FailureReason = Literal["timeout", "process-failure", "invalid-output", "isolation-unsupported"]
FAILURE_REASONS: tuple[str, ...] = (
    "timeout",
    "process-failure",
    "invalid-output",
    "isolation-unsupported",
)
# Every reason, flat: a runtime `SkipReason | FailureReason` would fail on Python 3.9, which the
# hooks reach this module from.
Reason = Literal[
    "missing-cli",
    "command-not-configured",
    "disabled",
    "timeout",
    "process-failure",
    "invalid-output",
    "isolation-unsupported",
]

# Both are required for an isolated run. `--ignore-rules` is deliberately NOT here: it would remove
# execpolicy restrictions, which is the opposite of what isolation is for (ADR 0100).
_ISOLATION_FLAGS = ("--ignore-user-config", "--ephemeral")
_PROBE_TIMEOUT = 15  # seconds; `exec --help` does no work, so a slow one is a failed check
_DETAIL_MAX = 500
_MAX_BAD_OBJECTS = 1000  # undecodable would-be objects in one reply before it stops being a review
# How much of one piece of third-party text is sanitised. The redaction patterns are quadratic on
# hostile input (measured: under 0.1 s at this size, over 25 s at 120 KB), so this comes first.
_LINE_INPUT_MAX = 4000
# Where CLI output is kept by its tail, the cut may have removed the key or header that identified a
# secret. So more goes than the one token: enough to pass a key and its value, and any long run of
# base64 alphabet, which is what the body of a PEM key looks like without its header.
_TAIL_CUT_SKIP = 200
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=]{40,}")
# A `changes` in the raw reply. `parse_review` compares the same way: case and padding do not count.
_CHANGES_TEXT = re.compile(r'"verdict"\s*:\s*"\s*changes\s*"', re.IGNORECASE)
# Terminal escape sequences, whole, so no parameters are left behind when the control character
# goes: the string forms (OSC, DCS, SOS, PM, APC) with a terminator, then CSI, then short forms. The
# string form's body stops at another introducer, so a run of them costs one pass, not one per
# introducer.
_ANSI = re.compile(
    r"(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f])[^\x07\x1b\x9c\x90\x98\x9d\x9e\x9f]*"
    r"(?:\x07|\x1b\\|\x9c)"
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
    r"|\x1b[ -/]*[0-~]"
)


@dataclass(frozen=True)
class ReviewerOptions:
    """How to invoke the reviewer CLI. The defaults reproduce the plain read-only invocation."""

    isolated: bool = False
    model: str | None = None
    effort: str | None = None

    @classmethod
    def from_settings(cls, resolved: settings.Settings) -> ReviewerOptions:
        return cls(
            isolated=resolved.external_reviewer_isolated,
            model=resolved.external_reviewer_model,
            effort=resolved.external_reviewer_effort,
        )


@dataclass(frozen=True)
class ReviewOutcome:
    """What one external review attempt produced. ``review`` is set only when ``status`` is
    ``"reviewed"``. A ``"skipped"`` outcome (a reason in :data:`SKIP_REASONS`) and a ``"failed"``
    one (a reason in :data:`FAILURE_REASONS`) have no review and so no verdict."""

    status: Literal["reviewed", "skipped", "failed"]
    review: dict[str, Any] | None = None
    reason: Reason | None = None
    detail: str = ""


def build_prompt(target: str, kind: str) -> str:
    """The review prompt for an external CLI: the kind's criteria + the strict JSON format + the
    target. An unknown kind falls back to the code criteria."""
    criteria = KINDS.get(kind, KINDS["code"])
    return f"{criteria}\n\n{_FORMAT}\n\nTARGET:\n{target}"


def is_available(command: str) -> bool:
    """True if the external reviewer CLI is on PATH."""
    return bool(command) and shutil.which(command) is not None


def _argv(command: str, options: ReviewerOptions | None = None) -> list[str]:
    """The reviewer CLI argv. For codex, ``exec --sandbox read-only`` runs it non-interactively and
    **read-only** — a reviewer must never mutate the repo (mirrors the read-only grader's tool
    allowlist). Adjust here for a different CLI / codex version.

    The prompt is not in it: the last element is ``-``, which tells ``codex exec`` to read the
    prompt from stdin, and :func:`_run_cli` writes it there. One argv element is capped by the OS
    (128 KiB on Linux, ``E2BIG``), and a review target is routinely larger. No shell is involved
    either way.

    ``--skip-git-repo-check`` makes the caller's cwd irrelevant: codex otherwise refuses to start
    outside a trusted git repo, and the review needs no repo, only the text it is given. It does not
    widen anything: the sandbox stays read-only, and it marks no directory trusted. ``-C`` is not
    used: the cwd already names the same directory, and codex would still refuse it outside a repo.

    Every flag is fixed here: there is no free-form args setting, so no config can add one
    (ADR 0100). ``model`` / ``effort`` are re-checked at this last step, whoever built the options,
    so an invalid value is dropped rather than reaching argv."""
    opts = options or ReviewerOptions()
    argv = [command, "exec", "--sandbox", "read-only", "--skip-git-repo-check"]
    if opts.isolated:
        argv.extend(_ISOLATION_FLAGS)
    model = settings.safe_cli_value(opts.model)
    if model is not None:
        argv.extend(["--model", model])
    effort = settings.safe_cli_value(opts.effort)
    if effort is not None:
        argv.extend(["-c", f'model_reasoning_effort="{effort}"'])
    argv.append("-")  # the prompt: read from stdin
    return argv


def _run_cli(
    command: str, prompt: str, workdir: Path, timeout: int, options: ReviewerOptions | None = None
) -> str:
    """Shell out to the external reviewer CLI, with the prompt on its stdin. Raises
    ``UnicodeDecodeError`` if it exits 0 and its stdout is not UTF-8. Bytes rather than
    ``text=True``, which also decodes stderr: there a bad byte would read as a bad reply, and would
    hide a non-zero exit.

    ``input`` makes stdin a pipe holding the prompt and nothing else, so the caller's own stdin
    never reaches the CLI. It is written while the output is read, so a large prompt cannot
    deadlock."""
    completed = subprocess.run(
        _argv(command, options),
        cwd=str(workdir),
        input=prompt.encode("utf-8"),
        capture_output=True,
        check=True,
        timeout=timeout,
    )
    stdout = completed.stdout
    return stdout.decode("utf-8") if isinstance(stdout, bytes) else stdout


def _probe_help(command: str, timeout: int) -> str:
    """The real capability check: ``<command> exec --help``, nothing else. codex 0.164 prints its
    help on stdout."""
    completed = subprocess.run(
        [command, "exec", "--help"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )
    return completed.stdout


def run_external(
    command: str,
    prompt: str,
    workdir: Path | str,
    *,
    runner: Runner | None = None,
    timeout: int = 600,
) -> str | None:
    """Run the external reviewer CLI and return its stdout, or ``None`` if it is unavailable or the
    call fails (never raises — an external reviewer is optional). The plain primitive: it does not
    read settings and is never isolated. Use :func:`review_outcome` for the configured behaviour."""
    if not is_available(command):
        return None
    run = runner or _run_cli
    try:
        return run(command, prompt, Path(workdir), timeout)
    except Exception:
        return None


_SEVERITIES = ("blocker", "major", "minor", "nit")


def _without_partial_token(text: str, *, keep_tail: bool) -> str:
    """``text`` after a cut, without the token the cut went through: what is left of a secret may no
    longer match a redaction pattern, so it must not be shown."""
    parts = text.split(None, 1) if keep_tail else text.rsplit(None, 1)
    if len(parts) < 2:
        return ""
    return parts[1] if keep_tail else parts[0]


def _safe_line(text: Any, *, keep_tail: bool = False) -> str:
    """One redacted line with no terminal escapes or control characters: this reaches a terminal,
    the session and review.md, and the text comes from a third party or a config file. A single line
    also means it can't inject markdown structure (``---``, headings) into a rendered review.md.

    The input is capped first, at :data:`_LINE_INPUT_MAX`, because redaction is quadratic on hostile
    text. ``keep_tail`` keeps its end rather than its start, for CLI output, and leaves no marker.

    Escapes and control characters go BEFORE redacting: one placed inside a secret would otherwise
    hide it from the patterns, and removing it afterwards would put the secret back together. The
    token at the cut goes after them, so one with a space in its parameters cannot hide where the
    token really starts or ends."""
    if isinstance(text, bytes):  # the subprocess errors carry bytes
        text = text.decode("utf-8", "replace")
    raw = str(text if text is not None else "")
    cut = len(raw) > _LINE_INPUT_MAX
    if cut:
        raw = raw[-_LINE_INPUT_MAX:] if keep_tail else raw[:_LINE_INPUT_MAX]
    plain = _ANSI.sub("", raw)
    visible = "".join(ch for ch in plain if ch.isprintable() or ch.isspace())
    if cut and keep_tail:
        visible = _BASE64_RUN.sub("[REDACTED]", visible[_TAIL_CUT_SKIP:])
    if cut:
        visible = _without_partial_token(visible, keep_tail=keep_tail)
    line = " ".join(guardrails.redact_secrets(visible).split())
    return f"{line} [truncated]".lstrip() if cut and not keep_tail else line


def _finding(f: dict[str, Any]) -> dict[str, str]:
    """Normalise one external finding to the canonical shape: severity clamped to the vocab
    (unknown -> minor), every field a safe single line (:func:`_safe_line`)."""
    severity = _safe_line(f.get("severity", "minor")).lower()
    return {
        "severity": severity if severity in _SEVERITIES else "minor",
        "location": _safe_line(f.get("location", "")),
        "issue": _safe_line(f.get("issue", f.get("text", ""))),
        "suggestion": _safe_line(f.get("suggestion", "")),
    }


def _json_objects(output: str) -> tuple[list[dict[str, Any]], bool]:
    """Every JSON object in ``output``, nested ones included, and whether the whole reply was read.
    The scan stops at more than :data:`_MAX_BAD_OBJECTS` openings that do not decode, and what it
    decoded until then is returned: the caller decides what that may still prove.

    ``strict=False``, so a raw tab or newline inside a string does not hide a real ``changes``.

    Not ``agent_eval.json_objects``: it follows quote state across the whole reply, so one stray
    ``"`` in prose hides the objects after it, and here the hidden one could be the deciding
    ``changes``. Decoding from each opening has no such state. A decoded object is skipped past and
    walked in memory, and a failed attempt is what the limit counts, since each one costs time
    proportional to what is left of the reply. So the limit bounds the attempts, not the time, which
    still grows with the reply's size (ADR 0100)."""
    decoder = json.JSONDecoder(strict=False)
    opening = re.compile(r"\{\s*\"")
    objects: list[dict[str, Any]] = []
    bad = 0
    pos = 0
    while True:
        match = opening.search(output, pos)
        if match is None:
            return objects, True
        try:
            data, pos = decoder.raw_decode(output, match.start())
        except (ValueError, RecursionError):
            bad += 1
            if bad > _MAX_BAD_OBJECTS:
                return objects, False
            pos = match.start() + 1
            continue
        stack: list[Any] = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                objects.append(item)
                stack.extend(reversed(list(item.values())))
            elif isinstance(item, list):
                stack.extend(reversed(item))


def parse_review(output: str) -> dict[str, Any] | None:
    """Parse an external reviewer's reply into a review-shaped dict (``{verdict, findings}``), or
    ``None`` if none is found. Lenient: scans every JSON object in the reply (tolerating a leading
    session/event object that ``codex exec`` may print).

    **Any review-shaped ``changes`` decides**, wherever it is. The reviewer may quote the target,
    and the target may hold an approve, so neither position nor count can make an approve win. The
    findings are those of every object with the winning verdict, de-duplicated in reply order:
    taking only one would let a quoted ``changes`` with no findings hide the real one's. A
    ``changes`` the reviewer merely quoted also decides, which errs on the side of another look
    (ADR 0100).

    An approve has to clear two more checks, because a ``changes`` may be what could not be read.
    The scan must have reached the end of the reply, and the raw text must not say ``changes`` where
    no review-shaped object did: a trailing comma, ``findings`` null or missing. Either way the
    answer is ``None``, a skip, since the reply cannot prove an approve."""
    objects, complete = _json_objects(output)
    reviews: list[tuple[str, list[Any]]] = []
    for data in objects:
        verdict = str(data.get("verdict", "")).strip().lower()
        findings = data.get("findings")
        if verdict in ("approve", "changes") and isinstance(findings, list):
            reviews.append((verdict, findings))
    if not reviews:
        return None
    verdict = "changes" if any(v == "changes" for v, _ in reviews) else "approve"
    if verdict == "approve" and (not complete or _CHANGES_TEXT.search(output)):
        return None
    seen: dict[tuple[str, ...], dict[str, str]] = {}
    for candidate, findings in reviews:
        if candidate == verdict:
            for f in findings:
                if isinstance(f, dict):
                    item = _finding(f)
                    seen.setdefault(tuple(item.values()), item)
    return {"verdict": verdict, "findings": list(seen.values())}


def _detail(summary: str, tail: Any = "") -> str:
    """``summary`` plus a short, safe tail of CLI output. Redact BEFORE this cap: it could cut a
    secret's prefix off, and what is left no longer matches a redaction pattern. The input cap in
    :func:`_safe_line` comes earlier and is far larger, and drops the token it cuts."""
    head = _safe_line(summary)[:_DETAIL_MAX]
    flat = _safe_line(tail, keep_tail=True)
    room = _DETAIL_MAX - len(head) - 2
    return f"{head}: {flat[-room:]}" if flat and room > 0 else head


def _without_prompt(text: Any, prompt: str) -> str:
    """``text`` without any line that is also a line of ``prompt``. codex echoes the prompt to
    stderr before it starts, so the tail of a failed run's output can be the end of the target under
    review, and that must not reach the detail. Done before any cut, on whole lines: blank lines
    and lines the prompt does not hold stay. Best-effort: a target line the CLI rewrapped still
    shows."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    raw = str(text if text is not None else "")
    if not prompt or not raw:
        return raw
    held = {line.strip() for line in prompt.splitlines()} - {""}
    return "\n".join(line for line in raw.splitlines() if line.strip() not in held)


def _failure_detail(exc: Exception, prefix: str = "", prompt: str = "") -> str:
    """A failed call's detail. Never ``str(exc)`` for the subprocess errors: theirs embeds the whole
    argv, which held the target under review while the prompt was an argv element. The output tail
    goes through :func:`_without_prompt`, because the CLI may echo the prompt."""
    if isinstance(exc, subprocess.TimeoutExpired):
        tail = _without_prompt(exc.stderr, prompt)
        return _detail(f"{prefix}no result within {exc.timeout}s", tail)
    if isinstance(exc, subprocess.CalledProcessError):
        tail = _without_prompt(exc.stderr or exc.stdout, prompt)
        return _detail(f"{prefix}exit status {exc.returncode}", tail)
    return _detail(f"{prefix}{type(exc).__name__}", _without_prompt(exc, prompt))


def _isolation_problem(command: str, probe: HelpProbe) -> str:
    """Why ``command`` cannot run isolated, or ``""`` if it can. A check that fails is a "cannot":
    without positive evidence of both flags the run must not happen. Matched as whole flags, so a
    longer flag that merely contains one of the names does not count."""
    try:
        text = probe(command, _PROBE_TIMEOUT)
    except Exception as exc:
        return _failure_detail(exc, "capability check failed: ")
    missing = [
        flag
        for flag in _ISOLATION_FLAGS
        if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", str(text))
    ]
    return f"`{command} exec --help` does not list {', '.join(missing)}" if missing else ""


def _skipped(reason: SkipReason, detail: str) -> ReviewOutcome:
    return ReviewOutcome(status="skipped", reason=reason, detail=_detail(detail))


def _failed(reason: FailureReason, detail: str) -> ReviewOutcome:
    return ReviewOutcome(status="failed", reason=reason, detail=_detail(detail))


def _attempt(
    target: str,
    kind: str,
    command: str,
    workdir: Path | str,
    runner: Runner | None,
    help_probe: HelpProbe | None,
    options: ReviewerOptions | None,
    timeout: int,
) -> ReviewOutcome:
    if not is_available(command):
        return _skipped("missing-cli", f"{command!r} not found on PATH")
    opts = options
    if opts is None:
        opts = ReviewerOptions.from_settings(settings.resolve(workdir))
    if opts.isolated:
        problem = _isolation_problem(command, help_probe or _probe_help)
        if problem:
            return _failed("isolation-unsupported", problem)

    def real_cli(cmd: str, prompt: str, cwd: Path, limit: int) -> str:
        return _run_cli(cmd, prompt, cwd, limit, opts)

    run = runner or real_cli
    prompt = build_prompt(target, kind)
    try:
        output = run(command, prompt, Path(workdir), timeout)
    except subprocess.TimeoutExpired as exc:
        return _failed("timeout", _failure_detail(exc, prompt=prompt))
    except UnicodeDecodeError:  # it ran and answered, and the answer is not text
        return _failed("invalid-output", "the output is not UTF-8 text")
    except Exception as exc:
        return _failed("process-failure", _failure_detail(exc, prompt=prompt))
    parsed = parse_review(output)
    if parsed is None:
        why = "no review-shaped JSON, or an approve beside a `changes` that could not be read"
        return _failed("invalid-output", _detail(why, _without_prompt(output, prompt)))
    return ReviewOutcome(status="reviewed", review=parsed)


def review_outcome(
    target: str,
    kind: str,
    *,
    command: str = "codex",
    workdir: Path | str = ".",
    runner: Runner | None = None,
    help_probe: HelpProbe | None = None,
    options: ReviewerOptions | None = None,
    timeout: int = 600,
) -> ReviewOutcome:
    """Review ``target`` (kind: any key of :data:`KINDS`) and report what happened; never raises.

    Runs ``command`` as given and does not read ``enabled``, so it is for a caller that speaks for
    the operator, such as the CLI's ``--command`` and ``--force``. Anything else goes through
    :func:`configured_review_outcome`. ``options=None``
    reads the ``external_reviewer`` settings for ``workdir``. ``runner`` is a test seam that
    receives no argv; the flags apply to the default runner."""
    try:
        return _attempt(target, kind, command, workdir, runner, help_probe, options, timeout)
    except Exception as exc:
        return _failed("process-failure", _failure_detail(exc))


def configured_review_outcome(
    target: str,
    kind: str,
    *,
    command: str | None = None,
    workdir: Path | str = ".",
    runner: Runner | None = None,
    help_probe: HelpProbe | None = None,
    timeout: int = 600,
) -> ReviewOutcome:
    """:func:`review_outcome` for the reviewer the settings name, and no other; never raises.

    ``enabled: false``, at either config level, is a ``disabled`` skip before anything else happens:
    nothing is probed or run, so an opt-out holds even for a caller that did not check it.
    ``command=None`` means the configured reviewer. A different ``command`` is refused without being
    run: a session that read the raw repo file and passed its value would otherwise run a program
    the repo chose, and that program's stdout would be the verdict (ADR 0100). The detail does not
    repeat the refused value, which may be repo-controlled."""
    try:
        resolved = settings.resolve(workdir)
        if not resolved.external_reviewer_enabled:
            where = (
                f" in this repo's config ({settings.CONFIG_PATH})"
                if resolved.external_reviewer_disabled_by_repo
                else ""
            )
            return _skipped("disabled", f"external_reviewer.enabled is false{where}")
        configured = resolved.external_reviewer_command
        if command is not None and command != configured:
            return _skipped(
                "command-not-configured",
                f"only the configured reviewer {configured!r} may run here; "
                "take it from settings.resolve, not from the config file",
            )
        return review_outcome(
            target,
            kind,
            command=configured,
            workdir=workdir,
            runner=runner,
            help_probe=help_probe,
            options=ReviewerOptions.from_settings(resolved),
            timeout=timeout,
        )
    except Exception as exc:
        return _failed("process-failure", _failure_detail(exc))


def review(
    target: str,
    kind: str,
    *,
    command: str | None = None,
    workdir: Path | str = ".",
    runner: Runner | None = None,
) -> dict[str, Any] | None:
    """Get an external review of ``target`` (kind: any key of :data:`KINDS`) from the configured
    reviewer. Returns a review-shaped dict, or ``None`` if the review was skipped or failed for any
    reason (see :func:`configured_review_outcome` for which one, including an opt-out and a
    ``command`` that is not the configured one)."""
    outcome = configured_review_outcome(
        target, kind, command=command, workdir=workdir, runner=runner
    )
    return outcome.review
