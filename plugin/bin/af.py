#!/usr/bin/env python3
"""What the skills run instead of an inline ``python -c`` (ADR 0104).

An inline call puts the working directory first on ``sys.path``, so a checkout's ``agentic_forge/``,
``re.py`` or ``json.py`` runs as the user, and it needs the library importable, which a plugin-only
install does not give it. Run as a script, ``sys.path[0]`` is this file's directory, and the library
is found beside it. ``-E`` makes the interpreter ignore ``PYTHONPATH``, which would otherwise reach
it before this file's first line, and keeps user site-packages, which may hold PyYAML.

    python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" <command> [flags]
    python3 -E "${CLAUDE_PLUGIN_ROOT}/bin/af.py" --help

One narrow command per operation a skill needs, and no way to call anything else. A result is one
JSON object on stdout. Free text and structured input come from a file or stdin (``-``), so a quoted
heredoc can carry them without the shell reading them.

Exit codes: 0 done; 1 refused, failed, or a check that found problems (a check still prints its JSON
result; otherwise the reason is one line on stderr and nothing on stdout); 2 bad usage; 3 a package
this command needs is missing, so it did nothing.

PyYAML and jsonschema are optional and imported only where they are needed. ``handoff-load`` and
``plan-batches`` need both and exit 3 without them, because the library would otherwise call an
unvalidated artifact valid. ``vault-recall`` works without PyYAML, says so under ``warnings``, and
ranks on names and bodies, because titles and tags are in the frontmatter it cannot then read. All
the rest need neither.

Commands that change something outside this process, such as a push, a merge or a commit, are not
run here. They are returned as ``{"argv": [...], "shell": "..."}`` for the session to run, so the
guardrail hooks see the real command line (a hook reads the Bash command, not what a script does).
"""

from __future__ import annotations

import argparse
import dataclasses
import errno
import importlib.util
import json
import math
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(_PLUGIN_ROOT, "lib"))

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_MISSING_PACKAGE = 3

_MAX_INPUT_BYTES = 8 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024  # parsed by pure-Python YAML: this bounds the time it takes
_MAX_BODY_CHARS = 1024 * 1024
_MAX_TITLE_CHARS = 200
_MAX_TAGS = 32
_MAX_OUTPUT_UNITS = 4 * 1024 * 1024  # one per value, one per character of a string
_MAX_OUTPUT_DEPTH = 64
_MAX_MESSAGE_CHARS = 2000
_READ_TIMEOUT_SECONDS = 60
_FILE_OR_STDIN = "a file, or - for stdin"

_NOTE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,63}")
_REPO_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._][A-Za-z0-9._-]{0,99}")
_NAME_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_GIT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}")
_THREAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_=+/-]{0,199}")
_PHASE = re.compile(r"[a-z][a-z-]{0,31}")
# A title reaches a printed command line, and gh has no file form for it, so nothing in it can mean
# anything to a shell or be mangled by whoever copies the line.
_PR_TITLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/()#+-]{0,199}")

_BARE_REPOSITORY_KEY = "safe.bareRepository"
_BARE_REPOSITORY_VALUE = "explicit"


class _MissingPackage(Exception):
    """A package this command needs is not installed: exit 3."""


class _Usage(Exception):
    """Flags that cannot go together: exit 2, as argparse's own errors do."""


def _need(command: str, *modules: str) -> None:
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if missing:
        raise _MissingPackage(
            f"{command} needs {', '.join(missing)}, which this python3 does not have, so nothing "
            "was checked. Stop: do not treat the artifact as valid, keep its status in-review, "
            "commit nothing, and report the package. In a review loop pass --gate-green unknown. "
            "To enable it: python3 -m pip install pyyaml jsonschema"
        )


def _one_line(text: object) -> str:
    """What goes to stderr: a message can repeat a file's text, and a repo chooses that."""
    head = str(text)[: _MAX_MESSAGE_CHARS * 2]
    return " ".join("".join(c if c.isprintable() else " " for c in head).split())[
        :_MAX_MESSAGE_CHARS
    ]


def _plain(value: Any, budget: list[int], depth: int = 0) -> Any:
    """``value`` as JSON can carry it, within a budget. YAML gives dates and non-finite floats."""
    budget[0] -= 1 + (len(value) if isinstance(value, str) else 0)
    if budget[0] < 0 or depth > _MAX_OUTPUT_DEPTH:
        raise ValueError("the result is too large or too deeply nested to report")
    if isinstance(value, dict):
        return {_plain(str(k), budget, depth + 1): _plain(v, budget, depth + 1)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, budget, depth + 1) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)


