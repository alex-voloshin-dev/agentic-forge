#!/usr/bin/env python3
"""Tier-2 quality eval runner for the engine roles (reviewer, grader, software-engineer,
architect, security-engineer, qa-engineer, reader).

Usage:
    python dev/run_agent_evals.py --runner dry            # verify wiring, no model calls
    python dev/run_agent_evals.py --runner claude         # real run via your Claude subscription
    python dev/run_agent_evals.py --runner api            # real run via API key (per-token)
    python dev/run_agent_evals.py --role reviewer ...     # one role (repeatable)
    python dev/run_agent_evals.py --runner claude --role reviewer \
        --claude-md plugin/eval/fixtures/claude-md/typical-project.md --omit-claude-md on
                                                          # one arm of the omitClaudeMd A/B

`dry` needs no credentials and never calls a model: it checks that every contract, role
prompt, and fixture resolves. `claude` (recommended) shells out to the `claude` CLI, so it
uses your Claude Code auth — a subscription via CLAUDE_CODE_OAUTH_TOKEN (`claude
setup-token`); make sure ANTHROPIC_API_KEY is unset or it takes precedence and bills per
token. `api` uses the Anthropic Messages SDK and always bills per token. Both run each role's
cases N times, grade with the grader role, aggregate, and gate against the contract's tier2
thresholds. See docs/eval-runbook.md.

On `claude`, each session follows its role's `omitClaudeMd` frontmatter — the role under test
(`--omit-claude-md` overrides it) and the judge (always `grader.md`'s) — and `--claude-md` puts a
project CLAUDE.md into every case's workspace (ADR 0113, amended).

Exit code 0 if every selected role's gate passes (or dry-run is clean), 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # dev/ — for the _eval_cli sibling

import _eval_cli  # noqa: E402
from agentic_forge import agent_eval, benchmark, models, settings  # noqa: E402
from agentic_forge.frontmatter import parse as parse_frontmatter  # noqa: E402


def _role_tools(plugin_dir: Path, role: str) -> str:
    fm, _ = parse_frontmatter((plugin_dir / "agents" / f"{role}.md").read_text(encoding="utf-8"))
    return str(fm.get("tools", "Read, Grep, Glob"))


def _build_runners(
    runner: str,
    role: str,
    plugin_dir: Path,
    model: str,
    *,
    grader_model: str | None = None,
    omit_claude_md: bool | None = None,
    grader_omit_claude_md: bool | None = None,
) -> tuple[agent_eval.Runner, agent_eval.Runner]:
    """Build (role_runner, grader_runner): resolve the role's tools, then delegate to the shared
    transport core in `_eval_cli` (one construction site for both the agent and skill runners)."""
    return _eval_cli.build_runners(
        runner,
        allowed_tools=_role_tools(plugin_dir, role),
        model=model,
        plugin_dir=plugin_dir,
        grader_model=grader_model,
        omit_claude_md=omit_claude_md,
        grader_omit_claude_md=grader_omit_claude_md,
    )


def _claude_md_label(path: Path, text: str) -> str:
    """``<file name>@sha256:<12 hex>``: names the workspace CLAUDE.md in the benchmark, and moves
    when its content does, so two runs on different files are never compared as one setup."""
    return f"{path.name}@sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"


# Where every `--claude-md` run leaves its arm (the benchmark record, the probe and pass/fail),
# beside the benchmark history but apart from it: an A/B arm is a measurement, not a release
# baseline, and the arm that lost quality is exactly the one the history's healthy-only rule would
# not keep. Run the two arms one after the other, never at once: each run reads, then rewrites it.
AB_FILE = "claude-md-ab.json"


def _load_arms(path: Path) -> list[dict[str, Any]]:
    """The recorded A/B arms. A missing file is an empty list; an unreadable or malformed one is an
    error — never read as empty and overwritten, which would lose every arm recorded so far."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        reason = f"{path} is not readable JSON ({exc}); move it aside to start over"
        raise ValueError(reason) from None
    if not isinstance(data, list):
        raise ValueError(f"{path} does not hold a list of A/B arms; move it aside to start over")
    return data


