"""External reviewer seam (ADR 0042): run a third-party reviewer CLI (codex) as an independent lens.

A different model is an independent review lens — it catches what a same-family ``reviewer`` pass
misses (adversarial-review.md). This is a **pure parser + a thin subprocess seam**, in the
connectors style: it **never raises** and **degrades gracefully** when the CLI is absent. Gated by
the ``external_reviewer.{enabled,command}`` settings (ADR 0041).

Pure + tested: :func:`build_prompt` / :func:`parse_review`. Thin seam: :func:`is_available` /
:func:`run_external` (the real subprocess call is excluded from coverage, like the agent_eval
transports).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import agent_eval

__all__ = ["KINDS", "build_prompt", "is_available", "run_external", "parse_review", "review"]

# Review focus per target kind.
KINDS: dict[str, str] = {
    "code": "Review this code change for correctness, bugs, security, and integration/API breaks.",
    "plan": "Review this plan for completeness, task sequencing (a cycle-free order), and risk.",
    "product": (
        "Review this product spec: testable acceptance criteria, measurable metrics, complete "
        "non-goals, traceability to the brief."
    ),
    "technical": "Review this technical design for soundness, rejected alternatives, and risks.",
}

_FORMAT = (
    'Return ONLY a JSON object: {"verdict":"approve|changes","findings":'
    '[{"severity":"blocker|major|minor|nit","location":"file:line","issue":"...",'
    '"suggestion":"..."}]}. Use "approve" only when no blocker/major remains.'
)

# Subprocess seam: (command, prompt, workdir, timeout) -> stdout. Injected in tests; the default
# shells out to the real CLI and is excluded from coverage.
Runner = Callable[[str, str, Path, int], str]


def build_prompt(target: str, kind: str) -> str:
    """The review prompt for an external CLI: the kind's criteria + the strict JSON format + the
    target. An unknown kind falls back to the code criteria."""
    criteria = KINDS.get(kind, KINDS["code"])
    return f"{criteria}\n\n{_FORMAT}\n\nTARGET:\n{target}"


def is_available(command: str) -> bool:
    """True if the external reviewer CLI is on PATH."""
    return bool(command) and shutil.which(command) is not None


def _argv(command: str, prompt: str) -> list[str]:
    """The reviewer CLI argv. For codex, ``exec --sandbox read-only`` runs it non-interactively and
    **read-only** — a reviewer must never mutate the repo (mirrors the read-only grader's tool
    allowlist). Adjust here for a different CLI / codex version; the prompt is a single argv element
    (no shell), so a hostile target can't shell-inject."""
    return [command, "exec", "--sandbox", "read-only", prompt]


def _run_cli(command: str, prompt: str, workdir: Path, timeout: int) -> str:  # pragma: no cover
    """Shell out to the external reviewer CLI (real call; excluded from coverage)."""
    completed = subprocess.run(
        _argv(command, prompt),
        cwd=str(workdir),
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
    call fails (never raises — an external reviewer is optional)."""
    if not is_available(command):
        return None
    run = runner or _run_cli
    try:
        return run(command, prompt, Path(workdir), timeout)
    except Exception:
        return None


_SEVERITIES = ("blocker", "major", "minor", "nit")


def _clean(value: Any) -> str:
    """Collapse a finding field to a single line (newlines / extra spaces removed) so external
    output can't inject markdown structure (``---``, headings) into a rendered review.md."""
    return " ".join(str(value).split())


def _finding(f: dict[str, Any]) -> dict[str, str]:
    """Normalise one external finding to the canonical shape: severity clamped to the vocab
    (unknown -> minor), every field sanitised to a single line."""
    severity = _clean(f.get("severity", "minor")).lower()
    return {
        "severity": severity if severity in _SEVERITIES else "minor",
        "location": _clean(f.get("location", "")),
        "issue": _clean(f.get("issue", f.get("text", ""))),
        "suggestion": _clean(f.get("suggestion", "")),
    }


def parse_review(output: str) -> dict[str, Any] | None:
    """Parse an external reviewer's reply into a review-shaped dict (``{verdict, findings}``), or
    ``None`` if none is found. Lenient: scans every JSON object in the reply (tolerating a leading
    session/event object that ``codex exec`` may print) and returns the first that is review-shaped,
    with findings sanitised and severities clamped to the canonical vocab."""
    for data in agent_eval.json_objects(output):
        verdict = str(data.get("verdict", "")).strip().lower()
        findings = data.get("findings")
        if verdict not in ("approve", "changes") or not isinstance(findings, list):
            continue
        good = [_finding(f) for f in findings if isinstance(f, dict)]
        return {"verdict": verdict, "findings": good}
    return None


def review(
    target: str,
    kind: str,
    *,
    command: str = "codex",
    workdir: Path | str = ".",
    runner: Runner | None = None,
) -> dict[str, Any] | None:
    """Get an external review of ``target`` (kind: code|plan|product|technical). Returns a
    review-shaped dict, or ``None`` if the reviewer is unavailable / produced nothing parseable."""
    output = run_external(command, build_prompt(target, kind), workdir, runner=runner)
    return parse_review(output) if output is not None else None