def _emit(result: dict[str, Any]) -> None:
    print(json.dumps(_plain(result, [_MAX_OUTPUT_UNITS])))


def _read_path(path: str, limit: int = _MAX_INPUT_BYTES) -> str:
    """The text of a regular file, capped, and strict about UTF-8. Not through a link at the last
    component, and never a device or a pipe, which a repo could put at a name it controls."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"{path} is a symlink; pass the real path") from None
        raise
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"{path} is not a regular file")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{path} is larger than {limit} bytes")
    return raw.decode("utf-8")


def _read_input(source: str) -> str:
    """A file, or stdin for ``-``."""
    if source != "-":
        return _read_path(source)
    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        raise ValueError(f"the input is larger than {_MAX_INPUT_BYTES} bytes")
    return raw.decode("utf-8")


def _read_json(source: str) -> Any:
    try:
        return json.loads(_read_input(source))
    except RecursionError:
        raise ValueError("the JSON input is too deeply nested") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"the input is not JSON: {exc}") from None


def _list_in(data: Any, key: str, what: str) -> list[Any]:
    """A JSON array, or the array under ``key``: so one command's output can pipe into the next."""
    value = data.get(key) if isinstance(data, dict) else data
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a JSON array, or an object with {key!r} holding one")
    return value


def _matching(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"invalid {what} {value!r}: expected {pattern.pattern}")
    return value


def _directory(path: str) -> str:
    if not os.path.isdir(path):
        raise ValueError(f"no such directory: {path}")
    return path


def _command(argv: list[str]) -> dict[str, Any]:
    """A command for the session to run. A printed git line carries the same setting as this
    process's own git calls, so that running it in a repo-shaped subdirectory cannot read that
    directory's config."""
    if argv[0] == "git":
        argv = ["git", "-c", f"{_BARE_REPOSITORY_KEY}={_BARE_REPOSITORY_VALUE}", *argv[1:]]
    return {"argv": argv, "shell": shlex.join(argv)}


def _refuse_bare_discovery() -> None:
    """Every git this process starts stops treating a directory shaped like a bare repository as
    one. A checkout can commit such a directory, config and all, and its config runs programs. Only
    a repository named outright is exempt, and a linked worktree is not affected: it has a ``.git``
    file. Added to whatever GIT_CONFIG_COUNT already holds."""
    try:
        count = max(int(os.environ.get("GIT_CONFIG_COUNT") or 0), 0)
    except ValueError:
        count = 0
    os.environ[f"GIT_CONFIG_KEY_{count}"] = _BARE_REPOSITORY_KEY
    os.environ[f"GIT_CONFIG_VALUE_{count}"] = _BARE_REPOSITORY_VALUE
    os.environ["GIT_CONFIG_COUNT"] = str(count + 1)


def _read_process(argv: list[str]) -> str:
    """Run a read-only command (``gh`` or ``git``) and return its stdout, or raise saying why."""
    try:
        done = subprocess.run(
            argv, capture_output=True, encoding="utf-8", errors="replace", check=False,
            timeout=_READ_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise ValueError(f"{argv[0]} is not on PATH") from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"{argv[0]} timed out after {_READ_TIMEOUT_SECONDS}s") from None
    if done.returncode != 0:
        raise ValueError(f"{argv[0]} exited {done.returncode}: {done.stderr[-300:]}")
    return done.stdout


# --- vault ----------------------------------------------------------------------------------------


def _vault_validate(args: argparse.Namespace) -> int:
    from agentic_forge import vault

    repo = _directory(args.repo)
    problems = vault.validate_vault(repo)
    _emit({"ok": not problems, "exists": vault.vault_path(repo).is_dir(), "problems": problems})
    return EXIT_OK if not problems else EXIT_FAILED


def _vault_scaffold(args: argparse.Namespace) -> int:
    from agentic_forge import vault

    _emit({"vault": str(vault.scaffold(_directory(args.repo)))})
    return EXIT_OK


def _vault_recall(args: argparse.Namespace) -> int:
    from agentic_forge import vault

    repo = _directory(args.repo)
    if not args.query.strip():
        raise ValueError("--query is empty")
    notes = [  # the file it was read from, in whatever folder of the vault
        {"name": note.name, "score": score, "path": str(note.path)}
        for note, score in vault.recall_notes(repo, args.query)
    ]
    result: dict[str, Any] = {"notes": notes}
    if importlib.util.find_spec("yaml") is None:
        result["warnings"] = [
            "PyYAML is not installed, so note titles and tags were not read: "
            "this ranks on names and bodies only"
        ]
    _emit(result)
    return EXIT_OK


