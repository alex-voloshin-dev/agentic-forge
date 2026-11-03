"""Plugin settings & configuration (ADR 0041; user-level layer ADR 0049).

One resolver for the plugin's knobs. **Precedence: built-in DEFAULTS < the user-level config
(`~/.agentic-forge/config.json`, cross-project) < the per-repo committed config
(`.agentic-forge/config.json`) < the documented env vars** — so a user sets defaults once in their
home, a repo overrides them per-project, and CI / one-off env vars still win. Both files are
validated against `schemas/config.schema.json`. The exception is `external_reviewer`: `command`,
`isolated`, `model` and `effort` are the operator's and honoured from the user-level file only, and
a repo cannot turn on a user-level `enabled: false` (ADR 0100). `state.in_repo` and
`knowledge.allow_external_vault` are the operator's in the same way (ADR 0102).

`resolve()` **never raises**: a missing file adds nothing; a malformed / schema-invalid / oversized
file adds nothing but a one-line warning — printed to stderr and carried on ``Settings.warnings``,
which the session-start hook shows once per session (a hook's stderr reaches nobody) — except that a
dropped repo file's clear `enabled: false` is kept (ADR 0100). `jsonschema` is
imported **lazily and is optional** — a guardrail hook may run under a bare `python3` without the
plugin's third-party deps, so when it is unavailable a committed (trusted) file is loaded
*unvalidated* rather than dropped, and resolve still coerces every value defensively; the shape of
a value bound for a CLI's argv is checked in code, and it is ignored with a warning if invalid
(ADR 0100). Settings
must not break a session, and deliberately does **not** depend on :mod:`diagnostics` (which reads
settings — that would be circular).
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

__all__ = ["CONFIG_PATH", "CLI_VALUE_PATTERN", "DEFAULTS", "Settings", "resolve", "safe_cli_value"]

# The config file path within each base dir. The user-level file is ``~/<CONFIG_PATH>`` and the
# per-repo file is ``<repo>/<CONFIG_PATH>`` — same relative path, different base (ADR 0049).
CONFIG_PATH = ".agentic-forge/config.json"
# A config file is a few hundred bytes. Past this it is dropped unread, so its size cannot stall a
# hook: decoding and validating are not free, and a repo controls this file (ADR 0100).
_CONFIG_MAX_BYTES = 1024 * 1024

# A config value that reaches a CLI's argv (ADR 0100). No leading dash, so a value cannot become a
# flag. Enforced HERE, deliberately not by a schema `pattern`: a schema failure drops the whole
# file, so one bad value would also switch off `isolated` and everything else in it.
CLI_VALUE_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_CLI_VALUE = re.compile(CLI_VALUE_PATTERN[1:-1])
# `external_reviewer.command`, as set in the user-level file: a bare executable name.
_BARE_COMMAND = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
# The `external_reviewer` keys only the operator may set: removed from a repo file before the merge
# (see _drop_repo_reviewer_settings). `enabled` is deliberately not here.
_OPERATOR_REVIEWER_KEYS = ("command", "isolated", "model", "effort")
# An opt-out as it reads in a file that will not decode: the section's own keys are flat, so `[^{}]`
# stays inside it. Lenient on purpose, since a false match only turns the reviewer off, which a repo
# may do anyway. An escaped `\"` inside a JSON string does not match: its closing quote differs.
_RAW_OPT_OUT = re.compile(
    r"""["']external_reviewer["']\s*:\s*"""
    r"""(?:false\b|\{[^{}]*?["']enabled["']\s*:\s*["']?false\b)""",
    re.IGNORECASE,
)
# What the warning for a dropped file says remains, by where the file was.
_USER_FILE_DROPPED = (
    "the whole file is dropped until it is fixed, except an external_reviewer.enabled: false it "
    "clearly states; the repo config and the built-in defaults apply instead"
)
_REPO_FILE_DROPPED = (
    "the whole file is dropped until it is fixed, except an external_reviewer.enabled: false it "
    "clearly states; the user-level config still applies"
)
_MERGED_CONFIG_DROPPED = (
    "every setting is at its built-in default until it is fixed, except the user-level "
    "external_reviewer settings, state.in_repo and knowledge.allow_external_vault, and an "
    "external_reviewer.enabled: false in either file"
)

