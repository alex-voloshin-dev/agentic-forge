"""Diagnostics bundle packager (ADR 0052).

Collect a target repo's plugin diagnostics into ONE consistent, redacted, shareable zip so a
maintainer can debug the plugin from real usage. Where :mod:`observability` / :mod:`diagnostics`
each *read one log*, this assembles the whole picture: both logs, a rendered ``log-summary.txt``,
an ``environment.txt`` snapshot, and the plugin/config metadata slices — always in the same layout.

Split like the rest of L4: :func:`plan_bundle` is **pure** (given the already-read text blobs it
builds the redacted ``{arcname: text}`` manifest, the generated README, and the summary) and is
what the tests hit; :func:`build_bundle` is the thin I/O seam (read files, snapshot the env, write
the zip). Redaction is defence-in-depth — the logs are already hook-redacted (ADR 0019/0039), and
every config/settings blob is passed through :func:`guardrails.redact_secrets` again; the settings
slice keeps only enablement + hooks, never tokens.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import diagnostics, guardrails, observability, settings

__all__ = [
    "BUNDLE_PREFIX",
    "DEFAULT_WINDOW_DAYS",
    "AuditQuality",
    "audit_quality",
    "settings_slice",
    "filter_by_window",
    "window_text",
    "default_output_path",
    "log_summary",
    "readme",
    "plan_bundle",
    "environment_text",
    "build_bundle",
]

BUNDLE_PREFIX = "agentic-forge-diagnostics"
DEFAULT_WINDOW_DAYS = 7
# ~/.claude files whose agentic-forge slice is safe to ship (enablement + hooks; NEVER tokens).
_SETTINGS_KEEP = ("enabledPlugins", "extraKnownMarketplaces", "hooks")
# The plugin root this lib ships inside (<plugin>/lib/agentic_forge/ -> <plugin>) — the ONLY
# reliable manifest location; `~/.claude/plugins/plugin.json` never existed (real bundles shipped
# without any version info before this was fixed).
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def _parse_ts(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing ``Z``) to an aware UTC datetime, or None
    if absent/unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _timestamp(now: str) -> str:
    """The consistent ``YYYYMMDD-HHMMSS`` stamp used in every bundle name (UTC, from ``now``)."""
    return now.replace(":", "").replace("-", "").replace("T", "-")[:15]


@dataclass(frozen=True)
class AuditQuality:
    """How much of the audit trail predates the current record format: ``undated`` records lack a
    ``ts`` (pre-ADR-0053 — kept regardless of the window since they cannot be dated) and
    ``legacy_input`` records hold a truncated non-JSON ``input`` (pre-ADR-0052)."""

    total: int
    undated: int
    legacy_input: int


def audit_quality(audit_lines: list[str]) -> AuditQuality:
    """Measure the legacy share of ``audit_lines`` (pure) so the bundle can DISCLOSE it instead of
    claiming uniform fidelity — a real 7-day bundle carried 1478 undated / 799 non-JSON records
    from a pre-0.1.0 plugin alongside the current-format ones."""
    undated = legacy_input = total = 0
    for line in audit_lines:
        if not line.strip():
            continue
        total += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            undated += 1
            legacy_input += 1
            continue
        if not isinstance(record, dict):
            continue
        if "ts" not in record:
            undated += 1
        try:
            json.loads(record.get("input") or "")
        except (json.JSONDecodeError, TypeError):
            legacy_input += 1
    return AuditQuality(total=total, undated=undated, legacy_input=legacy_input)


def filter_by_window(lines: list[str], *, days: int | None, now: str) -> list[str]:
    """Keep JSONL ``lines`` whose ``ts`` is within the last ``days`` of ``now`` (pure). ``days``
    of ``None`` keeps everything. Records that are blank/malformed, or lack a parseable ``ts``
    (audit lines predate them — ADR 0053), are **retained** — a window never silently drops a
    record it cannot date."""
    if days is None:
        return list(lines)
    ref = _parse_ts(now)
    if ref is None:
        return list(lines)
    cutoff = ref - timedelta(days=days)
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            kept.append(line)  # keep unparseable lines verbatim rather than lose them
            continue
        ts = _parse_ts(rec.get("ts")) if isinstance(rec, dict) else None
        if ts is None or ts >= cutoff:
            kept.append(line)
    return kept


def window_text(*, days: int | None, now: str) -> str:
    """A human-readable description of the covered window for the report."""
    if days is None:
        return "full history (no window)"
    ref = _parse_ts(now)
    if ref is None:
        return f"last {days} day(s)"
    start = (ref - timedelta(days=days)).date().isoformat()
    return f"last {days} day(s): {start} .. {ref.date().isoformat()}"


def default_output_path(home: Path | str, *, now: str) -> Path:
    """The strict, consistent bundle destination: ``<home>/Downloads/<prefix>-<ts>.zip`` (ADR
    0053) — same shape every run, so bundles sort and are easy to find."""
    return Path(home) / "Downloads" / f"{BUNDLE_PREFIX}-{_timestamp(now)}.zip"


def settings_slice(settings_json: str) -> str:
    """Keep only the enablement + hooks keys of a ``~/.claude/settings.json`` blob (drop tokens and
    everything else), redact, and pretty-print. Returns ``"{}"`` on unparseable input."""
    try:
        data = json.loads(settings_json)
    except (json.JSONDecodeError, TypeError):
        return "{}"
    if not isinstance(data, dict):
        return "{}"
    kept = {k: data[k] for k in _SETTINGS_KEEP if k in data}
    return guardrails.redact_secrets(json.dumps(kept, indent=2, sort_keys=True))


def _legacy_note(quality: AuditQuality) -> str:
    """A one-line disclosure of the legacy share, or "" when the trail is uniformly current."""
    if not (quality.undated or quality.legacy_input):
        return ""
    return (
        f"Legacy records: {quality.undated} lack a timestamp (kept regardless of the window — "
        f"they cannot be dated); {quality.legacy_input} hold a truncated non-JSON `input` "
        "(written by a pre-0.1.0 plugin)."
    )


def log_summary(audit_lines: list[str], diag_lines: list[str], *, window: str = "") -> str:
    """A quick-triage ``log-summary.txt``: the audit usage digest + the diagnostics top-problems
    digest, both rendered from their pure summarisers, prefixed with the covered window and the
    legacy-share disclosure (when any)."""
    header = f"# Log summary\n\nWindow: {window}\n\n" if window else "# Log summary\n\n"
    note = _legacy_note(audit_quality(audit_lines))
    if note:
        header += f"{note}\n\n"
    return (
        f"{header}"
        "## Audit (tool usage)\n"
        f"{observability.render(observability.digest(audit_lines))}\n\n"
        "## Diagnostics (errors / denials / anomalies)\n"
        f"{diagnostics.render(diagnostics.digest(diag_lines))}\n"
    )


def readme(
    *,
    repo_name: str,
    collected_at: str,
    audit_lines: list[str],
    diag_lines: list[str],
    window: str = "",
) -> str:
    """The generated ``README.md`` — what the bundle is, its contents, and the top diagnostic signal
    (so a maintainer sees the headline before opening anything)."""
    diag = diagnostics.digest(diag_lines)
    audit = observability.digest(audit_lines)
    quality = audit_quality(audit_lines)
    top = diag.problems[0] if diag.problems else None
    signal = (
        f"[{top.severity}] {top.component} ({top.kind}) x{top.count} — {top.sample[:100]}"
        if top
        else "no diagnostic events recorded."
    )
    window_line = f"Window: {window}\n" if window else ""
    legacy_line = _legacy_note(quality)
    legacy_note = f"- {legacy_line}\n" if legacy_line else ""
    input_claim = (
        "each `input` is valid JSON"
        if not quality.legacy_input
        else f"`input` is valid JSON except {quality.legacy_input} legacy record(s) — see Notes"
    )
    return (
        "# agentic-forge diagnostics bundle\n\n"
        f"Collected: {collected_at} from repo `{repo_name}`.\n"
        f"{window_line}"
        f"Audit: {audit.total} tool call(s) across {audit.sessions} session(s). "
        f"Diagnostics: {diag.total} event(s).\n\n"
        "## Contents\n"
        f"- `repo-logs/audit.jsonl` — redacted tool-call audit trail ({input_claim}).\n"
        "- `repo-logs/diagnostics.jsonl` — plugin-emitted errors / denials / anomalies.\n"
        "- `log-summary.txt` — quick triage: audit usage digest + diagnostics top problems.\n"
        "- `environment.txt` — OS / node / python / claude-code / plugin versions.\n"
        "- `user-config/config.json` — `~/.agentic-forge/config.json` (redacted).\n"
        "- `plugin-meta/` — plugin manifest, install record, and the `~/.claude/settings` "
        "agentic-forge slice (enablement + hooks only; no tokens).\n\n"
        "## Top signal\n"
        f"{signal}\n\n"
        "## Notes\n"
        "- No secrets: logs are hook-redacted at write time; config/settings slices are "
        "re-redacted and the settings slice keeps only enablement + hooks.\n"
        f"{legacy_note}"
    )


def plan_bundle(
    *,
    repo_name: str,
    collected_at: str,
    audit_lines: list[str],
    diag_lines: list[str],
    environment: str,
    user_config: str | None,
    plugin_json: str | None,
    installed_plugins: str | None,
    claude_settings: str | None,
    window: str = "",
) -> dict[str, str]:
    """Build the bundle manifest ``{arcname: text}`` (pure). Every blob is redacted; absent optional
    inputs are simply omitted. The caller writes each entry under a ``<prefix>-<ts>/`` root."""
    manifest: dict[str, str] = {
        "README.md": readme(
            repo_name=repo_name,
            collected_at=collected_at,
            audit_lines=audit_lines,
            diag_lines=diag_lines,
            window=window,
        ),
        "log-summary.txt": log_summary(audit_lines, diag_lines, window=window),
        "environment.txt": guardrails.redact_secrets(environment),
        "repo-logs/audit.jsonl": "\n".join(audit_lines) + ("\n" if audit_lines else ""),
        "repo-logs/diagnostics.jsonl": "\n".join(diag_lines) + ("\n" if diag_lines else ""),
    }
    if user_config is not None:
        manifest["user-config/config.json"] = guardrails.redact_secrets(user_config)
    if plugin_json is not None:
        manifest["plugin-meta/plugin.json"] = guardrails.redact_secrets(plugin_json)
    if installed_plugins is not None:
        manifest["plugin-meta/installed_plugins.json"] = guardrails.redact_secrets(
            installed_plugins
        )
    if claude_settings is not None:
        manifest["plugin-meta/settings-agentic-forge.json"] = settings_slice(claude_settings)
    return manifest


def _read(path: Path) -> str | None:
    """Read a small text file, or None if absent/unreadable (best-effort metadata)."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _manifest_version(manifest_json: str | None) -> str:
    """``name version`` from a plugin manifest blob, or ``unknown`` — the single most valuable
    triage fact, so it must be in ``environment.txt`` even when the metadata files are absent."""
    if not manifest_json:
        return "unknown"
    try:
        data = json.loads(manifest_json)
    except json.JSONDecodeError:
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    return f"{data.get('name', 'agentic-forge')} {data.get('version', '?')}"