def _note_fields(data: Any) -> dict[str, Any]:
    """The note a caller asked for, checked where it arrives: a name or a MOC reaches a path, and a
    tag reaches the note's frontmatter."""
    if not isinstance(data, dict):
        raise ValueError("the note must be a JSON object")
    unknown = sorted(set(data) - {"name", "title", "body", "tags", "moc"})
    if unknown:
        raise ValueError(f"unknown note field(s): {', '.join(unknown)}")
    name, title, body = data.get("name"), data.get("title"), data.get("body")
    if not isinstance(name, str):
        raise ValueError("the note needs a string 'name'")
    _matching(_NOTE_NAME, name, "note name")
    if not isinstance(title, str) or not title.strip() or len(title) > _MAX_TITLE_CHARS:
        raise ValueError(f"the note needs a 'title' of 1 to {_MAX_TITLE_CHARS} characters")
    if not title.isprintable():
        raise ValueError("the note's title holds a line break or a control character")
    if not isinstance(body, str) or not body.strip() or len(body) > _MAX_BODY_CHARS:
        raise ValueError(f"the note needs a 'body' of 1 to {_MAX_BODY_CHARS} characters")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > _MAX_TAGS or not all(
        isinstance(tag, str) and _TAG.fullmatch(tag) for tag in tags
    ):
        raise ValueError(f"'tags' must be at most {_MAX_TAGS} strings like {_TAG.pattern}")
    fields: dict[str, Any] = {"name": name, "title": title, "body": body, "tags": tuple(tags)}
    if "moc" in data:
        moc = data["moc"]
        if not isinstance(moc, str):
            raise ValueError("'moc' must be a string")
        if moc != "MOC":
            _matching(_NOTE_NAME, moc, "MOC name")
        fields["moc"] = moc
    return fields


def _vault_add_note(args: argparse.Namespace) -> int:
    from agentic_forge import vault

    repo = _directory(args.repo)
    fields = _note_fields(_read_json(args.json))
    replaced = vault.note_path(repo, fields["name"]).exists()
    name, title, body = fields["name"], fields["title"], fields["body"]
    path = vault.add_note(repo, name, title, body, tags=fields["tags"],
                          moc=fields.get("moc", vault.ROOT_MOC))
    _emit({"path": str(path), "replaced": replaced})
    return EXIT_OK


# --- handoff artifacts and the review loop --------------------------------------------------------


def _load(command: str, path: str, artifact_type: str) -> Any:
    from agentic_forge import handoff

    _need(command, "yaml", "jsonschema")
    if artifact_type not in handoff.ARTIFACT_TYPES:
        expected = ", ".join(handoff.ARTIFACT_TYPES)
        raise ValueError(f"unknown artifact type {artifact_type!r}; expected one of: {expected}")
    text = _read_path(path, _MAX_ARTIFACT_BYTES)
    return handoff.parse_artifact(text, expected_type=artifact_type)


def _handoff_load(args: argparse.Namespace) -> int:
    from agentic_forge import handoff

    artifact = _load("handoff-load", args.path, args.type)
    _emit({
        "path": args.path,
        "type": artifact.type,
        "ready": handoff.is_handoff_ready(artifact.header),
        "header": artifact.header,
    })
    return EXIT_OK


def _review_decision(args: argparse.Namespace) -> int:
    from agentic_forge import handoff

    if args.iteration < 1:
        raise ValueError("--iteration starts at 1")
    if args.gate_green == "unknown":
        # The gate could not be run (handoff-load exited 3). `no` would loop for ever on a machine
        # that can never turn it green, so this exits, and it is not a proceed.
        _emit({"decision": "escalate"})
        return EXIT_OK
    decision = handoff.review_loop_decision(
        args.verdict, args.iteration, gate_green=args.gate_green == "yes"
    )
    _emit({"decision": decision})
    return EXIT_OK


def _review_blocks(args: argparse.Namespace) -> int:
    from agentic_forge import handoff

    findings = _list_in(_read_json(args.findings_json), "findings", "--findings-json")
    _emit({"blocks_approve": handoff.blocks_approve(findings)})
    return EXIT_OK


def _plan_batches(args: argparse.Namespace) -> int:
    from agentic_forge import planning

    tasks = _load("plan-batches", args.plan, "plan").header["tasks"]
    _emit({"levels": planning.plan_batches(tasks)})
    return EXIT_OK


# --- stack ----------------------------------------------------------------------------------------


def _stack_detect(args: argparse.Namespace) -> int:
    from agentic_forge import stacks

    profiles = stacks.detect(_directory(args.repo))
    _emit({
        "primary": dataclasses.asdict(profiles[0]),
        "profiles": [dataclasses.asdict(profile) for profile in profiles],
        "pack_paths": [str(p) for p in stacks.pack_paths(_PLUGIN_ROOT, profiles[0])],
        "summary": stacks.format_profile(profiles[0]),
    })
    return EXIT_OK


