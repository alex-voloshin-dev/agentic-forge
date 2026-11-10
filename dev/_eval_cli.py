"""Shared helpers for the dev/ eval-runner CLIs (run_agent/skill/tier1_evals)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from agentic_forge import agent_eval, benchmark, diagnostics, gate, validation

# The variables a skill body may reference as `${VAR}` and expect a live session to resolve. The
# harness PINS these for every Tier-2 and Tier-3 session — to the tree under test, never to whatever
# happens to be installed (ADR 0097) — and a contract test holds every `${VAR}` in a SKILL.md or
# agent body to this set, so a new variable cannot fall into the same hole (ADR 0098).
SESSION_VARS_PINNED: frozenset[str] = frozenset({"CLAUDE_PLUGIN_ROOT", "CLAUDE_SKILL_DIR"})
# Variables a body may reference that the harness deliberately leaves to the real environment.
# None today; add one here WITH the reason, and the contract test will accept it.
SESSION_VARS_INHERITED: frozenset[str] = frozenset()


def session_env(plugin_dir: Path, *, skill_dir: Path | None = None) -> dict[str, str]:
    """The environment a Tier-2/Tier-3 session runs under: every pinned variable, set to the tree
    under test. `CLAUDE_SKILL_DIR` is the skill's own directory when the run is about one skill,
    else the plugin root (a role has no skill of its own)."""
    root = plugin_dir.resolve()
    return {
        "CLAUDE_PLUGIN_ROOT": str(root),
        "CLAUDE_SKILL_DIR": str(skill_dir.resolve() if skill_dir else root),
    }


def _git(plugin_dir: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(plugin_dir), *args], capture_output=True, text=True, timeout=5
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _git_dirty(path: Path) -> bool | None:
    """Whether ``path`` differs from its own repository's HEAD: True / False, or None when the
    status check itself failed (not a repository, git missing, a timeout). ``_git`` turns a failure
    into "", which for `status --porcelain` reads as CLEAN — so a failure must never pass through
    it. Run in ``path``'s own repository (``git -C <path>``), so a root outside the plugin's
    worktree is judged by its own tree, not by a combined call that fails as a whole."""
    try:
        done = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if done.returncode != 0:
        return None
    return bool(done.stdout.strip())


def resolve_skill_roots(
    plugin_dir: Path, explicit: Sequence[Path] | None, *, include: bool = True
) -> list[Path]:
    """The extra skill roots an eval run reads beside the plugin (ADR 0105): none when ``include``
    is off; else the explicit ``--skill-root`` dirs, each of which must exist (a typo must not
    silently measure the shipped listing alone); else the repo's maintainer root when the plugin
    sits in this repository (``validation.maintainer_root``)."""
    if not include:
        return []
    if explicit:
        roots = [p.resolve() for p in explicit]
        for root in roots:
            if not root.is_dir():
                raise ValueError(f"skill root not found: {root}")
        return roots
    default = validation.maintainer_root(plugin_dir.parent)
    return [default] if default is not None else []


def provenance(
    plugin_dir: Path, model: str, skill_roots: Sequence[Path] = ()
) -> dict[str, str]:
    """What a run is actually measuring: the plugin root and its declared version, the git commit
    (with `+dirty` when the tree differs from it), the model, the home the session inherits, the
    interpreter. Printed at the top of every run and stored in the Tier-2 benchmark, because the
    seventh instance of "the check measured something else" (ADR 0097 — Tier-2 graded the
    INSTALLED plugin) would have been visible on its first run had the run said which plugin it
    ran (ADR 0098).

    ``skill_roots`` are the extra skill dirs the run also reads — the maintainer skills (ADR
    0105). They are part of what is measured, so they are named and an edit in one is `+dirty`.
    The plugin and each root are checked on their own (:func:`_git_dirty`); a check that failed
    adds `+status-unknown` — an unknown tree is never reported as clean."""
    root = plugin_dir.resolve()
    roots = [r.resolve() for r in skill_roots]
    version = "?"
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        version = str(manifest.get("version") or "?")
    except (OSError, ValueError):
        pass
    sha = _git(root, "rev-parse", "--short", "HEAD") or "?"
    if sha != "?":
        states = [_git_dirty(root), *(_git_dirty(r) for r in roots)]
        if any(state is True for state in states):
            sha += "+dirty"
        if any(state is None for state in states):
            sha += "+status-unknown"
    return {
        "plugin_root": str(root),
        "skill_roots": ",".join(str(r) for r in roots) or "none",
        "plugin_version": version,
        "git": sha,
        "model": model,
        "home": os.environ.get("HOME", "?"),
        "python": sys.version.split()[0],
    }


def provenance_line(prov: dict[str, str]) -> str:
    return (
        f"measuring: plugin={prov['plugin_root']} version={prov['plugin_version']} "
        f"skill_roots={prov.get('skill_roots', 'none')} "
        f"git={prov['git']} model={prov['model']} home={prov['home']} python={prov['python']}"
    )

_API_KEY_WARNING = (
    "warning: ANTHROPIC_API_KEY is set; the claude CLI uses it before the subscription token. "
    "Unset it to bill this run to your Claude subscription."
)


def warn_if_api_key_set(runner: str) -> None:
    """Warn on stderr when the ``claude`` runner is chosen but ``ANTHROPIC_API_KEY`` is set — it
    takes precedence over the subscription token, so the run would bill per token."""
    if runner == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        print(_API_KEY_WARNING, file=sys.stderr)


def build_runners(
    runner: str,
    *,
    allowed_tools: str,
    model: str,
    plugin_dir: Path | None = None,
    skill_dir: Path | None = None,
) -> tuple[agent_eval.Runner, agent_eval.Runner]:
    """Build (component_runner, grader_runner) for the chosen transport — the one construction
    site shared by the agent and skill Tier-2 CLIs. `claude` keeps the component run and the
    grading on the `claude` CLI (subscription auth, no API key), giving the grader read-only tools
    and a generous turn cap so it can verify on-disk artifacts (level-2) without ever modifying
    them; `api` uses the Anthropic Messages SDK for both (per-token billing). The caller resolves
    `allowed_tools` (a role's or skill's tools) before delegating here.

    `plugin_dir` becomes `CLAUDE_PLUGIN_ROOT` for the session. Ten skill bodies invoke their
    scripts as `${CLAUDE_PLUGIN_ROOT}/skills/<name>/scripts/...`, and until ADR 0097 nothing set it:
    a probe session resolved it to the *installed* plugin instead and graded a build four versions
    behind the tree under test, which makes every such Tier-2 number a statement about someone
    else's code (ADR 0097)."""
    if runner == "api":
        api = agent_eval.api_runner(model)
        return api, api
    if runner == "claude":
        # The turn caps bound a runaway session, not a slow one. A session that hits its cap is
        # `error_max_turns` in the CLI envelope: raised as `TurnCapHit`, never re-run, recorded by
        # the Tier-2 loop as an undetermined case with its `num_turns` on the evidence line — so a
        # cap hit is no longer indistinguishable from a failed case (eval audit, C13).
        env = session_env(plugin_dir, skill_dir=skill_dir) if plugin_dir else None
        component_fn = agent_eval.claude_cli_runner(
            allowed_tools=allowed_tools, model=model, max_turns=40, env=env
        )
        grader_fn = agent_eval.claude_cli_runner(
            allowed_tools="Read,Grep,Glob", model=model, max_turns=20, env=env
        )
        return component_fn, grader_fn
    raise ValueError(f"unknown runner {runner!r}")


