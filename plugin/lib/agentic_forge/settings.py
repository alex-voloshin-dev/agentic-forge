"""Plugin settings & configuration (ADR 0041; user-level layer ADR 0049).

One resolver for the plugin's knobs. **Precedence: built-in DEFAULTS < the user-level config
(`~/.agentic-forge/config.json`, cross-project) < the per-repo committed config
(`.agentic-forge/config.json`) < the documented env vars** — so a user sets defaults once in their
home, a repo overrides them per-project, and CI / one-off env vars still win. Both files are
validated against `schemas/config.schema.json`.

`resolve()` **never raises**: a missing file is defaults; a malformed / schema-invalid file is
defaults + a one-line warning — printed to stderr and carried on ``Settings.warnings``, which the
session-start hook shows once per session (a hook's stderr reaches nobody). `jsonschema` is
imported **lazily and is optional** — a guardrail hook may run under a bare `python3` without the
plugin's third-party deps, so when it is unavailable a committed (trusted) file is loaded
*unvalidated* rather than dropped, and resolve still coerces every value defensively. Settings
must not break a session, and deliberately does **not** depend on :mod:`diagnostics` (which reads
settings — that would be circular).
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
    # Generated state (logs, queues, job state) goes to the USER level unless this is on (ADR 0072).
    "state": {"in_repo": False},
    "diagnostics": {"enabled": False},  # the self-diagnostics log collector (ADR 0039)
    # The PostToolUse audit trail (ADR 0019). ON by default — it is the only record of what the
    # agent actually did, and the field evidence this project runs on. The switch exists because
    # until 2026.7.10 it was the one writer with no way to turn it off (ADR 0078).
    # Rotation bounds. The audit log is a BOUNDED ROLLING WINDOW, not durable history: at ~8 MB
    # per ten days on one active repo (field measurement) the default reaches rotation inside a
    # fortnight, and the trim discards the oldest records. Raise these if the history must last;
    # collect a diagnostics bundle if it must be kept (ADR 0080).
    "logs": {
        "enabled": True,
        "max_bytes": 10 * 1024 * 1024,
        "keep_bytes": 5 * 1024 * 1024,
        # Gzipped archives of rotated-out records kept beside the live log (ADR 0081).
        # 0 restores the pre-2026.9.1 behaviour: the oldest records are simply discarded.
        "archives": 6,
    },
    "subagent_budget": {"soft": 25, "hard": 50},  # Task-spawn caps (budget hook)
    "test_gate": {"skip": False},  # skip the pre-commit test gate (commit_gate hook)
    # The deterministic pre-router (ADR 0089): names the matching skill in each prompt's context.
    # OFF by default: measured at +0.095 over the session note (z = 1.27, inside noise) on a stand
    # ADR 0090 then found empty, so the null result is uninterpretable; the honest baseline
    # (ADR 0091) left it nothing to fix, so it does not ship on.
    "pre_router": {"enabled": False},
    # The SessionStart routing note (2026.9.3). On by default; the switch exists so its contribution
    # can be MEASURED with it off (ADR 0092) — and so an operator who finds it noise can drop it.
    "routing_note": {"enabled": True},
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
        # auto_watch is ON by default *within an enabled watcher* (ADR 0069): `enabled` is the
        # master switch, and once a user has opted into the watcher, watching the PRs they create
        # is the expected behaviour. It still only ENQUEUES — merging needs auto_merge (off).
        "auto_watch": True,
        "max_ticks": 144,  # 24 h at the 10-minute drain cadence — nothing is watched forever
        "merge_method": "rebase",
        "poll_seconds": 600,
    },
}


@dataclass(frozen=True)
class Settings:
    """The resolved plugin configuration (defaults < user file < repo file < env)."""

    diagnostics_enabled: bool
    logs_enabled: bool
    logs_max_bytes: int
    logs_keep_bytes: int
    logs_archives: int
    state_in_repo: bool
    subagent_soft: int
    subagent_hard: int
    skip_test_gate: bool
    pre_router_enabled: bool
    routing_note_enabled: bool
    review_passes: int
    external_reviewer_enabled: bool
    external_reviewer_command: str
    models: dict[str, str]
    pr_watcher_enabled: bool
    pr_watcher_bot: str
    pr_watcher_max_threads: int
    pr_watcher_repos: list[str]
    pr_watcher_auto_merge: bool
    pr_watcher_auto_watch: bool
    pr_watcher_max_ticks: int
    pr_watcher_merge_method: str
    pr_watcher_poll_seconds: int
    # One line per config file that was DROPPED on the way here. A malformed or schema-invalid
    # file is ignored whole, so a `test_gate.skip` or `pr_watcher.enabled` in it is silently
    # ineffective — and the stderr line that says so reaches nobody from a hook (exit-0 stderr is
    # debug-log only). The session-start hook surfaces these once per session instead.
    warnings: tuple[str, ...] = ()


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


def _dropped(reason: str) -> str:
    """The warning for a config file resolve had to ignore: printed to stderr (kept — it costs
    nothing) and returned for :attr:`Settings.warnings`. It spells out the consequence, because
    "ignoring" alone did not convey that every switch in the file is now at its default."""
    warning = (
        f"agentic-forge: {reason} — the whole file is dropped, so every setting in it is at its "
        f"built-in default until it is fixed"
    )
    print(warning, file=sys.stderr)
    return warning


def _load_config(path: Path) -> tuple[dict[str, Any], str]:
    """Read + schema-validate ONE ``config.json`` -> ``(data, warning)``: ``({}, "")`` if absent,
    ``({}, why)`` if unreadable / invalid (see :func:`_dropped`). ``jsonschema`` is imported
    **lazily and optionally**: when it is unavailable (a hook under a bare ``python3``) a committed
    JSON object is loaded *unvalidated* rather than dropped — :func:`resolve` then coerces every
    value defensively."""
    if not path.is_file():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {}, _dropped(f"ignoring unreadable {path}: {exc}")
    try:
        import jsonschema
    except ImportError:
        # No validator available — trust the committed file, but only if it is a JSON object.
        if isinstance(data, dict):
            return cast("dict[str, Any]", data), ""
        return {}, _dropped(f"ignoring invalid {path}: not a JSON object")
    errors = sorted(jsonschema.Draft7Validator(_schema()).iter_errors(data), key=str)
    if errors:
        return {}, _dropped(f"ignoring invalid {path}: {errors[0].message}")
    return cast("dict[str, Any]", data), ""


def _settings_from(data: dict[str, Any], warnings: tuple[str, ...] = ()) -> Settings:
    """Build :class:`Settings` from a merged config mapping, coercing every value so a stray type in
    an unvalidated file can't raise (resolve wraps this and falls back to pure defaults if it
    somehow still does). ``warnings`` are carried through untouched."""
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
        logs_enabled=_coerce_bool(data["logs"]["enabled"]),
        logs_max_bytes=_coerce_int(data["logs"]["max_bytes"]) or DEFAULTS["logs"]["max_bytes"],
        logs_keep_bytes=_coerce_int(data["logs"]["keep_bytes"]) or DEFAULTS["logs"]["keep_bytes"],
        logs_archives=_int(data["logs"].get("archives"), DEFAULTS["logs"]["archives"]),
        state_in_repo=_coerce_bool((data.get("state") or {}).get("in_repo")),
        subagent_soft=_int(data["subagent_budget"]["soft"], DEFAULTS["subagent_budget"]["soft"]),
        subagent_hard=_int(data["subagent_budget"]["hard"], DEFAULTS["subagent_budget"]["hard"]),
        skip_test_gate=_coerce_bool(data["test_gate"]["skip"]),
        pre_router_enabled=_coerce_bool((data.get("pre_router") or {}).get("enabled", False)),
        routing_note_enabled=_coerce_bool((data.get("routing_note") or {}).get("enabled", True)),
        review_passes=_int(data["review"]["passes"], DEFAULTS["review"]["passes"]),
        external_reviewer_enabled=_coerce_bool(data["external_reviewer"]["enabled"]),
        external_reviewer_command=str(data["external_reviewer"]["command"]),
        models={str(k): str(v) for k, v in models.items()},
        pr_watcher_enabled=_coerce_bool(pr["enabled"]),
        pr_watcher_bot=str(pr["bot"]),
        pr_watcher_max_threads=_int(pr["max_threads"], DEFAULTS["pr_watcher"]["max_threads"]),
        pr_watcher_repos=[str(r) for r in repos],
        # `is True` — NOT _coerce_bool: merging is irreversible, so it demands the exact documented
        # boolean rather than the widened truthy set ("yes"/"on"/1) that a config slipping past an
        # absent `jsonschema` could otherwise carry (ADR 0067).
        pr_watcher_auto_merge=pr.get("auto_merge") is True,
        pr_watcher_auto_watch=pr.get("auto_watch") is True,
        pr_watcher_max_ticks=_int(pr.get("max_ticks"), DEFAULTS["pr_watcher"]["max_ticks"]),
        pr_watcher_merge_method=method,
        pr_watcher_poll_seconds=_int(
            pr.get("poll_seconds"), DEFAULTS["pr_watcher"]["poll_seconds"]
        ),
        warnings=warnings,
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
    user_data, user_warning = _load_config(home_dir / CONFIG_PATH)  # user-level (cross-project)
    repo_data, repo_warning = _load_config(Path(repo) / CONFIG_PATH)  # per-repo (overrides it)
    _deep_merge(data, user_data)
    _deep_merge(data, repo_data)
    warnings = tuple(w for w in (user_warning, repo_warning) if w)

    try:
        # Legacy env-var overrides (back-compat; env wins over both files). An empty value is
        # treated as "unset" (skip) so `export VAR=` can't clobber a file. Inside the try so a
        # malformed (unvalidated) file that left a non-mapping in place can't raise here either.
        if src.get("AGENTIC_FORGE_DIAGNOSTICS"):
            data["diagnostics"]["enabled"] = _coerce_bool(src["AGENTIC_FORGE_DIAGNOSTICS"])
        if src.get("AGENTIC_FORGE_LOGS"):
            data["logs"]["enabled"] = _coerce_bool(src["AGENTIC_FORGE_LOGS"])
        soft = _coerce_int(src.get("AGENTIC_FORGE_SUBAGENT_SOFT"))
        if soft is not None:
            data["subagent_budget"]["soft"] = soft
        hard = _coerce_int(src.get("AGENTIC_FORGE_SUBAGENT_HARD"))
        if hard is not None:
            data["subagent_budget"]["hard"] = hard
        if src.get("AGENTIC_FORGE_SKIP_TEST_GATE"):
            # _coerce_bool like every other switch: `=0` / `=false` used to DISABLE the commit
            # gate, because any non-empty value was taken as "skip".
            data["test_gate"]["skip"] = _coerce_bool(src["AGENTIC_FORGE_SKIP_TEST_GATE"])
        if src.get("AGENTIC_FORGE_ROUTING_NOTE"):
            data.setdefault("routing_note", {})["enabled"] = _coerce_bool(
                src["AGENTIC_FORGE_ROUTING_NOTE"]
            )
        if src.get("AGENTIC_FORGE_PRE_ROUTER"):
            data.setdefault("pre_router", {})["enabled"] = _coerce_bool(
                src["AGENTIC_FORGE_PRE_ROUTER"]
            )
        return _settings_from(data, warnings)
    except Exception as exc:
        # An unvalidated (no-jsonschema) malformed file slipped through; never raise — fall back to
        # pure defaults (a session / guardrail hook must not break on a bad config), and say so.
        dropped = _dropped(f"ignoring malformed config ({type(exc).__name__}: {exc})")
        return _settings_from(copy.deepcopy(DEFAULTS), (*warnings, dropped))