def _save_arms(path: Path, arms: list[dict[str, Any]]) -> None:
    """Write the arms atomically: a temp file in the same directory, then ``os.replace`` — an
    interrupted write leaves the old file whole, never a truncated one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(arms, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _temp_root() -> Path:
    """Where the case and probe workspaces are made (`tempfile`'s root, i.e. TMPDIR)."""
    return Path(tempfile.gettempdir())


def _build_probe(*, model: str, plugin_dir: Path, omit_claude_md: bool) -> agent_eval.Runner:
    """The A/B probe's runner, built from the role's own component environment (`_eval_cli`)."""
    return _eval_cli.build_claude_md_probe(
        model=model, plugin_dir=plugin_dir, omit_claude_md=omit_claude_md
    )


def _git_state(prov: dict[str, str]) -> tuple[str, bool | None]:
    """``(commit, dirty)`` from the provenance's ``git`` (``sha[+dirty][+status-unknown]``); dirty
    is None when the status check itself failed."""
    git = str(prov.get("git", "?"))
    if "+status-unknown" in git:
        return git.split("+")[0], None
    return git.split("+")[0], "+dirty" in git


def _fmt(value: Any, spec: str = ".0f") -> str:
    return format(float(value), spec) if isinstance(value, (int, float)) else "n/a"


def _ab_check(
    report: Any,
    *,
    role: str,
    model: str,
    grader_model: str,
    plugin_dir: Path,
    ab_path: Path,
    fixture_text: str,
    probe: dict[str, Any],
    prov: dict[str, str],
) -> tuple[list[str], bool | None]:
    """Record this arm and judge the A/B's manipulation (ADR 0113, amended).

    The validity test is the probe, not a token total: a session's tokens sum up to 40 turns that
    each re-read the whole cached context, so two identical arms differ by more than a CLAUDE.md
    about half the time. The probe asks one question whose answer depends only on what was loaded:
    the "off" arm (file loaded) must quote the file's first heading, the "on" arm must not. An arm
    whose probe is not as expected is INVALID on its own. A pair is VALID when both are as expected
    and the arms share role, model, judge, file, runner, ``claude --version`` and input
    ``fingerprint``. Token and cost differences are printed as the measured saving, information
    only. Returns the lines to print and True / False, or None while the other arm is missing."""
    bench = report.benchmark
    arm = str(bench.get("omit_claude_md", "?"))
    heading = agent_eval.first_heading(fixture_text) or ""
    answer = probe.get("answer")
    if answer is None:
        quoted = False
        ok = False
        probe_line = f"probe session failed ({probe.get('error', 'no answer')})"
    else:
        quoted = agent_eval.quotes_heading(str(answer), heading)
        ok = quoted if arm == "off" else not quoted
        probe_line = (
            f"probe answered {str(answer)[:120]!r}: the file's heading {heading!r} is "
            f"{'quoted' if quoted else 'not quoted'}"
        )
    commit, dirty = _git_state(prov)
    record = benchmark.make_record(role, model, bench)
    record.update(
        passed=bool(report.passed),
        fingerprint=agent_eval.input_fingerprint(plugin_dir, role, fixture_text),
        git=commit,
        dirty=dirty,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        probe_answer=answer,
        probe_prompt_tokens=probe.get("prompt_tokens"),
        probe_ok=ok,
    )
    arms = _load_arms(ab_path)
    version = bench.get("claude_version")
    unknown_cli = version in (None, "unknown")
    # Two arms whose CLI version is unknown cannot be shown to share the CLI that applied the
    # switch, so they are never paired.
    other = None if unknown_cli else benchmark.ab_counterpart(
        arms,
        role,
        model,
        grader_model=grader_model,
        setup=benchmark.run_setup(bench),
        claude_version=version,
        fingerprint=record["fingerprint"],
    )
    arms.append(record)
    _save_arms(ab_path, arms)

    state = "omitted" if arm == "on" else "loaded"
    lines = [
        f"  A/B arm {arm} (CLAUDE.md {state}): {probe_line} — "
        f"{'as expected' if ok else 'NOT as expected'}; recorded in {ab_path}"
    ]
    if record.get("prompt_tokens") is None:
        lines.append(f"  A/B arm {arm}: this arm reported no prompt tokens; its cost is unknown")
    else:
        lines.append(
            f"  A/B arm {arm}: prompt_tokens/run={_fmt(record['prompt_tokens'])}, "
            f"cost/run=${_fmt(record.get('cost_usd'), '.4f')}, "
            f"answered sessions/run={_fmt(record.get('answered_sessions'), 'g')} (information)"
        )
    if not ok:
        lines.append(
            f"  A/B check: INVALID — the {arm} arm's probe shows the switch did not act as asked; "
            "discard this arm and fix the setup before reading any A/B"
        )
        return lines, False
    if unknown_cli:
        lines.append(
            "  A/B check: this arm is sound but cannot be paired: `claude --version` did not "
            "answer, so no other arm can be shown to have run on the same CLI"
        )
        return lines, None
    if other is None:
        lines.append(
            "  A/B check: this arm is sound; no other arm with the same inputs "
            f"(fingerprint {record['fingerprint'][:12]}, same model, judge, runner and CLI) yet. "
            "Run the other arm next; the pair is valid only if both probes are as expected."
        )
        return lines, None
    off, on = (record, other) if arm == "off" else (other, record)
    dirty_note = {True: " (dirty)", None: " (status unknown)"}.get(other.get("dirty"), "")
    lines.append(
        f"  A/B pair: the other arm ran at git {other.get('git', '?')}{dirty_note} "
        f"on {other.get('timestamp', '?')}"
    )
    if other.get("git") != record.get("git"):
        lines.append(
            f"  A/B pair: WARNING — the arms ran at different commits ({other.get('git')} vs "
            f"{record.get('git')}); their inputs match, the rest of the tree may not"
        )
    if other.get("n") != record.get("n"):
        lines.append(
            "  A/B pair: WARNING — the arms measured different numbers of runs "
            f"(n={other.get('n')} vs n={record.get('n')}); weigh their pass-rates accordingly"
        )
    gaps = []
    for key, label, spec in (
        ("probe_prompt_tokens", "probe prompt tokens", ".0f"),
        ("prompt_tokens", "prompt_tokens/run", ".0f"),
        ("cost_usd", "cost/run $", ".4f"),
    ):
        if isinstance(off.get(key), (int, float)) and isinstance(on.get(key), (int, float)):
            gaps.append(f"{label} off-on={float(off[key]) - float(on[key]):{spec}}")
    if gaps:
        lines.append("  A/B saving (information): " + ", ".join(gaps))
    valid = bool(other.get("probe_ok"))
    lines.append(
        "  A/B check: VALID — both probes as expected"
        if valid
        else "  A/B check: INVALID — the other arm's probe was not as expected; re-run that arm"
    )
    return lines, valid


def _claude_md_fields(
    mode: str, omit: bool, grader_omit: bool, label: str | None
) -> dict[str, Any]:
    """The benchmark's record of a run's CLAUDE.md setup (ADR 0113, amended)."""
    fields: dict[str, Any] = {
        "omit_claude_md": "on" if omit else "off",
        "omit_claude_md_mode": mode,
        "grader_omit_claude_md": "on" if grader_omit else "off",
    }
    if label is not None:
        fields["claude_md"] = label
    return fields


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run Tier-2 quality evals for engine roles.")
    parser.add_argument("--plugin", type=Path, default=_REPO_ROOT / "plugin")
    parser.add_argument("--role", action="append", dest="roles", choices=agent_eval.ROLES)
    parser.add_argument("--runner", choices=["dry", "api", "claude"], default="dry")
    parser.add_argument(
        "--model",
        default=models.TIERS["default"],
        help="the model for unpromoted roles; a role promoted in VALIDATED_TIERS runs at its "
        "shipped tier unless settings.models names another (ADR 0114)",
    )
    parser.add_argument(
        "--grader-model",
        default=None,
        help="the judge's model (default: --model). A role's tier from settings.models never moves "
        "the grader (ADR 0114)",
    )
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument(
        "--isolate",
        action="store_true",
        help="give each case execution a fresh temp workdir (use for write roles)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="append this run to the benchmark history for version-over-version A/B (ADR 0047)",
    )
    parser.add_argument(
        "--benchmark-history",
        type=Path,
        default=None,
        help="history path (default: <repo>/.agentic-forge/benchmark-history.json)",
    )
    parser.add_argument(
        "--omit-claude-md",
        choices=agent_eval.OMIT_CLAUDE_MD_MODES,
        default="role",
        help="whether the role under test runs without CLAUDE.md: 'role' follows its omitClaudeMd "
        "frontmatter, 'on'/'off' force it for an A/B. The judge always follows grader.md "
        "(ADR 0113, amended)",
    )
    parser.add_argument(
        "--claude-md",
        type=Path,
        default=None,
        help="copy this file into every case's workspace as CLAUDE.md (forces per-case isolation)",
    )
    args = parser.parse_args(argv[1:])

    claude_md_text: str | None = None
    claude_md_label: str | None = None
    if args.claude_md is not None:
        if not args.claude_md.is_file():
            parser.error(f"--claude-md: not a file: {args.claude_md}")
        claude_md_text = args.claude_md.read_text(encoding="utf-8")
        claude_md_label = _claude_md_label(args.claude_md, claude_md_text)
        problem = agent_eval.heading_problem(agent_eval.first_heading(claude_md_text))
        if problem:  # the A/B probe asks for the heading, so it must be one only the file has
            parser.error(f"--claude-md: {args.claude_md}: {problem}")
    if args.claude_md is not None and args.workdir is not None:
        parser.error("--claude-md runs every case in a fresh workspace; --workdir would be ignored")
    if args.runner == "api" and (args.claude_md is not None or args.omit_claude_md != "role"):
        parser.error("the api runner loads no CLAUDE.md: --claude-md/--omit-claude-md need claude")
    if args.runner == "claude" and args.claude_md is not None:
        blocked = agent_eval.claude_md_unloadable(_temp_root())
        if blocked:  # the "off" arm would load nothing and measure a second "on" arm
            parser.error(
                f"--claude-md: Claude Code will not load a CLAUDE.md here ({blocked}); "
                "set TMPDIR to a directory outside it"
            )

    plugin_dir: Path = args.plugin.resolve()
    history_path = args.benchmark_history or (
        plugin_dir.parent / ".agentic-forge" / "benchmark-history.json"
    )
    roles = args.roles or list(agent_eval.ROLES)

    if args.runner == "dry":
        ok = True
        for role in roles:
            problems = agent_eval.check_wiring(role, plugin_dir)
            if problems:
                ok = False
                print(f"{role}: NOT READY")
                for problem in problems:
                    print(f"  - {problem}")
            else:
                print(f"{role}: ready")
        print("\nDry-run:", "OK" if ok else "problems found")
        return 0 if ok else 1

    _eval_cli.warn_if_api_key_set(args.runner)

    # Per-component tiers (ADR 0043). A role promoted in the shipped policy runs at that tier
    # unless settings.models says otherwise: a default run measures what live delegation runs
    # (ADR 0114).
    shipped = {role: tier for role, tier in models.VALIDATED_TIERS.items() if tier != "default"}
    models_cfg = {**shipped, **settings.resolve(plugin_dir.parent).models}
    all_passed = True
    prov = _eval_cli.provenance(plugin_dir, args.model)
    print(_eval_cli.provenance_line(prov), flush=True)  # which tree this run is about (ADR 0098)
    grader_model = args.grader_model or args.model  # fixed for the run, whatever a role's tier
    on_cli = args.runner == "claude"  # only a CLI session has a CLAUDE.md to load or omit
    cli_version = _eval_cli.claude_version() if on_cli else None
    ab_path = history_path.with_name(AB_FILE)
    for role in roles:
        model = models.model_for(role, models_cfg, default=args.model)
        omit: bool | None = None
        grader_omit: bool | None = None
        try:
            # Inside the per-role guard: a missing or malformed role file fails this role, not the
            # sweep.
            if on_cli:
                omit = agent_eval.resolve_omit_claude_md(args.omit_claude_md, plugin_dir, role)
                grader_omit = agent_eval.omits_claude_md(plugin_dir, "grader")
            setup = ""
            if omit is not None:
                setup = f", CLAUDE.md={'omitted' if omit else 'loaded'}"
                if claude_md_label:
                    setup += f", workspace CLAUDE.md={claude_md_label}"
            print(
                f"[{role}] running via {args.runner} "
                f"(model={model}, grader={grader_model}{setup})...",
                flush=True,
            )
            refusal = _eval_cli.workspace_refusal(
                args.runner, role, plugin_dir / "agents" / "evals" / f"{role}.evals.json"
            )
            if refusal:  # before this role's runner exists, so before any model call (ADR 0116)
                print(f"error: {refusal}", file=sys.stderr, flush=True)
                all_passed = False
                continue
            role_fn, grader_fn = _build_runners(
                args.runner,
                role,
                plugin_dir,
                model,
                grader_model=grader_model,
                omit_claude_md=omit,
                grader_omit_claude_md=grader_omit,
            )
            report = agent_eval.run_role(
                role,
                plugin_dir,
                run_role_fn=role_fn,
                run_grader_fn=grader_fn,
                runs=args.runs,
                workdir=args.workdir,
                isolate=args.isolate,
                claude_md=claude_md_text,
            )
        except Exception as exc:  # keep going so one role's failure doesn't lose the rest
            print(f"{role}: ERROR — {exc}", flush=True)
            _eval_cli.record_failure(f"agent-eval:{role}", f"{type(exc).__name__}: {exc}")
            all_passed = False
            continue
        report.benchmark["provenance"] = prov  # the benchmark says which tree it measured
        report.benchmark["grader_model"] = grader_model  # and which judge graded it (ADR 0114)
        report.benchmark["runner"] = args.runner  # over which transport (ADR 0113, amended)
        if cli_version is not None:
            report.benchmark["claude_version"] = cli_version
        if omit is not None and grader_omit is not None:  # and with what CLAUDE.md (ADR 0113)
            report.benchmark.update(
                _claude_md_fields(args.omit_claude_md, omit, grader_omit, claude_md_label)
            )
        print(report.summary_line(), flush=True)
        for line in report.evidence_lines():  # which run/case, subtype, num_turns (ADR 0084)
            print(line, flush=True)
        if not report.passed:
            _eval_cli.record_failure(
                f"agent-eval:{role}", "; ".join(report.gate.reasons), kind="anomaly"
            )
        all_passed = all_passed and report.passed
        ab_valid: bool | None = None
        if claude_md_text is not None and on_cli:  # the omitClaudeMd A/B's manipulation check
            try:  # its own guard: a probe or file error fails this role, not the sweep
                probe_fn = _build_probe(
                    model=model, plugin_dir=plugin_dir, omit_claude_md=bool(omit)
                )
                probe = agent_eval.claude_md_probe(
                    probe_fn, agent_eval.role_body(plugin_dir, role), claude_md_text
                )
                ab_lines, ab_valid = _ab_check(
                    report,
                    role=role,
                    model=model,
                    grader_model=grader_model,
                    plugin_dir=plugin_dir,
                    ab_path=ab_path,
                    fixture_text=claude_md_text,
                    probe=probe,
                    prov=prov,
                )
            except Exception as exc:
                print(f"{role}: ERROR in the A/B check — {exc}", flush=True)
                _eval_cli.record_failure(f"agent-eval:{role}", f"{type(exc).__name__}: {exc}")
                all_passed = False
                # Intended: `continue` also skips this role's version check and `--record` — an
                # arm whose manipulation could not be checked is no baseline either.
                continue
            for line in ab_lines:
                print(line, flush=True)
            if ab_valid is False:
                _eval_cli.record_failure(f"agent-eval:{role}", ab_lines[-1], kind="anomaly")
                all_passed = False
        # An INVALID A/B arm stays in claude-md-ab.json but never becomes a baseline: its numbers
        # measured a setup whose switch did not act as asked.
        ver = _eval_cli.version_check(
            report,
            component=role,
            model=model,
            history_path=history_path,
            record=args.record and ab_valid is not False,
        )
        if ver is not None:  # version-over-version A/B (opt-in; only once a baseline exists)
            print(ver, flush=True)
            if not ver.passed:
                _eval_cli.record_failure(
                    f"agent-eval:{role}", "; ".join(ver.reasons), kind="anomaly"
                )
            all_passed = all_passed and ver.passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