# --- release --------------------------------------------------------------------------------------


def _release_commits(args: argparse.Namespace) -> int:
    from agentic_forge import release

    _emit({"commits": release.commits_since(_directory(args.repo))})
    return EXIT_OK


def _release_summarize(args: argparse.Namespace) -> int:
    from agentic_forge import release

    messages = _list_in(_read_json(args.messages_json), "commits", "--messages-json")
    if not all(isinstance(message, str) for message in messages):
        raise ValueError("every commit message must be a string")
    scheme = args.scheme
    if scheme == "auto":
        scheme = "calver" if release.looks_calver(args.current) else "semver"
    now = time.gmtime()
    calver = (now.tm_year, now.tm_mon) if scheme == "calver" else None
    summary = release.summarize(args.current, messages, calver=calver)
    _emit({"scheme": scheme, **dataclasses.asdict(summary)})
    return EXIT_OK


# --- deploys and incidents ------------------------------------------------------------------------

_DEPLOY_STATUSES = ("passing", "failing", "running", "queued", "cancelled")


def _for_environment(records: list[Any], environment: str, what: str) -> list[dict[str, Any]]:
    """The records for ``environment``: one with no ``environment`` of its own counts. If there are
    records and none is for it, that is a wrong flag or a wrong file, and reading it as empty would
    report a failing rollout as healthy."""
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"every {what} must be an object")
    mine = [r for r in records if r.get("environment", environment) == environment]
    if records and not mine:
        found = sorted({str(r.get("environment")) for r in records})
        raise ValueError(
            f"every {what} is for another environment than {environment!r}: "
            f"{', '.join(found[:5])}"
        )
    return mine


def _alerts_from(records: list[Any], environment: str) -> Any:
    """In-memory alerts from records. A severity outside the vocabulary is refused: the assessment
    would read it as healthy."""
    from agentic_forge import ops

    alerts = []
    for record in _for_environment(records, environment, "alert"):
        if record.get("severity") not in ops.ALERT_SEVERITIES:
            raise ValueError(
                f"an alert's severity must be one of {ops.ALERT_SEVERITIES}: {record!r}"
            )
        alerts.append(ops.Alert(
            severity=record["severity"], summary=str(record.get("summary", "")),
            source=str(record.get("source", "")),
        ))
    return ops.InMemoryAlerts({environment: alerts})


def _snapshot_sources(data: Any, environment: str) -> tuple[Any, Any]:
    """In-memory sources from a recorded ``{"deploys": [...], "alerts": [...]}``."""
    from agentic_forge import ops

    if not isinstance(data, dict):
        raise ValueError("the snapshot must be a JSON object")
    deploys = []
    records = _list_in(data, "deploys", "the snapshot's deploys")
    mine = _for_environment(records, environment, "deploy")
    # Newest first is what the assessment reads, and a file's order says nothing about time.
    if len(mine) > 1 and not all(record.get("at") for record in mine):
        raise ValueError(
            "a snapshot with more than one deploy needs an 'at' on each, to say which is latest"
        )
    for record in sorted(mine, key=lambda r: str(r.get("at")), reverse=True):
        if record.get("status") not in _DEPLOY_STATUSES:
            raise ValueError(f"a deploy's status must be one of {_DEPLOY_STATUSES}: {record!r}")
        deploys.append(ops.Deploy(
            sha=str(record.get("sha", "")), status=record["status"],
            environment=environment, at=str(record.get("at", "")),
            workflow=str(record.get("workflow", "")),
        ))
    alerts = _alerts_from(_list_in(data, "alerts", "the snapshot's alerts"), environment)
    return ops.InMemoryPipeline({environment: deploys}), alerts


def _live_alerts() -> Any:
    """The live alert source. With none configured, one that says so: not read is not none."""
    from agentic_forge import connectors, ops

    source = connectors.alert_source()
    if isinstance(source, ops.InMemoryAlerts):
        return ops.UnavailableAlerts(_NO_ALERTS)
    return source


_NO_ALERTS = "no alert source: set GRAFANA_URL, or pass --alerts-json"