def record_failure(
    component: str, message: str, *, kind: str = "error", severity: str = "major"
) -> None:
    """Emit a pipeline diagnostic for a runner crash (``error``) or a gate FAIL (``anomaly``) —
    opt-in (``AGENTIC_FORGE_DIAGNOSTICS``), non-blocking, written to ``./.agentic-forge/`` (ADR
    0039). A no-op when capture is off, so normal runs are unaffected."""
    diagnostics.emit(".", kind=kind, component=component, message=message, severity=severity)


class _Report(Protocol):
    benchmark: dict[str, Any]
    thresholds: dict[str, Any]

    @property
    def passed(self) -> bool: ...


def version_check(
    report: _Report,
    *,
    component: str,
    model: str,
    history_path: str | Path,
    record: bool,
) -> gate.GateResult | None:
    """Version-over-version A/B (ADR 0047): compare ``report`` against the latest same-model record
    in the benchmark history and, if ``record``, append this run — but only when it is **healthy**
    (it passed ``tier2_quality`` *and* did not regress), so a failing/regressed run never poisons
    the baseline. Returns the regression :class:`gate.GateResult`, or ``None`` when there is no
    prior / no ``max_regression`` threshold (the check is opt-in)."""
    history = benchmark.load_history(history_path)
    prior = benchmark.prior_record(history, component, model)
    result = gate.version_regression(report.benchmark, prior, report.thresholds)
    healthy = report.passed and (result is None or result.passed)
    if record and healthy:
        history.append(benchmark.make_record(component, model, report.benchmark))
        benchmark.save_history(history_path, history)
    return result
