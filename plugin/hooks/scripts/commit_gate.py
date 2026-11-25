#!/usr/bin/env python3
"""Test-gate hook (PreToolUse): block a git commit/push when the fast gate fails (ADR 0019).

On a `git commit`/`git push` Bash command, run the repo's fast gate (`dev/validate.py` if present,
else the detected stack's lint) and exit 2 (block) if it fails. The gate runs in the directory the
commit acts on: a plain `cd <dir> && … git -C <dir> commit` line is followed within the start
directory's own work tree (`guardrails.commit_dir`, ADR 0111). A simple command narrows that gate
to what it changes (`gate_scope`, ADR 0101). Skippable via the `test_gate.skip` setting (or
AGENTIC_FORGE_SKIP_TEST_GATE — ADR 0041). Fails OPEN on any infrastructure error (missing tool,
etc.) — only a genuine gate failure blocks.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from agentic_forge import diagnostics, gate_scope, guardrails, settings, stacks  # noqa: E402

# A fail-open is the RIGHT default — a broken toolchain must not block a commit (ADR 0058/0059) —
# but until 2026.9.1 it was announced only to the diagnostics log, which nobody reads. A field
# bundle: 69 fail-opens over two months, 50 of them one missing `ruff`, and the operator never knew
# the gate had stopped running. The notice below says it once per session (ADR 0081).
_FAIL_OPEN_MARKER = "commit-gate:fail-open"
# Once per session per set of ignored tool directories (ADR 0115): one fixed key per kind ("dirs",
# "script"), the set's digest kept in the value beside the session, so the notices file never grows.
_UNTRUSTED_MARKER = "commit-gate:untrusted-tools:"
_SHOWN_NAMES = 12  # of the withheld variable names in a block's messages


_GATE_TIMEOUT = 110  # seconds; the hook itself is capped at 120 in hooks.json
_TAIL_CHARS = 400  # of a hung gate's output kept in the record (each context value caps at 500)
_SHOWN_ARGS = 12  # of a gate's argv in what we print: a commit can touch a thousand files


def _tail(raw: object) -> str:
    """The last ``_TAIL_CHARS`` of a captured stream. ``TimeoutExpired`` carries the partial output
    as BYTES on POSIX even in text mode; only ``str(exc)`` was recorded, so nothing said which test
    hung."""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    return text.strip()[-_TAIL_CHARS:]


def _shown(gate: list[str]) -> str:
    """``gate`` for a person: not all of a long argv, and no filename's control characters."""
    shown = gate if len(gate) <= _SHOWN_ARGS else [*gate[:_SHOWN_ARGS], "..."]
    return gate_scope.printable(" ".join(shown), keep="")


def fail_open_notice(gate: list[str], detail: str) -> str:
    """The one line an operator needs when the gate could not run: what did not run, and what to
    do about it. A timeout gets its own remedy — installing something is not the answer when the
    lint ran fine and merely took too long (a field case: `npm run lint` on a large Next.js app,
    ADR 0082)."""
    head = f"agentic-forge test-gate: `{_shown(gate)}` could not run — this commit was NOT gated "
    if "TimeoutExpired" in detail:
        return (
            f"{head}(timed out after {_GATE_TIMEOUT}s). The gate is capped by the hook's own "
            f"{_GATE_TIMEOUT + 10}s budget, so a slow whole-repo lint can never fit: scope it to "
            "the staged files (lint-staged, `eslint --cache`), or set `test_gate.skip: true` in "
            ".agentic-forge/config.json and gate in CI instead."
        )
    return (
        f"{head}({gate_scope.printable(detail)}). Install the tool (or keep it in the project's "
        ".venv/node_modules), or "
        "set `test_gate.skip: true` in .agentic-forge/config.json to stop trying."
    )


def _announce(
    cwd: str, gate: list[str], detail: str, session_id: str | None, notes: list[str] | None = None
) -> None:
    """Print the fail-open notice to the operator, once per session. Hook stdout is JSON, so the
    line goes in `systemMessage` — stderr from a hook that exits 0 reaches nobody. The run's
    pending ``notes`` ride in the same message (one JSON object per run) and are then spent."""
    if diagnostics.once_per_session(cwd, _FAIL_OPEN_MARKER, session_id):
        message = "\n".join([*(notes or []), fail_open_notice(gate, detail)])
        if notes:
            notes.clear()
        print(json.dumps({"systemMessage": message}))


