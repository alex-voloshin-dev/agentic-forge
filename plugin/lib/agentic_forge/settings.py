"""Plugin settings & configuration (ADR 0041; user-level layer ADR 0049).

One resolver for the plugin's knobs. **Precedence: built-in DEFAULTS < the user-level config
(`~/.agentic-forge/config.json`, cross-project) < the per-repo committed config
(`.agentic-forge/config.json`) < the documented env vars** — so a user sets defaults once in their
home, a repo overrides them per-project, and CI / one-off env vars still win. Both files are
validated against `schemas/config.schema.json`.

`resolve()` **never raises**: a missing file is defaults; a malformed / schema-invalid file is
defaults + a one-line stderr warning. `jsonschema` is imported **lazily and is optional** — a
guardrail hook may run under a bare `python3` without the plugin's third-party deps, so when it is
unavailable a committed (trusted) file is loaded *unvalidated* rather than dropped, and resolve
still coerces every value defensively. Settings must not break a session, and deliberately does
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

__all__ = ["CONFIG_PATH", "DEFAULTS", "Settings", "resolve"]

# The config file path within each base dir. The user-level file is ``~/<CONFIG_PATH>`` and the
# per-repo file is ``<repo>/<CONFIG_PATH>`` — same relative path, different base (ADR 0049).
CONFIG_PATH = ".agentic-forge/config.json"

DEFAULTS: dict[str, Any] = {
    "diagnostics": {"enabled": False},  # the self-diagnostics log collector (ADR 0039)
    "subagent_budget": {"soft": 25, "hard": 50},  # Task-spawn caps (budget hook)
    "test_gate": {"skip": False},  # skip the pre-commit test gate (commit_gate hook)
    "review": {"passes": 3},  # the bounded review-loop budget N (review-loop.md)
    "external_reviewer": {"enabled": True, "command": "codex"},  # on by default (ADR 0057)
    "models": {},  # tier/role -> model id (increment 4); empty = the runner default
    # PR watcher (increment 1, ADR 0044/0045): off by default; outward GitHub writes are opt-in.
    # `repos` (owner/name) are the repos the scheduled hourly job watches (empty = none).
    "pr_watcher": {
        "enabled": False,
        "bot": "github-actions[bot]",
        "max_threads": 10,
        "repos": [],
        # Autonomous mode (ADR 0063). auto_merge stays OFF by default: a published plugin must not
        # start merging pull requests in every repo that installs it. poll_seconds is also the
        # window an external PR reviewer gets — the gate cannot open before the first post-CI poll.
        "auto_merge": False,
        "merge_method": "rebase",
        "poll_seconds": 600,
    },
}


@dataclass(frozen=True)
class Settings:
    """The resolved plugin configuration (defaults < user file < repo file < env)."""

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
    pr_watcher_auto_merge: bool
    pr_watcher_merge_method: str
    pr_watcher_poll_seconds: int


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


def _int(value: Any, default: int) -> int:
    """``value`` as an int, or ``default`` when it is missing / unparseable — so a stray value in an
    unvalidated config can never make :func:`resolve` raise."""
    parsed = _coerce_int(value)
    return default if parsed is None else parsed


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively overlay ``over`` onto ``base`` (mutates + returns ``base``)."""
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_config(path: Path) -> dict[str, Any]:
    """Read + schema-validate ONE ``config.json``; ``{}`` if absent / unreadable / invalid (with a
    one-line stderr note). ``jsonschema`` is imported **lazily and optionally**: when it is
    unavailable (a hook under a bare ``python3``) a committed JSON object is loaded *unvalidated*
    rather than dropped — :func:`resolve` then coerces every value defensively."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"agentic-forge: ignoring unreadable {path}: {exc}", file=sys.stderr)
        return {}
    try:
        import jsonschema
    except ImportError:
        # No validator available — trust the committed file, but only if it is a JSON object.
        return cast("dict[str, Any]", data) if isinstance(data, dict) else {}
    errors = sorted(jsonschema.Draft7Validator(_schema()).iter_errors(data), key=str)
    if errors:
        print(f"agentic-forge: ignoring invalid {path}: {errors[0].message}", file=sys.stderr)
        return {}
    return cast("dict[str, Any]", data)


def _settings_from(data: dict[str, Any]) -> Settings:
    """Build :class:`Settings` from a merged config mapping, coercing every value so a stray type in
    an unvalidated file can't raise (resolve wraps this and falls back to pure defaults if it
    somehow still does)."""
    pr = data["pr_watcher"]
    models = data["models"] if isinstance(data.get("models"), dict) else {}
    repos = pr["repos"] if isinstance(pr.get("repos"), list) else []
    # A merge is irreversible and the method reaches argv as a flag, so an unknown value falls back
    # to the default rather than being passed through (defence in depth with pr_watch.merge_argv,
    # which raises on one — this layer keeps an unvalidated config from reaching it at all).
    method = str(pr.get("merge_method") or DEFAULTS["pr_watcher"]["merge_method"])
    if method not in ("rebase", "squash", "merge"):
        method = str(DEFAULTS["pr_watcher"]["merge_method"])
    return Settings(
        diagnostics_enabled=_coerce_bool(data["diagnostics"]["enabled"]),
        subagent_soft=_int(data["subagent_budget"]["soft"], DEFAULTS["subagent_budget"]["soft"]),
        subagent_hard=_int(data["subagent_budget"]["hard"], DEFAULTS["subagent_budget"]["hard"]),
        skip_test_gate=_coerce_bool(data["test_gate"]["skip"]),
        review_passes=_int(data["review"]["passes"], DEFAULTS["review"]["passes"]),
        external_reviewer_enabled=_coerce_bool(data["external_reviewer"]["enabled"]),
        external_reviewer_command=str(data["external_reviewer"]["command"]),
        models={str(k): str(v) for k, v in models.items()},
        pr_watcher_enabled=_coerce_bool(pr["enabled"]),
        pr_watcher_bot=str(pr["bot"]),
        pr_watcher_max_threads=_int(pr["max_threads"], DEFAULTS["pr_watcher"]["max_threads"]),
        pr_watcher_repos=[str(r) for r in repos],
        pr_watcher_auto_merge=_coerce_bool(pr.get("auto_merge")),
        pr_watcher_merge_method=method,
        pr_watcher_poll_seconds=_int(
            pr.get("poll_seconds"), DEFAULTS["pr_watcher"]["poll_seconds"]
        ),
    )


def resolve(
    repo: Path | str, *, env: dict[str, str] | None = None, home: Path | str | None = None
) -> Settings:
    """Resolve the plugin :class:`Settings` for ``repo`` — DEFAULTS < user-level file < repo file <
    env. ``home`` overrides the user-config base dir (defaults to :func:`Path.home`; mostly for
    tests/embedding)."""
    src = os.environ if env is None else env
    home_dir = Path.home() if home is None else Path(home)

    data = copy.deepcopy(DEFAULTS)
    _deep_merge(data, _load_config(home_dir / CONFIG_PATH))  # user-level (cross-project)
    _deep_merge(data, _load_config(Path(repo) / CONFIG_PATH))  # per-repo (overrides user-level)

    try:
        # Legacy env-var overrides (back-compat; env wins over both files). An empty value is
        # treated as "unset" (skip) so `export VAR=` can't clobber a file. Inside the try so a
        # malformed (unvalidated) file that left a non-mapping in place can't raise here either.
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
        return _settings_from(data)
    except Exception:
        # An unvalidated (no-jsonschema) malformed file slipped through; never raise — fall back to
        # pure defaults (a session / guardrail hook must not break on a bad config).
        return _settings_from(copy.deepcopy(DEFAULTS))