DEFAULTS: dict[str, Any] = {
    # Generated state (logs, queues, job state) goes to the USER level unless this is on (ADR 0072).
    # Honoured from the user-level file only (ADR 0102).
    "state": {"in_repo": False},
    # Read and write a vault that resolves outside the repo. Off, because a checkout can commit the
    # link that would take it there. Honoured from the user-level file only (ADR 0102).
    "knowledge": {"allow_external_vault": False},
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
    "external_reviewer": {
        "enabled": True,  # on by default (ADR 0057)
        "command": "codex",
        # Run the CLI without the operator's user config and session files (ADR 0100). Off by
        # default, and there is deliberately no free-form args key beside these. Every key here but
        # `enabled` is honoured from the user-level file only.
        "isolated": False,
        "model": None,
        "effort": None,
    },
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
    external_reviewer_isolated: bool
    external_reviewer_model: str | None
    external_reviewer_effort: str | None
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
    # One line per config file that was DROPPED on the way here, and per single value that was
    # ignored (ADR 0100). A malformed or schema-invalid file is ignored whole, so a
    # `test_gate.skip` or `pr_watcher.enabled` in it is silently ineffective — and the stderr line
    # that says so reaches nobody from a hook (exit-0 stderr is debug-log only). The session-start
    # hook surfaces these once per session instead.
    warnings: tuple[str, ...] = ()
    # The repo's config is what turned the reviewer off, not the operator's: a branch can add that
    # to its own config, so a skip should say so (ADR 0100).
    external_reviewer_disabled_by_repo: bool = False
    knowledge_allow_external_vault: bool = False


def _schema() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "schemas" / "config.schema.json"
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, (list, dict)):  # never truthy, and `str` overflows on a deep one
        return False
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


def _warn(warning: str) -> str:
    """Print ``warning`` to stderr and return it. A closed stderr must not make resolve raise, and
    the line is still carried on :attr:`Settings.warnings`."""
    try:
        print(warning, file=sys.stderr)
    except (OSError, ValueError):
        pass
    return warning


def _dropped(reason: str, consequence: str) -> str:
    """The warning for a config file resolve had to ignore: printed to stderr (kept — it costs
    nothing) and returned for :attr:`Settings.warnings`. It spells out the consequence, because
    "ignoring" alone did not convey what a switch in the file is now doing."""
    return _warn(f"agentic-forge: {reason} — {consequence}")


def _user_reviewer_section(user_data: dict[str, Any]) -> dict[str, Any]:
    """The user-level ``external_reviewer`` mapping, or ``{}`` if it is absent or malformed."""
    section = user_data.get("external_reviewer")
    return cast("dict[str, Any]", section) if isinstance(section, dict) else {}


def safe_cli_value(value: Any) -> str | None:
    """``value`` if it is safe to place in a CLI's argv (:data:`CLI_VALUE_PATTERN`), else ``None``.

    ``fullmatch``, because ``$`` would also accept a trailing newline. This is the only check on
    the value's shape (ADR 0100)."""
    return value if isinstance(value, str) and _CLI_VALUE.fullmatch(value) else None


def _ignored_value(key: str, why: str) -> str:
    """The warning for one value resolve ignored while keeping the rest of the file. It names the
    key and never echoes the value: the file may be repo-controlled and this line reaches the
    session (see :attr:`Settings.warnings`)."""
    return _warn(f"agentic-forge: {key} {why}")


def _reviewer_value(section: dict[str, Any], key: str) -> tuple[str | None, tuple[str, ...]]:
    """An ``external_reviewer`` argv value -> ``(value, warnings)``. Unset is not a problem; an
    invalid value is treated as unset and reported."""
    raw = section.get(key)
    if raw is None:
        return None, ()
    value = safe_cli_value(raw)
    if value is not None:
        return value, ()
    why = f"does not match {CLI_VALUE_PATTERN} — ignored, treated as unset"
    return None, (_ignored_value(f"external_reviewer.{key}", why),)