def _named(skipped: Sequence[tuple[Path, str]]) -> str:
    return ", ".join(f"`{directory}` ({why})" for directory, why in skipped)


def skipped_tools_notice(skipped: Sequence[tuple[Path, str]]) -> str:
    """For the model on stderr, and the operator: which project tool directories the hook did not
    use, and exactly what that means (ADR 0115)."""
    noun = "directory" if len(skipped) == 1 else "directories"
    return gate_scope.printable(
        f"agentic-forge test-gate: ignored the project tool {noun} {_named(skipped)}: the hook "
        "neither takes the gate's program from it nor adds it to the gate's PATH, because the gate "
        "runs before the commit is approved. The project's own checks still run.",
        keep="",
    )


def script_skip_notice(gate: list[str], skipped: Sequence[tuple[Path, str]], cwd: str) -> str:
    """For the operator: a package-script gate that was not run, because the package manager would
    put an ignored `node_modules/.bin` back on the script's PATH itself (ADR 0115)."""
    return gate_scope.printable(
        f"agentic-forge test-gate: `{_shown(gate)}` was NOT run — this commit was NOT gated. A "
        "package manager puts the `node_modules/.bin` of the package and of every parent on a "
        f"script's PATH itself, and {_named(skipped)} is not one the hook can trust. If it is your "
        "own install, make sure git tracks nothing in it; otherwise set `test_gate.skip: true` in "
        f"{cwd}/.agentic-forge/config.json to stop trying.",
        keep="",
    )


def _withheld(names: Sequence[str]) -> str:
    shown = ", ".join(names[:_SHOWN_NAMES])
    return shown + (f" and {len(names) - _SHOWN_NAMES} more" if len(names) > _SHOWN_NAMES else "")


def _once_for(
    cwd: str, kind: str, skipped: Sequence[tuple[Path, str]], session_id: str | None
) -> bool:
    """:func:`diagnostics.once_per_session` under the one key of ``kind``, for this session and the
    sorted set ``skipped``: a new set is news, the same set on every commit is not."""
    if not session_id:
        return False
    key = "\0".join(sorted(f"{directory}\t{why}" for directory, why in skipped))
    digest = hashlib.sha256(key.encode("utf-8", "surrogateescape")).hexdigest()[:16]
    return diagnostics.once_per_session(cwd, _UNTRUSTED_MARKER + kind, f"{session_id}:{digest}")


