"""Plugin settings & configuration (ADR 0041).

One resolver for the plugin's knobs. **Precedence: built-in DEFAULTS < the per-repo committed
config file (`.agentic-forge/config.json`, validated against `schemas/config.schema.json`) < the
documented env vars** — so CI / one-off overrides still work and the legacy env vars stay
back-compatible.

`resolve()` **never raises**: a missing file is defaults; a malformed / schema-invalid file is
defaults + a one-line stderr warning. Settings must not break a session, and deliberately does
**not** depend on :mod:`diagnostics` (which reads settings — that would be circular).
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import jsonschema

__all__ = ["CONFIG_PATH", "DEFAULTS", "Settings", "resolve"]

CONFIG_PATH = ".agentic-forge/config.json"

DEFAULTS: dict[str, Any] = {
    "diagnostics": {"enabled": False},  # the self-diagnostics log collector (ADR 0039)
    "subagent_budget": {"soft": 25, "hard": 50},  # Task-spawn caps (budget hook)
    "test_gate": {"skip": False},  # skip the pre-commit test gate (commit_gate hook)
    "review": {"passes": 3},  # the bounded review-loop budget N (review-loop.md)
    "external_reviewer": {"enabled": False, "command": "codex"},  # increment 2
    "models": {},  # tier/role -> model id (increment 4); empty = the runner default
    # PR watcher (increment 1, ADR 0044/0045): off by default; outward GitHub writes are opt-in.
    # `repos` (owner/name) are the repos the scheduled hourly job watches (empty = none).
    "pr_watcher": {"enabled": False, "bot": "github-actions[bot]", "max_threads": 10, "repos": []},
}


@dataclass(frozen=True)
class Settings:
    """The resolved plugin configuration (defaults < file < env)."""

    diagnostics_enabled: bool
    subagent_soft: int
    subagent_hard: int
    skip_test_gate: bool
    review_passes: int
    external_reviewer_enabled: bool
    external_reviewer_command: str
    models: dict[str, str]
    pr_watcher_enabled: bool
    pr_watcher_bot: str
    pr_watcher_max_threads: int
    pr_watcher_repos: list[str]


def _schema() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "schemas" / "config.schema.json"
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _coerce_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _coerce_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively overlay ``over`` onto ``base`` (mutates + returns ``base``)."""
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_file(repo: Path | str) -> dict[str, Any]:
    """Read + schema-validate the repo config file; ``{}`` if absent/invalid (with a warning)."""
    path = Path(repo) / CONFIG_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"agentic-forge: ignoring unreadable {CONFIG_PATH}: {exc}", file=sys.stderr)
        return {}
    errors = sorted(jsonschema.Draft7Validator(_schema()).iter_errors(data), key=str)
    if errors:
        msg = errors[0].message
        print(f"agentic-forge: ignoring invalid {CONFIG_PATH}: {msg}", file=sys.stderr)
        return {}
    return cast("dict[str, Any]", data)


def resolve(repo: Path | str, *, env: dict[str, str] | None = None) -> Settings:
    """Resolve the plugin :class:`Settings` for ``repo`` (defaults < config file < env)."""
    src = os.environ if env is None else env
    data = _deep_merge(copy.deepcopy(DEFAULTS), _load_file(repo))

    # Legacy env-var overrides (back-compat; env wins over the file). An empty value is treated as
    # "unset" (skip) — consistent with the int vars below — so `export VAR=` can't clobber the file.
    if src.get("AGENTIC_FORGE_DIAGNOSTICS"):
        data["diagnostics"]["enabled"] = _coerce_bool(src["AGENTIC_FORGE_DIAGNOSTICS"])
    soft = _coerce_int(src.get("AGENTIC_FORGE_SUBAGENT_SOFT"))
    if soft is not None:
        data["subagent_budget"]["soft"] = soft
    hard = _coerce_int(src.get("AGENTIC_FORGE_SUBAGENT_HARD"))
    if hard is not None:
        data["subagent_budget"]["hard"] = hard
    if src.get("AGENTIC_FORGE_SKIP_TEST_GATE"):
        data["test_gate"]["skip"] = True

    return Settings(
        diagnostics_enabled=bool(data["diagnostics"]["enabled"]),
        subagent_soft=int(data["subagent_budget"]["soft"]),
        subagent_hard=int(data["subagent_budget"]["hard"]),
        skip_test_gate=bool(data["test_gate"]["skip"]),
        review_passes=int(data["review"]["passes"]),
        external_reviewer_enabled=bool(data["external_reviewer"]["enabled"]),
        external_reviewer_command=str(data["external_reviewer"]["command"]),
        models={str(k): str(v) for k, v in (data["models"] or {}).items()},
        pr_watcher_enabled=bool(data["pr_watcher"]["enabled"]),
        pr_watcher_bot=str(data["pr_watcher"]["bot"]),
        pr_watcher_max_threads=int(data["pr_watcher"]["max_threads"]),
        pr_watcher_repos=[str(r) for r in (data["pr_watcher"].get("repos") or [])],
    )