def _deploy_status(args: argparse.Namespace) -> int:
    from agentic_forge import connectors, ops

    if args.snapshot is not None and args.alerts_json is not None:
        raise _Usage("--snapshot already holds the alerts; give one or the other")
    not_configured = False
    if args.snapshot is not None:
        pipeline, alerts = _snapshot_sources(_read_json(args.snapshot), args.environment)
    else:
        pipeline = connectors.pipeline_source(args.repo or ".")
        if isinstance(pipeline, ops.InMemoryPipeline):  # the library's name for no provider
            pipeline = ops.UnavailablePipeline("gh is not on PATH, so no pipeline was read")
        if args.alerts_json is not None:
            records = _list_in(_read_json(args.alerts_json), "alerts", "--alerts-json")
            alerts = _alerts_from(records, args.environment)
        else:
            alerts = connectors.alert_source()
            not_configured = isinstance(alerts, ops.InMemoryAlerts)
    status = ops.deploy_status(pipeline, alerts, args.environment)
    if not_configured:
        # Many repos have no alert source: the pipeline's reading stands, and the report says what
        # it did not read. A source that is configured and fails is the library's `unknown`.
        read = status.get("unavailable")
        status["unavailable"] = {**(read if isinstance(read, dict) else {}), "alerts": _NO_ALERTS}
    _emit(status)
    return EXIT_OK


def _alerts_active(args: argparse.Namespace) -> int:
    from agentic_forge import ops

    try:
        alerts = _live_alerts().active_alerts(args.environment)
    except ops.SourceUnavailable as exc:
        raise ValueError(f"alerts unavailable, so report them as unknown, not none: {exc}") from exc
    _emit({
        "environment": args.environment,
        "alerts": [dataclasses.asdict(alert) for alert in alerts],
        "triage": ops.triage_alerts(alerts),
    })
    return EXIT_OK


def _incident_classify(args: argparse.Namespace) -> int:
    from agentic_forge import ops

    severity = ops.classify_incident(
        outage=args.outage, data_loss=args.data_loss, degraded=args.degraded,
        workaround=args.workaround,
    )
    _emit({"severity": severity})
    return EXIT_OK


# --- pull requests --------------------------------------------------------------------------------


def _has_write(slug: str, login: str) -> bool:
    """What GitHub says ``login`` may do on ``slug``. Anything but a clear yes is a no: the same
    answer as the scheduled driver's, by the same two library calls."""
    from agentic_forge import pr_watch

    try:
        answer = json.loads(_read_process(pr_watch.permission_argv(slug, login)))
    except (OSError, ValueError):
        return False
    return pr_watch.has_write_permission(answer)


def _git_answers(repo: str, *args: str) -> tuple[int, str]:
    """A git question whose exit code is the answer."""
    try:
        done = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, encoding="utf-8", errors="replace",
            check=False, timeout=_READ_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return done.returncode, done.stdout.strip()