def _reviewer_command(section: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """``external_reviewer.command`` -> ``(value, warnings)``. Anything but a bare name falls back
    to the default, because this value reaches ``subprocess`` and the reviewer is on by default."""
    value = _command_in_effect(section)
    if "command" not in section or value == section["command"]:
        return value, ()
    why = f"is not a bare executable name — ignored, using the default {value!r}"
    return value, (_ignored_value("external_reviewer.command", why),)


def _command_in_effect(section: dict[str, Any]) -> str:
    """The command a user-level section gives: its own if that is a bare name, else the default."""
    raw = section.get("command")
    if isinstance(raw, str) and _BARE_COMMAND.fullmatch(raw):
        return raw
    return str(DEFAULTS["external_reviewer"]["command"])


def _operator_value_in_effect(key: str, section: dict[str, Any]) -> Any:
    """What a user-level section gives for one of :data:`_OPERATOR_REVIEWER_KEYS`, which is not its
    raw value when that is invalid. Pure: the warning for an invalid value is _settings_from's."""
    if key == "command":
        return _command_in_effect(section)
    if key == "isolated":
        return _coerce_bool(section.get(key, False))
    return safe_cli_value(section.get(key))


def _drop_repo_reviewer_settings(
    repo_data: dict[str, Any], user_data: dict[str, Any]
) -> tuple[str, ...]:
    """Remove from a repo file, before it can be merged, what a repo may not decide about the
    external reviewer, and report it.

    ``command``, ``isolated``, ``model`` and ``effort`` are the operator's (ADR 0100): the repo is
    what gets reviewed, so it must not pick the program that reviews it, drop the operator's whole
    CLI config by asking for isolation, or weaken its own review through the model or effort. A
    user-level ``enabled: false`` holds too, because content goes to a third party. Removing the
    keys here, rather than restoring values after the merge, means no later path can read them. A
    value equal to the one in effect changes nothing, so it gets no warning: the shipped example has
    all four.

    A repo keeps the right to turn the reviewer off. It is reported when that overrides a user-level
    ``true``, since a branch can add it to its own config, and the review then silently does not
    happen."""
    user_section = _user_reviewer_section(user_data)
    warnings: list[str] = []
    if _opted_out(repo_data) and _coerce_bool(user_section.get("enabled", False)):
        why = (
            "is false in this repo's config, which overrides your user-level true — no external "
            "review runs here; a branch can add this to its own config, so check it is intended"
        )
        warnings.append(_ignored_value("external_reviewer.enabled", why))
    section = repo_data.get("external_reviewer")
    if not isinstance(section, dict):
        return tuple(warnings)
    for key in _OPERATOR_REVIEWER_KEYS:
        if key not in section:
            continue
        value = section.pop(key)
        if value != _operator_value_in_effect(key, user_section):
            why = "in a repo config is ignored — only the user-level config can set it"
            warnings.append(_ignored_value(f"external_reviewer.{key}", why))
    if _opted_out(user_data) and _coerce_bool(section.get("enabled", False)):
        del section["enabled"]
        why = "is false in the user-level config, which a repo config cannot turn on — ignored"
        warnings.append(_ignored_value("external_reviewer.enabled", why))
    return tuple(warnings)


def _user_state_in_repo(user_data: dict[str, Any]) -> bool:
    """What the user-level file says about ``state.in_repo``: False if absent or malformed."""
    section = user_data.get("state")
    return _coerce_bool(section.get("in_repo", False)) if isinstance(section, dict) else False


def _user_allows_external_vault(file_data: dict[str, Any]) -> bool:
    """``knowledge.allow_external_vault`` in ``file_data``: False if absent or malformed. ``is
    True``, NOT :func:`_coerce_bool`: "on" is the dangerous side here, as with ``auto_merge``."""
    section = file_data.get("knowledge")
    return isinstance(section, dict) and section.get("allow_external_vault") is True


def _drop_repo_section(
    repo_data: dict[str, Any], name: str, key: str, in_effect: bool
) -> tuple[str, ...]:
    """Remove a one-key section from a repo file before it can be merged, and report it.

    ``state.in_repo`` and ``knowledge.allow_external_vault`` decide where the plugin reads and
    writes, and a checkout must not get to point those at places it has chosen with its own paths
    (ADR 0102). The section holds nothing else, so all of it goes, which also means a non-mapping
    cannot reach the merge. As with the reviewer's keys, a value equal to the one in effect changes
    nothing and gets no warning: the shipped example has both, false."""
    if name not in repo_data:
        return ()
    section = repo_data.pop(name)
    if not isinstance(section, dict):
        return (_ignored_value(name, "in a repo config is ignored — it is not a mapping"),)
    if key not in section or _coerce_bool(section[key]) == in_effect:
        return ()
    why = "in a repo config is ignored — only the user-level config can set it"
    return (_ignored_value(f"{name}.{key}", why),)


def _reviewer_isolated(section: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """``external_reviewer.isolated`` -> ``(value, warnings)``. Uses :func:`_coerce_bool`, NOT the
    ``is True`` of ``auto_merge``: there "on" is the dangerous side, here it is the safe one, so a
    widened truthy value must not silently run without isolation. A non-boolean is still reported,
    because a typo reads as off."""
    raw = section.get("isolated", False)
    value = _coerce_bool(raw)
    if isinstance(raw, bool):
        return value, ()
    why = f"is not a boolean — read as {str(value).lower()}"
    return value, (_ignored_value("external_reviewer.isolated", why),)


def _opted_out(file_data: dict[str, Any]) -> bool:
    """True if one config file's data turns the reviewer off. Content goes to a third party when it
    runs. Anything but a truthy value counts: off is the safe side here."""
    section = file_data.get("external_reviewer")
    if section is False:
        return True
    return (
        isinstance(section, dict) and "enabled" in section and not _coerce_bool(section["enabled"])
    )


def _dropped_file_opts_out(path: Path) -> bool:
    """True if a config file that was dropped still clearly turns the reviewer off, so a typo cannot
    turn a repo's opt-out back on (ADR 0100). Parses what can be parsed: the raw text first, which
    needs no decodable JSON, then the JSON for a file only the schema refused. Reads no further than
    the size limit. A file with neither, such as one in another encoding, says nothing we can read,
    and then the answer is False: its opt-out cannot be known."""
    try:
        with path.open("rb") as handle:
            text = handle.read(_CONFIG_MAX_BYTES).decode("utf-8", "replace")
        if _RAW_OPT_OUT.search(text):
            return True
        data = json.loads(text)
    except Exception:  # the file has already been reported as dropped
        return False
    return isinstance(data, dict) and _opted_out(data)


def _schema_problem(error: Any) -> str:
    """Where a file failed the schema and under which rule, never what it held: the file may be
    repo-controlled and this line reaches the session, so no ``error.message``. A key the schema
    does not itself declare (the free-form names under ``models``) is written ``*``, because that
    name is the file's own text too."""
    schema_path = list(error.absolute_schema_path)
    declared = {schema_path[i + 1] for i, key in enumerate(schema_path[:-1]) if key == "properties"}
    where = "$"
    for part in error.absolute_path:
        if isinstance(part, int):
            where += f"[{part}]"
        else:
            where += f".{part}" if part in declared else ".*"
    return f"{where} fails the schema's {error.validator} rule"


def _load_config(path: Path, consequence: str) -> tuple[dict[str, Any], str]:
    """Read + schema-validate ONE ``config.json`` -> ``(data, warning)``: ``({}, "")`` if absent,
    ``({}, why)`` if unreadable / oversized / invalid (see :func:`_dropped`, which ``consequence``
    goes to). ``jsonschema`` is imported **lazily and optionally**: when it is unavailable (a hook
    under a bare ``python3``) a committed JSON object is loaded *unvalidated* rather than dropped —
    :func:`resolve` then coerces every value defensively."""
    try:
        if not path.is_file():
            return {}, ""
        if path.stat().st_size > _CONFIG_MAX_BYTES:
            reason = f"ignoring {path}: it is larger than {_CONFIG_MAX_BYTES} bytes"
            return {}, _dropped(reason, consequence)
        data = json.loads(path.read_text(encoding="utf-8"))
    # ValueError covers bad JSON, bytes that are not UTF-8, and an integer past Python's digit
    # limit; RecursionError is JSON nested too deeply. No such message repeats the file's content.
    except (OSError, ValueError, RecursionError, MemoryError) as exc:
        return {}, _dropped(f"ignoring unreadable {path}: {exc}", consequence)
    try:
        import jsonschema
    except ImportError:
        # No validator available — trust the committed file, but only if it is a JSON object.
        if isinstance(data, dict):
            return cast("dict[str, Any]", data), ""
        return {}, _dropped(f"ignoring invalid {path}: not a JSON object", consequence)
    # A validator walks and prints what it is given, and JSON that decoded can still be too deep or
    # too large for that. The name of the error only: the message may quote the file.
    try:
        errors = sorted(
            jsonschema.Draft7Validator(_schema()).iter_errors(data),
            key=lambda e: ([str(part) for part in e.absolute_path], str(e.validator)),
        )
        if errors:
            reason = f"ignoring invalid {path}: {_schema_problem(errors[0])}"
            return {}, _dropped(reason, consequence)
    except Exception as exc:
        reason = f"ignoring {path}: it could not be validated ({type(exc).__name__})"
        return {}, _dropped(reason, consequence)
    return cast("dict[str, Any]", data), ""


def _settings_from(
    data: dict[str, Any], warnings: tuple[str, ...] = (), *, disabled_by_repo: bool = False
) -> Settings:
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
    reviewer = data["external_reviewer"]
    reviewer_command, command_warnings = _reviewer_command(reviewer)
    isolated, isolated_warnings = _reviewer_isolated(reviewer)
    reviewer_model, model_warnings = _reviewer_value(reviewer, "model")
    reviewer_effort, effort_warnings = _reviewer_value(reviewer, "effort")
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
        external_reviewer_enabled=_coerce_bool(reviewer["enabled"]),
        external_reviewer_command=reviewer_command,
        external_reviewer_isolated=isolated,
        external_reviewer_model=reviewer_model,
        external_reviewer_effort=reviewer_effort,
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
        warnings=(
            *warnings,
            *command_warnings,
            *isolated_warnings,
            *model_warnings,
            *effort_warnings,
        ),
        external_reviewer_disabled_by_repo=disabled_by_repo,
        knowledge_allow_external_vault=_user_allows_external_vault(data),
    )


def _load_user_config(home: Path | str | None) -> tuple[dict[str, Any], str]:
    """The user-level file, as :func:`_load_config` reads it. Having no home to look in is reported,
    because an opt-out there is then unknown."""
    try:
        home_dir = Path.home() if home is None else Path(home)
    except Exception as exc:  # RuntimeError: no $HOME and no passwd entry
        reason = f"cannot find the home directory ({type(exc).__name__})"
        return {}, _dropped(reason, "the user-level config, and any opt-out in it, is not read")
    path = home_dir / CONFIG_PATH
    data, warning = _load_config(path, _USER_FILE_DROPPED)
    if warning and _dropped_file_opts_out(path):  # a typo must not turn an opt-out back on
        data = {"external_reviewer": {"enabled": False}}
    return data, warning


def _repo_alone_opted_out(user_data: dict[str, Any], repo_data: dict[str, Any]) -> bool:
    return _opted_out(repo_data) and not _opted_out(user_data)


def resolve(
    repo: Path | str, *, env: dict[str, str] | None = None, home: Path | str | None = None
) -> Settings:
    """Resolve the plugin :class:`Settings` for ``repo`` — DEFAULTS < user-level file < repo file <
    env, with two ``external_reviewer`` exceptions (ADR 0100): a repo file cannot set ``command``,
    ``isolated``, ``model`` or ``effort``, and cannot turn on a user-level ``enabled: false``. It
    cannot set ``state.in_repo`` or ``knowledge.allow_external_vault`` either (ADR 0102). ``home``
    overrides the user-config base dir
    (defaults to :func:`Path.home`; mostly for tests/embedding)."""
    src = os.environ if env is None else env
    user_data: dict[str, Any] = {}
    repo_data: dict[str, Any] = {}
    warnings: tuple[str, ...] = ()

    try:
        user_data, user_warning = _load_user_config(home)
        repo_path = Path(repo) / CONFIG_PATH
        repo_data, repo_warning = _load_config(repo_path, _REPO_FILE_DROPPED)
        if repo_warning and _dropped_file_opts_out(repo_path):
            repo_data = {"external_reviewer": {"enabled": False}}
        warnings = tuple(w for w in (user_warning, repo_warning) if w)
        # Before the merge, so it cannot carry them.
        warnings = (
            *warnings,
            *_drop_repo_reviewer_settings(repo_data, user_data),
            *_drop_repo_section(repo_data, "state", "in_repo", _user_state_in_repo(user_data)),
            *_drop_repo_section(
                repo_data,
                "knowledge",
                "allow_external_vault",
                _user_allows_external_vault(user_data),
            ),
        )
        data = copy.deepcopy(DEFAULTS)
        _deep_merge(data, user_data)
        _deep_merge(data, repo_data)
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
        return _settings_from(
            data, warnings, disabled_by_repo=_repo_alone_opted_out(user_data, repo_data)
        )
    except Exception as exc:
        # An unvalidated (no-jsonschema) malformed file slipped through; never raise — fall back to
        # pure defaults (a session / guardrail hook must not break on a bad config), and say so.
        reason = f"ignoring malformed config ({type(exc).__name__}: {exc})"
        dropped = _dropped(reason, _MERGED_CONFIG_DROPPED)
        fallback = copy.deepcopy(DEFAULTS)
        # Not a way around the exceptions: a malformed file must not undo either level's opt-out or
        # reset what only the operator may choose.
        user_section = _user_reviewer_section(user_data)
        for key in _OPERATOR_REVIEWER_KEYS:
            if key in user_section:
                fallback["external_reviewer"][key] = user_section[key]
        if _opted_out(user_data) or _opted_out(repo_data):
            fallback["external_reviewer"]["enabled"] = False
        fallback["state"]["in_repo"] = _user_state_in_repo(user_data)
        fallback["knowledge"]["allow_external_vault"] = _user_allows_external_vault(user_data)
        return _settings_from(
            fallback,
            (*warnings, dropped),
            disabled_by_repo=_repo_alone_opted_out(user_data, repo_data),
        )