def _run_gate(
    gate: list[str],
    cwd: str,
    payload: dict[str, Any],
    *,
    timeout: float = _GATE_TIMEOUT,
    notes: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``gate`` in ``env`` (else :func:`guardrails.gate_env`), its program by absolute path
    (:func:`guardrails.executable`); None when it could not run, which is recorded and announced as
    a fail-open."""
    try:
        env = guardrails.gate_env(cwd) if env is None else env
        return subprocess.run(
            guardrails.executable(gate, env.get("PATH", "")),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except Exception as exc:
        # Infra error (tool missing, timeout) -> don't block, but RECORD the fail-open: a gate
        # that silently never runs is indistinguishable from a healthy one in the diagnostics
        # log (a real 7-day bundle had zero events — this makes that reading trustworthy).
        context: dict[str, Any] = {"gate": " ".join(gate)}
        for stream in ("stdout", "stderr"):  # a timeout's partial output: WHICH test hung
            tail = _tail(getattr(exc, stream, None))
            if tail:
                context[stream] = tail
        diagnostics.emit(
            cwd, kind="anomaly", component="commit-gate",
            message=f"gate fail-open (infra): {type(exc).__name__}: {exc}",
            severity="minor", context=context,
            session_id=payload.get("session_id"),
        )
        _announce(cwd, gate, f"{type(exc).__name__}: {exc}", payload.get("session_id"), notes)
        return None


def block_message(
    gate: list[str],
    cwd: str,
    *,
    scoped: bool,
    tail: str,
    shape: bool = False,
    moved: bool = False,
    withheld: Sequence[str] = (),
) -> str:
    """For the model, on stderr: what ran on what, its output, and what to do. It does not say how
    to turn the guardrail off, which is the operator's call (:func:`skip_notice`), and a linter
    quotes what it reads, a linked credentials file included. ``withheld``: the names of the
    variables the gate ran without (ADR 0115), given when its output reads like an authentication
    failure, since a gate that needed one can block."""
    scope = "on the changed files only" if scoped else "run whole"
    # A bare `git commit` runs in the call's start directory: when the gate moved (ADR 0111), the
    # way to a narrowed gate goes through the directory first.
    first = f"running `cd {shlex.quote(cwd)}` as its own call, then " if moved else ""
    hint = (
        f"This command shape ran whole; {first}running `git commit` or `git push` as its own call "
        "gates only what changed.\n" if shape else ""
    )
    if withheld:
        hint += (
            f"The gate ran without {_withheld(withheld)}, withheld because the names look like "
            "credentials. If it failed for want of one (a private module or registry), that is not "
            "a finding in the code: ask the user.\n"
        )
    return gate_scope.printable(
        f"blocked: gate failed (`{_shown(gate)}`) {scope}, in {cwd}\n"
        f"{guardrails.redact_secrets(tail)}\n{hint}Fix the findings, or ask the user."
    )


def skip_notice(cwd: str, withheld: Sequence[str] = ()) -> str:
    """For the operator, in `systemMessage`, which a block's exit 2 still carries (measured on the
    CLI 2.1.317) and the model does not get. ``withheld``: as in :func:`block_message`."""
    note = (
        f" The gate ran without {_withheld(withheld)} (names that look like credentials are "
        "withheld from it); if it failed for want of one, skipping is the way to commit."
        if withheld
        else ""
    )
    return gate_scope.printable(
        f"agentic-forge test-gate blocked this. To skip it, set `test_gate.skip: true` in {cwd}/"
        ".agentic-forge/config.json in a separate call first: the hook runs before the command."
        + note
    )


def decide(
    payload: dict[str, Any], notes: list[str] | None = None
) -> tuple[guardrails.Decision, str]:
    """The decision, and the directory it was taken in: where the commit acts, not where the call
    started. `cd .. && git commit` and `git -C <root> commit` are gated (and configured) as the
    root, within the start directory's own work tree only (ADR 0111). Operator notices not yet
    printed are appended to ``notes``."""
    start = str(payload.get("cwd") or ".")
    if payload.get("tool_name") != "Bash":
        return guardrails.ALLOW, start
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not guardrails.is_commit_or_push(command):
        return guardrails.ALLOW, start
    cwd = guardrails.commit_dir(command, start)
    return _gate(payload, command, cwd, [] if notes is None else notes), cwd


def gate_decision(payload: dict[str, Any]) -> guardrails.Decision:
    return decide(payload)[0]


def _gate(payload: dict[str, Any], command: str, cwd: str, notes: list[str]) -> guardrails.Decision:
    # resolve config only once we know it's a commit/push (keep the cheap filters first)
    if settings.resolve(cwd).skip_test_gate:
        return guardrails.ALLOW
    gate = guardrails.choose_gate(cwd)
    if not gate:
        return guardrails.ALLOW
    narrowed = gate_scope.narrow(gate, command, cwd)
    if narrowed is None:
        return guardrails.ALLOW
    scoped = narrowed != gate
    shape = not scoped and gate in gate_scope.NARROWABLE and not gate_scope.parse_simple(command)
    # Resolve the tool the way the project does (project-local bins first) and hand the gate a PATH
    # that includes them, so a package script's own linter resolves too (ADR 0081) — but not a bin
    # directory the repository itself ships, and say so (ADR 0115). Read once, for every use below.
    session_id = payload.get("session_id")
    dirs = guardrails.bin_dirs(cwd, package_script=gate[0] in stacks.PACKAGE_MANAGERS)
    if dirs.script_skipped:
        # npm/pnpm/yarn would put the ignored directory back on the script's PATH: no run at all.
        notice = script_skip_notice(gate, dirs.script_skipped, cwd)
        print(notice, file=sys.stderr)
        diagnostics.emit(
            cwd, kind="anomaly", component="commit-gate",
            message=f"gate not run (untrusted node_modules/.bin): `{' '.join(gate)}`",
            severity="minor", context={"skipped": _named(dirs.script_skipped)},
            session_id=session_id,
        )  # fmt: skip
        if _once_for(cwd, "script", dirs.script_skipped, session_id):
            notes.append(notice)
        return guardrails.ALLOW
    if dirs.skipped:
        notice = skipped_tools_notice(dirs.skipped)
        print(notice, file=sys.stderr)  # the model's channel on a block
        if _once_for(cwd, "dirs", dirs.skipped, session_id):
            notes.append(  # the operator's, in the run's one `systemMessage`
                f"{notice} For a repository you do not trust, set `test_gate.skip: true` in "
                f"{gate_scope.printable(cwd, keep='')}/.agentic-forge/config.json."
            )
    env = guardrails.gate_env(cwd, dirs=dirs)
    gate = guardrails.resolve_gate(gate, cwd, dirs, env["PATH"])
    ran, found, timeout = gate, "", float(_GATE_TIMEOUT)
    if scoped:
        # A narrowed failure only says there is something to look at. An explicit path reaches what
        # `ruff check .` does not walk, so the whole gate decides, as it always did (ADR 0101).
        started = time.monotonic()
        ran = guardrails.resolve_gate(narrowed, cwd, dirs, env["PATH"])
        first = _run_gate(ran, cwd, payload, notes=notes, env=env)
        if first is None or first.returncode == 0:
            return guardrails.ALLOW
        found = ((first.stdout or "") + "\n" + (first.stderr or "")).strip()[-500:]
        timeout = max(1.0, timeout - (time.monotonic() - started))
    result = _run_gate(gate, cwd, payload, timeout=timeout, notes=notes, env=env)
    if result is None:
        return guardrails.ALLOW
    if result.returncode != 0:
        # Join with a newline so a signature can't be spuriously formed or destroyed across the
        # stdout/stderr boundary (ADR 0059).
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        tail = combined.strip()[-500:]
        unrunnable = (
            guardrails.gate_unrunnable(combined)
            or result.returncode in guardrails.GATE_UNRUNNABLE_EXIT_CODES
        )
        if unrunnable:
            # The gate couldn't RUN (missing lint script / uninstalled linter / shell exit 127/126)
            # — environment breakage, not a code-quality failure. Fail OPEN (don't block a commit
            # for it), but record the downgrade so it's auditable (ADR 0058/0059).
            diagnostics.emit(
                cwd, kind="anomaly", component="commit-gate",
                message=f"gate unrunnable (fail-open): (`{' '.join(gate)}`)\n{tail}",
                severity="minor", context={"gate": " ".join(gate)},
                session_id=payload.get("session_id"),
            )
            _announce(cwd, gate, tail.splitlines()[-1] if tail else "no output",
                      payload.get("session_id"), notes)
            return guardrails.ALLOW
        return guardrails.Decision(
            True,
            block_message(
                ran, cwd, scoped=scoped, tail=found or tail, shape=shape,
                moved=cwd != str(payload.get("cwd") or "."),
                # a hint for the model only where the output reads like a refused credential
                withheld=(
                    guardrails.withheld_names()
                    if guardrails.looks_like_auth_failure(f"{found}\n{combined}")
                    else ()
                ),
            ),
        )
    return guardrails.ALLOW


def main() -> int:
    cwd = "."
    session_id: str | None = None
    notes: list[str] = []
    try:
        payload = json.load(sys.stdin)
        cwd = str(payload.get("cwd") or ".")
        session_id = payload.get("session_id")
        decision, where = decide(payload, notes)
    except Exception as exc:  # fail open, but record + announce the hook crash (ADR 0039)
        crash = diagnostics.hook_crash(cwd, "commit-gate", exc, session_id=session_id)
        if crash:
            print(json.dumps(crash))
        return 0
    if decision.block:
        print(f"agentic-forge test-gate {decision.message}", file=sys.stderr)
        # the config file that decided is the one in the directory the gate ran in (ADR 0111)
        notice = skip_notice(where, guardrails.withheld_names())
        print(json.dumps({"systemMessage": "\n".join([*notes, notice])}))
        diagnostics.emit(
            str(payload.get("cwd") or "."), kind="block", component="commit-gate",
            message=decision.message, severity="major", session_id=payload.get("session_id"),
        )
        return 2
    if notes:
        print(json.dumps({"systemMessage": "\n".join(notes)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