def _head_problem(state: Any, repo: str) -> str | None:
    """Why this checkout's HEAD is not a fix for this PR, or None. `push` sends whatever HEAD is,
    and "Everything up-to-date" must not read as a pushed fix."""
    code, branch = _git_answers(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if code != 0 or branch != state.branch:
        here = branch or "no branch"
        return f"check out the PR's branch {state.branch} first: this checkout is on {here}"
    code, _ = _git_answers(repo, "merge-base", "--is-ancestor", state.head_oid, "HEAD")
    if code != 0:
        return "HEAD does not hold the PR's head commit: fetch and bring the branch up to date"
    if _git_answers(repo, "rev-parse", "HEAD")[1] == state.head_oid:
        return "HEAD is the PR's head, so there is nothing to push: commit the fix first"
    return None


def _push_command(
    state: Any, repo: str, *, live: bool, foreign: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    """How to push to this PR's branch and None, or None and why not. A fork's branch name is a name
    in OUR origin, so a push there would land on our branch of that name (ADR 0045), and the same
    goes for a PR of a repo this checkout is not a clone of."""
    from agentic_forge import pr_watch

    if state.cross_repo:
        return None, "the PR is from a fork"
    if state.state.upper() != "OPEN":
        return None, f"the PR is {state.state}"
    if not _GIT_REF.fullmatch(state.branch) or ".." in state.branch:
        return None, "the PR's branch name is not one this can put on a command line"
    if foreign:
        return None, foreign
    problem = _head_problem(state, repo) if live else None
    if problem:
        return None, problem
    return _command(pr_watch.push_argv(repo, state.branch)), None


def _pr_state(args: argparse.Namespace) -> int:
    from agentic_forge import connectors, pr_watch, settings

    named = args.owner is not None or args.name is not None or args.number is not None
    if args.snapshot is not None and named:
        raise ValueError("give --snapshot, or all of --owner, --name and --number, not both")
    live = args.snapshot is None
    slug = ""
    if live:
        if not (args.owner and args.name and args.number):
            raise ValueError("give --snapshot, or all of --owner, --name and --number")
        owner = _matching(_NAME_PART, args.owner, "owner")
        name = _matching(_NAME_PART, args.name, "repository name")
        slug = f"{owner}/{name}"
        data = json.loads(_read_process(pr_watch.pr_query_argv(owner, name, args.number)))
    else:
        data = _read_json(args.snapshot)
    if not isinstance(data, dict):
        raise ValueError("the pull request's state must be a JSON object")
    state = pr_watch.parse_pr(data)
    if not state.number:
        raise ValueError("the answer holds no pull request")

    config = settings.resolve(_directory(args.repo))
    reviewers = config.pr_watcher_trusted_reviewers
    bot = config.pr_watcher_bot
    # A fix can only go to `origin`, so a PR of another repo gets none, as the scheduler has it.
    foreign = None
    if live:
        origin = connectors.remote_slug(args.repo)
        if origin is None or origin.casefold() != slug.casefold():
            foreign = f"this checkout's origin is {origin or 'not a GitHub repo'}, not {slug}"
    # A recorded snapshot cannot be asked about a person's permission, and says what it says: its
    # `source` tells the reader so, and it can never open the way to a merge.
    trusted_author = (
        pr_watch.author_checker(lambda login: _has_write(slug, login), reviewers) if live else None
    )
    open_threads = pr_watch.actionable_threads(state, bot=bot)
    trusted = {
        t.id: not foreign and (
            trusted_author(t) if trusted_author else pr_watch.thread_trusted(t, reviewers)
        )
        for t in open_threads
    }
    plan = pr_watch.plan_watch(
        state, bot=bot, max_threads=config.pr_watcher_max_threads, trusted_reviewers=reviewers,
        trusted_author=lambda thread: trusted[thread.id],
    )
    gate = pr_watch.merge_readiness(state, bot=bot)
    merges_here = live and config.merges_in(slug)
    reasons = list(gate.reasons)
    merge = None
    if gate.ready and merges_here:
        try:
            merge = _command(pr_watch.merge_argv(
                slug, state.number, config.pr_watcher_merge_method, head_commit=state.head_oid
            ))
        except ValueError as exc:
            reasons.append(str(exc))
    push, no_push = _push_command(state, args.repo, live=live, foreign=foreign)
    plan_report: dict[str, Any] = {"threads": plan.actionable, "untrusted": plan.untrusted}
    if foreign or state.cross_repo:
        plan_report["reason"] = no_push
    _emit({
        "source": "live" if live else "snapshot",
        "number": state.number, "state": state.state, "branch": state.branch, "base": state.base,
        "head_oid": state.head_oid, "cross_repo": state.cross_repo, "mergeable": state.mergeable,
        "conflicting": state.conflicting, "draft": state.draft, "created_at": state.created_at,
        "checks": state.checks, "review_authors": state.review_authors,
        "review_states": state.review_states,
        "actionable_threads": [
            {
                "id": t.id, "author": t.author, "path": t.path, "line": t.line,
                "trusted": trusted[t.id],
                # A stranger's text goes nowhere near the model, and cannot fill the report either.
                **({"body": t.body} if trusted[t.id] else {}),
            }
            for t in open_threads
        ],
        "plan": plan_report,
        "merge_gate": {"ready": gate.ready and not reasons, "reasons": reasons},
        "push": push,
        "no_push": no_push,
        "merge": merge,
        "settings": {
            "bot": bot,
            "max_threads": config.pr_watcher_max_threads,
            "poll_seconds": config.pr_watcher_poll_seconds,
            "merge_method": config.pr_watcher_merge_method,
            "merges_here": merges_here,
        },
    })
    return EXIT_OK


def _pr_merged(args: argparse.Namespace) -> int:
    from agentic_forge import pr_watch

    slug = _matching(_REPO_SLUG, args.repo_slug, "repository")
    payload = json.loads(_read_process(pr_watch.merged_argv(slug, args.number)))
    _emit({"merged": pr_watch.parse_merged(payload)})
    return EXIT_OK


def _pr_reply_argv(args: argparse.Namespace) -> int:
    from agentic_forge import pr_watch

    thread_id = _matching(_THREAD_ID, args.thread_id, "thread id")
    if not _read_path(args.body_file).strip():
        raise ValueError("the reply is empty")
    _emit(_command(pr_watch.reply_file_argv(thread_id, os.path.abspath(args.body_file))))
    return EXIT_OK


def _comment_body(comment: Any) -> str:
    return str(comment.get("body", "")) if isinstance(comment, dict) else str(comment)


def _pr_conflict_notice(args: argparse.Namespace) -> int:
    from agentic_forge import pr_watch

    slug = _matching(_REPO_SLUG, args.repo_slug, "repository")
    comments = _list_in(_read_json(args.comments_json), "comments", "--comments-json")
    present = pr_watch.conflict_notice_present([_comment_body(comment) for comment in comments])
    post = pr_watch.pr_comment_argv(slug, args.number, pr_watch.CONFLICT_NOTICE)
    _emit({"present": present, "post": None if present else _command(post)})
    return EXIT_OK


# --- document delivery ----------------------------------------------------------------------------


def _doc_worktree(args: argparse.Namespace) -> int:
    from agentic_forge import doc_delivery

    repo = _directory(args.repo)
    base = _matching(_GIT_REF, args.base, "base")
    relative = doc_delivery.worktree_dir(args.slug)
    path = os.path.normpath(os.path.join(os.path.abspath(repo), relative))
    _emit({
        "branch": doc_delivery.branch_name(args.slug),
        "worktree": path,
        "exists": os.path.isdir(path),
        "add": _command(doc_delivery.add_worktree_argv(repo, args.slug, base)),
    })
    return EXIT_OK


def _inside(worktree: str, path: str) -> str:
    """``path`` relative to the worktree, refused if it is not inside it."""
    root = os.path.abspath(worktree)
    relative = os.path.relpath(os.path.join(root, path), root)
    if relative == os.curdir or relative.split(os.sep)[0] == os.pardir:
        raise ValueError(f"--artifact {path} is not a file inside the worktree")
    return relative


def _doc_proceed(args: argparse.Namespace) -> int:
    from agentic_forge import doc_delivery

    worktree = _directory(args.worktree)
    phase = _matching(_PHASE, args.phase, "phase")
    artifacts = [_inside(worktree, path) for path in args.artifact]
    remotes = _read_process(doc_delivery.remote_argv(worktree))
    plan = doc_delivery.proceed_plan(
        worktree, phase, args.slug, remotes=remotes, gh=doc_delivery.gh_on_path()
    )
    steps = [doc_delivery.stage_argv(worktree, artifacts), *plan.argv]
    _emit({
        "steps": [_command(argv) for argv in steps],
        "open_pr": plan.open_pr,
        "note": plan.note,
    })
    return EXIT_OK


def _doc_pr_argv(args: argparse.Namespace) -> int:
    from agentic_forge import doc_delivery

    slug = _matching(_REPO_SLUG, args.repo_slug, "repository")
    title = _matching(_PR_TITLE, args.title, "--title")
    _read_path(args.body_file)  # it has to be there: the printed command reads it later
    create = doc_delivery.pr_create_argv(
        slug, args.slug, title, os.path.abspath(args.body_file), draft=False
    )
    _emit({
        "view": _command(doc_delivery.pr_view_argv(slug, args.slug)),
        "create": _command(create),
    })
    return EXIT_OK


# --- the command line -----------------------------------------------------------------------------


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a positive number")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="af.py", allow_abbrev=False,
        description="The plugin's deterministic operations, for skills to run (ADR 0104).",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def add(
        name: str, handler: Callable[[argparse.Namespace], int], summary: str
    ) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=summary, description=summary, allow_abbrev=False)
        sub.set_defaults(handler=handler)
        return sub

    def with_repo(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sub.add_argument("--repo", default=".", help="the repository directory (default: .)")
        return sub

    with_repo(add("vault-validate", _vault_validate, "Check the vault: links, orphans, root MOC."))
    with_repo(add("vault-scaffold", _vault_scaffold, "Create an empty vault if there is none."))

    sub = with_repo(add("vault-recall", _vault_recall, "Rank the notes matching a query."))
    sub.add_argument("--query", required=True)

    sub = with_repo(add("vault-add-note", _vault_add_note, "Write a note and link it from a MOC."))
    sub.add_argument(
        "--json", required=True, metavar="FILE",
        help='a file, or - for stdin, holding {"name", "title", "body", "tags", "moc"}',
    )

    sub = add("handoff-load", _handoff_load, "Read an artifact back and validate it.")
    sub.add_argument("--path", required=True)
    sub.add_argument("--type", required=True, help="the artifact type expected")

    sub = add("review-decision", _review_decision, "The review loop's next step.")
    sub.add_argument("--verdict", required=True)
    sub.add_argument("--iteration", type=int, required=True, help="1-based")
    sub.add_argument(
        "--gate-green", required=True, choices=("yes", "no", "unknown"),
        help="unknown: the gate could not be run (handoff-load exited 3), which escalates",
    )

    sub = add("review-blocks", _review_blocks, "Whether findings forbid an approve.")
    sub.add_argument("--findings-json", required=True, metavar="FILE", help=_FILE_OR_STDIN)

    sub = add("plan-batches", _plan_batches, "Dependency levels of a plan's tasks.")
    sub.add_argument("--plan", required=True, help="a plan.md handoff artifact")

    with_repo(add("stack-detect", _stack_detect, "Detect the stack and its knowledge packs."))
    with_repo(add("release-commits", _release_commits, "Commit messages since the latest tag."))

    sub = add("release-summarize", _release_summarize, "Next version and grouped changelog.")
    sub.add_argument("--current", required=True, help="the current version")
    sub.add_argument(
        "--messages-json", required=True, metavar="FILE",
        help="a file, or - for stdin: the output of release-commits, or a JSON array of strings",
    )
    sub.add_argument("--scheme", choices=("auto", "semver", "calver"), default="auto")

    sub = add("deploy-status", _deploy_status, "Assess rollout health for an environment.")
    sub.add_argument("--environment", required=True)
    source = sub.add_mutually_exclusive_group()
    source.add_argument("--repo", help="a checkout or owner/name (default: .)")
    source.add_argument(
        "--snapshot", metavar="FILE",
        help=f'a recorded {{"deploys", "alerts"}} instead of live sources: {_FILE_OR_STDIN}',
    )
    sub.add_argument(
        "--alerts-json", metavar="FILE",
        help=f"alerts from elsewhere, with the live pipeline: {_FILE_OR_STDIN}",
    )

    sub = add("alerts-active", _alerts_active, "Active alerts and their counts.")
    sub.add_argument("--environment", required=True)

    sub = add("incident-classify", _incident_classify, "Severity from an incident's facts.")
    for flag in ("--outage", "--data-loss", "--degraded", "--workaround"):
        sub.add_argument(flag, action="store_true")

    sub = with_repo(add(
        "pr-state", _pr_state, "A pull request's threads, plan, merge gate, push and merge."
    ))
    sub.add_argument("--owner")
    sub.add_argument("--name")
    sub.add_argument("--number", type=_positive_int)
    sub.add_argument("--snapshot", metavar="FILE", help=f"recorded PR JSON: {_FILE_OR_STDIN}")

    sub = add("pr-merged", _pr_merged, "Whether a pull request is merged, read from GitHub.")
    sub.add_argument("--repo-slug", required=True)
    sub.add_argument("--number", type=_positive_int, required=True)

    sub = add("pr-reply-argv", _pr_reply_argv, "The command that replies to a review thread.")
    sub.add_argument("--thread-id", required=True)
    sub.add_argument("--body-file", required=True, metavar="FILE", help="a file holding the reply")

    sub = add("pr-conflict-notice", _pr_conflict_notice, "Whether the conflict notice was posted.")
    sub.add_argument("--repo-slug", required=True)
    sub.add_argument("--number", type=_positive_int, required=True)
    sub.add_argument("--comments-json", required=True, metavar="FILE", help=_FILE_OR_STDIN)

    sub = with_repo(add("doc-worktree", _doc_worktree, "A feature's shared document worktree."))
    sub.add_argument("--slug", required=True)
    sub.add_argument("--base", default="HEAD")

    sub = add("doc-proceed", _doc_proceed, "The commands that deliver a phase's artifact.")
    sub.add_argument("--worktree", required=True)
    sub.add_argument("--phase", required=True)
    sub.add_argument("--slug", required=True)
    sub.add_argument(
        "--artifact", required=True, action="append", metavar="PATH",
        help="a file to stage, inside the worktree; repeat for more",
    )

    sub = add("doc-pr-argv", _doc_pr_argv, "The commands that find and open a feature's PR.")
    sub.add_argument("--repo-slug", required=True)
    sub.add_argument("--slug", required=True)
    sub.add_argument("--title", required=True)
    sub.add_argument("--body-file", required=True, metavar="FILE", help="a file holding the body")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _refuse_bare_discovery()
    try:
        code: int = args.handler(args)
    except _MissingPackage as exc:
        print(f"af.py: {_one_line(exc)}", file=sys.stderr)
        return EXIT_MISSING_PACKAGE
    except _Usage as exc:
        print(f"af.py: {args.command}: {_one_line(exc)}", file=sys.stderr)
        return EXIT_USAGE
    # Every refusal the library has is one of these: a vault's StateWriteRefused is an OSError, a
    # HandoffError a ValueError. Anything else is a bug here, and gets its traceback.
    except (OSError, ValueError) as exc:
        print(f"af.py: {args.command}: {_one_line(exc)}", file=sys.stderr)
        return EXIT_FAILED
    return code


if __name__ == "__main__":
    raise SystemExit(main())