def environment_text(*, collected_at: str, repo: Path, plugin: str = "unknown") -> str:
    """Snapshot OS / interpreter / claude-code / plugin versions (thin subprocess seam)."""

    def ver(*cmd: str) -> str:
        exe = shutil.which(cmd[0])
        if not exe:
            return "not found"
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
            text = (out.stdout or out.stderr).strip()
            return text.splitlines()[0] if text else "?"
        except (OSError, subprocess.SubprocessError):
            return "error"

    return "\n".join(
        [
            "# Environment snapshot",
            f"collected_at: {collected_at}",
            f"host_os: {platform.platform()}",
            f"python: {platform.python_version()} ({sys.executable})",
            f"node: {ver('node', '--version')}",
            f"claude_code: {ver('claude', '--version')}",
            f"plugin: {plugin}",
            f"repo: {repo}",
            "",
        ]
    )


def build_bundle(
    repo: Path | str,
    out_path: Path | str | None = None,
    *,
    home: Path | str | None = None,
    days: int | None = DEFAULT_WINDOW_DAYS,
    now: str | None = None,
) -> Path:
    """Package ``repo``'s diagnostics into a zip and return its path. Reads the two logs from
    ``<repo>/.agentic-forge/``, keeps only records within the last ``days`` (default 7; ``None`` =
    all), reads the user config + ``~/.claude`` metadata from ``home`` (default ``Path.home()``),
    snapshots the environment, then writes the redacted manifest under a ``<prefix>-<ts>/`` root.
    ``out_path`` defaults to the strict ``<home>/Downloads/<prefix>-<ts>.zip`` (ADR 0053).
    Best-effort: missing metadata is omitted, never fatal."""
    repo = Path(repo)
    home = Path(home) if home is not None else Path.home()
    collected_at = now or datetime.now(timezone.utc).isoformat()
    root = f"{BUNDLE_PREFIX}-{_timestamp(collected_at)}"
    out = Path(out_path) if out_path is not None else default_output_path(home, now=collected_at)

    audit_lines = filter_by_window(observability.load_audit(repo), days=days, now=collected_at)
    diag_lines = filter_by_window(diagnostics.load(repo), days=days, now=collected_at)
    # The manifest ships INSIDE the plugin this lib runs from — the one authoritative location.
    # (`~/.claude/plugins/plugin.json` never existed; real bundles shipped without a version.)
    plugin_json = _read(_PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
    # Claude Code's install record: `installed_plugins.json` on current versions; the old
    # `config.json` kept as a fallback for older installations.
    installed_plugins = _read(home / ".claude" / "plugins" / "installed_plugins.json") or _read(
        home / ".claude" / "plugins" / "config.json"
    )
    manifest = plan_bundle(
        repo_name=repo.name or str(repo),
        collected_at=collected_at,
        audit_lines=audit_lines,
        diag_lines=diag_lines,
        environment=environment_text(
            collected_at=collected_at, repo=repo, plugin=_manifest_version(plugin_json)
        ),
        user_config=_read(home / settings.CONFIG_PATH),
        plugin_json=plugin_json,
        installed_plugins=installed_plugins,
        claude_settings=_read(home / ".claude" / "settings.json"),
        window=window_text(days=days, now=collected_at),
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, text in manifest.items():
            zf.writestr(f"{root}/{arcname}", text)
    return out
