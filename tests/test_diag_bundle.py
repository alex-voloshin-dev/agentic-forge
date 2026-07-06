"""Tests for the diagnostics bundle packager (ADR 0052)."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

from agentic_forge import diag_bundle

_REPO = Path(__file__).resolve().parents[1]
_SKILL_SCRIPT = _REPO / "plugin" / "skills" / "diagnostics-bundle" / "scripts" / "build_bundle.py"

_AUDIT = [
    json.dumps({"tool": "Bash", "input": '{"command": "ls"}', "session_id": "s1"}),
    json.dumps({"tool": "Read", "input": '{"file_path": "a.py"}', "session_id": "s1"}),
]
_DIAG = [
    json.dumps(
        {
            "ts": "2026-07-05T00:00:00+00:00",
            "kind": "block",
            "severity": "major",
            "component": "security-hook",
            "signature": "security-hook:block:x",
            "message": "blocked: pipe a network download into a shell",
        }
    )
]


_NOW = "2026-07-10T00:00:00+00:00"


# --- filter_by_window --------------------------------------------------------


def _dated(ts: str) -> str:
    return json.dumps({"ts": ts, "tool": "Bash", "input": "{}"})


def test_filter_by_window_keeps_recent_drops_old() -> None:
    lines = [
        _dated("2026-07-09T00:00:00+00:00"),  # 1 day ago -> keep
        _dated("2026-07-04T00:00:00+00:00"),  # 6 days ago -> keep
        _dated("2026-07-01T00:00:00+00:00"),  # 9 days ago -> drop
    ]
    kept = diag_bundle.filter_by_window(lines, days=7, now=_NOW)
    assert len(kept) == 2
    assert "2026-07-01" not in "".join(kept)


def test_filter_by_window_retains_undated_and_malformed() -> None:
    lines = [
        json.dumps({"tool": "Bash", "input": "{}"}),  # legacy, no ts -> keep
        "not json at all",  # malformed -> keep verbatim
        _dated("2026-07-01T00:00:00+00:00"),  # old -> drop
    ]
    kept = diag_bundle.filter_by_window(lines, days=7, now=_NOW)
    assert len(kept) == 2


def test_filter_by_window_none_keeps_all() -> None:
    lines = [_dated("2020-01-01T00:00:00+00:00")]
    assert diag_bundle.filter_by_window(lines, days=None, now=_NOW) == lines


def test_filter_by_window_tolerates_z_suffix() -> None:
    kept = diag_bundle.filter_by_window([_dated("2026-07-09T00:00:00Z")], days=7, now=_NOW)
    assert len(kept) == 1


# --- window_text / default_output_path ---------------------------------------


def test_window_text_describes_range_and_full_history() -> None:
    assert "2026-07-03 .. 2026-07-10" in diag_bundle.window_text(days=7, now=_NOW)
    assert diag_bundle.window_text(days=None, now=_NOW) == "full history (no window)"


def test_default_output_path_is_downloads_with_consistent_name() -> None:
    out = diag_bundle.default_output_path("/home/u", now="2026-07-10T13:45:07+00:00")
    assert out == Path("/home/u/Downloads/agentic-forge-diagnostics-20260710-134507.zip")


# --- settings_slice ----------------------------------------------------------


def test_settings_slice_keeps_only_enablement_and_hooks_and_drops_tokens() -> None:
    raw = json.dumps(
        {
            "enabledPlugins": {"agentic-forge@agentic-forge": True},
            "hooks": {"PreToolUse": []},
            "apiKey": "sk-ant-shouldnotsurvive0123456789",
            "unrelated": {"nested": 1},
        }
    )
    out = diag_bundle.settings_slice(raw)
    parsed = json.loads(out)
    assert set(parsed) == {"enabledPlugins", "hooks"}
    assert "apiKey" not in parsed and "unrelated" not in parsed
    assert "sk-ant-" not in out


def test_settings_slice_survives_garbage() -> None:
    assert diag_bundle.settings_slice("not json") == "{}"
    assert diag_bundle.settings_slice("[1,2,3]") == "{}"


# --- log_summary / readme ----------------------------------------------------


def test_log_summary_has_both_digests() -> None:
    out = diag_bundle.log_summary(_AUDIT, _DIAG)
    assert "Audit (tool usage)" in out and "Diagnostics" in out
    assert "Bash" in out  # from the audit digest
    assert "security-hook" in out  # from the diagnostics digest


def test_readme_surfaces_top_signal_and_repo() -> None:
    out = diag_bundle.readme(
        repo_name="f4ai", collected_at="2026-07-06T00:00:00Z", audit_lines=_AUDIT, diag_lines=_DIAG
    )
    assert "f4ai" in out
    assert "security-hook" in out  # the top diagnostic signal
    assert "pipe a network download" in out


def test_readme_handles_no_diagnostics() -> None:
    out = diag_bundle.readme(
        repo_name="x", collected_at="t", audit_lines=_AUDIT, diag_lines=[]
    )
    assert "no diagnostic events recorded" in out


# --- plan_bundle -------------------------------------------------------------


def _plan(**over: object) -> dict[str, str]:
    base: dict[str, object] = dict(
        repo_name="f4ai",
        collected_at="2026-07-06T00:00:00Z",
        audit_lines=_AUDIT,
        diag_lines=_DIAG,
        environment="host_os: test",
        user_config=None,
        plugin_json=None,
        installed_plugins=None,
        claude_settings=None,
    )
    base.update(over)
    return diag_bundle.plan_bundle(**base)  # type: ignore[arg-type]


def test_plan_bundle_core_files_always_present() -> None:
    manifest = _plan()
    for name in (
        "README.md",
        "log-summary.txt",
        "environment.txt",
        "repo-logs/audit.jsonl",
        "repo-logs/diagnostics.jsonl",
    ):
        assert name in manifest
    # optional metadata omitted when not supplied
    assert "user-config/config.json" not in manifest
    assert "plugin-meta/settings-agentic-forge.json" not in manifest


def test_plan_bundle_includes_and_redacts_optional_blobs() -> None:
    manifest = _plan(
        user_config='{"token": "ghp_abcdefghijklmnopqrstuvwxyz0123"}',
        claude_settings='{"enabledPlugins": {"agentic-forge@agentic-forge": true}, '
        '"apiKey": "sk-ant-secret0123456789abcdef"}',
    )
    assert "user-config/config.json" in manifest
    assert "ghp_" not in manifest["user-config/config.json"]
    slice_ = manifest["plugin-meta/settings-agentic-forge.json"]
    assert "sk-ant-" not in slice_ and "apiKey" not in slice_
    assert "enabledPlugins" in slice_


def test_plan_bundle_environment_is_redacted() -> None:
    manifest = _plan(environment="key=sk-ant-secret0123456789abcdef")
    assert "sk-ant-" not in manifest["environment.txt"]


def test_plan_bundle_includes_plugin_metadata() -> None:
    manifest = _plan(
        plugin_json='{"name": "agentic-forge"}',
        installed_plugins='{"version": 2, "token": "ghp_abcdefghijklmnopqrstuvwxyz0123"}',
    )
    assert manifest["plugin-meta/plugin.json"] == '{"name": "agentic-forge"}'
    assert "ghp_" not in manifest["plugin-meta/installed_plugins.json"]


# --- build_bundle (I/O) ------------------------------------------------------


def _seed_repo(repo: Path) -> None:
    log_dir = repo / ".agentic-forge"
    log_dir.mkdir(parents=True)
    (log_dir / "audit.jsonl").write_text("\n".join(_AUDIT) + "\n", encoding="utf-8")
    (log_dir / "diagnostics.jsonl").write_text("\n".join(_DIAG) + "\n", encoding="utf-8")


def test_build_bundle_writes_structured_zip(tmp_path: Path) -> None:
    repo = tmp_path / "f4ai"
    repo.mkdir()
    _seed_repo(repo)
    home = tmp_path / "home"
    (home / ".agentic-forge").mkdir(parents=True)
    (home / ".agentic-forge" / "config.json").write_text(
        '{"diagnostics": {"enabled": true}}', encoding="utf-8"
    )

    out = tmp_path / "bundle.zip"
    written = diag_bundle.build_bundle(repo, out, home=home, now="2026-07-06T10:00:00+00:00")
    assert written == out and out.is_file()

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        root = f"{diag_bundle.BUNDLE_PREFIX}-20260706-100000"
        assert f"{root}/README.md" in names
        assert f"{root}/repo-logs/audit.jsonl" in names
        assert f"{root}/user-config/config.json" in names
        # the copied audit log round-trips as JSONL
        audit = zf.read(f"{root}/repo-logs/audit.jsonl").decode().strip().splitlines()
        assert json.loads(audit[0])["tool"] == "Bash"


def test_build_bundle_defaults_to_downloads_and_windows(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    log_dir = repo / ".agentic-forge"
    log_dir.mkdir()
    recent = json.dumps({"ts": "2026-07-09T00:00:00+00:00", "tool": "Read", "input": "{}"})
    old = json.dumps({"ts": "2026-06-01T00:00:00+00:00", "tool": "Read", "input": "{}"})
    (log_dir / "audit.jsonl").write_text(recent + "\n" + old + "\n", encoding="utf-8")
    (log_dir / "diagnostics.jsonl").write_text("", encoding="utf-8")
    home = tmp_path / "home"

    # out_path omitted -> strict ~/Downloads; default 7-day window drops the June record.
    out = diag_bundle.build_bundle(repo, home=home, now="2026-07-10T09:08:07+00:00")
    assert out == home / "Downloads" / "agentic-forge-diagnostics-20260710-090807.zip"
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        root = "agentic-forge-diagnostics-20260710-090807"
        audit = zf.read(f"{root}/repo-logs/audit.jsonl").decode()
        assert "2026-07-09" in audit and "2026-06-01" not in audit  # windowed
        assert "Window: last 7 day(s)" in zf.read(f"{root}/log-summary.txt").decode()


def test_build_bundle_full_history_with_days_none(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_repo(repo)
    out = tmp_path / "all.zip"
    diag_bundle.build_bundle(repo, out, home=tmp_path / "h", days=None, now=_NOW)
    with zipfile.ZipFile(out) as zf:
        summary = next(zf.read(n).decode() for n in zf.namelist() if n.endswith("log-summary.txt"))
        assert "full history" in summary


def test_build_bundle_best_effort_without_home_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_repo(repo)
    empty_home = tmp_path / "empty"
    empty_home.mkdir()

    out = tmp_path / "b.zip"
    diag_bundle.build_bundle(repo, out, home=empty_home, now="2026-07-06T10:00:00+00:00")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        # core files present; absent user config simply omitted, not fatal
        assert any(n.endswith("/log-summary.txt") for n in names)
        assert not any(n.endswith("/user-config/config.json") for n in names)


# --- shipped skill script ----------------------------------------------------


def _load_skill_script() -> object:
    spec = importlib.util.spec_from_file_location("_diag_bundle_skill", _SKILL_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_script_writes_to_downloads(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "repo"
    _seed_repo(repo)
    home = tmp_path / "home"
    module = _load_skill_script()
    rc = module.main(["build_bundle", "--repo", str(repo), "--home", str(home), "--days", "0"])
    assert rc == 0
    written = list((home / "Downloads").glob("agentic-forge-diagnostics-*.zip"))
    assert len(written) == 1  # strict ~/Downloads destination, consistent name
    assert "Diagnostics bundle written to" in capsys.readouterr().out
