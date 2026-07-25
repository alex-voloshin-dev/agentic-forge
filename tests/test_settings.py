"""Tests for plugin settings resolution (ADR 0041): defaults < config file < env."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agentic_forge import settings


def _write_config(repo: Path, data: dict) -> None:
    d = repo / ".agentic-forge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(data), encoding="utf-8")


def _write_user_config(home: Path, data: dict) -> None:
    """Write the user-level (cross-project) config under ``home/.agentic-forge`` (ADR 0049)."""
    d = home / ".agentic-forge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(data), encoding="utf-8")


def test_defaults_when_no_file_no_env(tmp_path: Path) -> None:
    s = settings.resolve(tmp_path, env={})
    assert s.diagnostics_enabled is False
    assert s.subagent_soft == 25 and s.subagent_hard == 50
    assert s.skip_test_gate is False
    assert s.review_passes == 3
    assert s.external_reviewer_enabled is True and s.external_reviewer_command == "codex"
    assert s.models == {}
    assert s.pr_watcher_enabled is False and s.pr_watcher_max_threads == 10
    assert s.pr_watcher_bot == "github-actions[bot]" and s.pr_watcher_repos == []


def test_file_overrides_defaults(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        {
            "diagnostics": {"enabled": True},
            "review": {"passes": 5},
            "external_reviewer": {"enabled": False, "command": "codex"},
            "models": {"default": "claude-opus-4-8", "simple": "claude-sonnet-4-6"},
        },
    )
    s = settings.resolve(tmp_path, env={})
    assert s.diagnostics_enabled is True and s.review_passes == 5
    assert s.external_reviewer_enabled is False  # file overrides the on-by-default (ADR 0057)
    assert s.models == {"default": "claude-opus-4-8", "simple": "claude-sonnet-4-6"}
    assert s.subagent_soft == 25  # an untouched key keeps its default (deep merge)


def test_env_overrides_file(tmp_path: Path) -> None:
    _write_config(tmp_path, {"diagnostics": {"enabled": False}, "subagent_budget": {"soft": 10}})
    s = settings.resolve(
        tmp_path,
        env={
            "AGENTIC_FORGE_DIAGNOSTICS": "1",
            "AGENTIC_FORGE_SUBAGENT_SOFT": "7",
            "AGENTIC_FORGE_SUBAGENT_HARD": "9",
            "AGENTIC_FORGE_SKIP_TEST_GATE": "1",
        },
    )
    assert s.diagnostics_enabled is True  # env beats the file's False
    assert s.subagent_soft == 7 and s.subagent_hard == 9
    assert s.skip_test_gate is True


@pytest.mark.parametrize(
    ("val", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("", False)],
)
def test_env_bool_coercion(tmp_path: Path, val: str, expected: bool) -> None:
    s = settings.resolve(tmp_path, env={"AGENTIC_FORGE_DIAGNOSTICS": val})
    assert s.diagnostics_enabled is expected


def test_bad_int_env_keeps_default(tmp_path: Path) -> None:
    s = settings.resolve(tmp_path, env={"AGENTIC_FORGE_SUBAGENT_SOFT": "notanint"})
    assert s.subagent_soft == 25  # unparseable -> default kept


def test_bad_json_falls_back_to_defaults(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    d = tmp_path / ".agentic-forge"
    d.mkdir(parents=True)
    (d / "config.json").write_text("{not json", encoding="utf-8")
    s = settings.resolve(tmp_path, env={})
    assert s.review_passes == 3  # defaults
    assert "ignoring unreadable" in capsys.readouterr().err


def test_schema_invalid_falls_back_to_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _write_config(tmp_path, {"review": {"passes": 0}})  # minimum is 1 -> schema-invalid
    s = settings.resolve(tmp_path, env={})
    assert s.review_passes == 3
    assert "ignoring invalid" in capsys.readouterr().err


def test_unknown_key_rejected(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _write_config(tmp_path, {"bogus": True})  # additionalProperties:false -> rejected
    s = settings.resolve(tmp_path, env={})
    assert s.review_passes == 3
    assert "ignoring invalid" in capsys.readouterr().err


def test_non_object_top_level_falls_back(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    d = tmp_path / ".agentic-forge"
    d.mkdir(parents=True)
    (d / "config.json").write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, not an object
    s = settings.resolve(tmp_path, env={})
    assert s.review_passes == 3  # schema's root type:object rejects it -> defaults
    assert "ignoring invalid" in capsys.readouterr().err


# --- user-level config layer (ADR 0049): DEFAULTS < user < repo < env ------------------------


def test_user_level_config_applied(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home, {"diagnostics": {"enabled": True}, "review": {"passes": 4}})
    s = settings.resolve(tmp_path / "repo", env={}, home=home)
    assert s.diagnostics_enabled is True and s.review_passes == 4  # user-level applies repo-wide


def test_repo_overrides_user_level(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    _write_user_config(home, {"review": {"passes": 4}, "diagnostics": {"enabled": True}})
    _write_config(repo, {"review": {"passes": 7}})
    s = settings.resolve(repo, env={}, home=home)
    assert s.review_passes == 7  # the repo file overrides the user-level value
    assert s.diagnostics_enabled is True  # a user-level key the repo didn't set still applies


def test_env_overrides_user_and_repo(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    _write_user_config(home, {"diagnostics": {"enabled": False}})
    _write_config(repo, {"diagnostics": {"enabled": False}})
    s = settings.resolve(repo, env={"AGENTIC_FORGE_DIAGNOSTICS": "1"}, home=home)
    assert s.diagnostics_enabled is True  # env beats both files


def test_example_config_is_schema_valid() -> None:
    # The shipped example must always validate against the schema (a copy-paste starting point).
    import jsonschema

    root = Path(__file__).resolve().parents[1]
    example = json.loads((root / "plugin" / "config.example.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (root / "plugin" / "schemas" / "config.schema.json").read_text(encoding="utf-8")
    )
    assert list(jsonschema.Draft7Validator(schema).iter_errors(example)) == []


# --- jsonschema is optional: a hook under a bare python3 still loads config (ADR 0019/0049) ---


def test_config_loads_without_jsonschema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)  # make `import jsonschema` fail
    _write_config(tmp_path, {"diagnostics": {"enabled": True}})
    s = settings.resolve(tmp_path, env={}, home=tmp_path / "nohome")
    assert s.diagnostics_enabled is True  # a valid committed file is trusted (loaded unvalidated)


def test_malformed_config_without_jsonschema_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    _write_config(tmp_path, {"subagent_budget": {"soft": "oops"}})  # bad type, now unvalidated
    s = settings.resolve(tmp_path, env={}, home=tmp_path / "nohome")  # must not raise
    assert s.subagent_soft == settings.DEFAULTS["subagent_budget"]["soft"]  # coerced to the default
