"""The marketplace entry carries the plugin's own version (ADR 0108)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_forge.validation import validate_marketplace

_REPO = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, market: object, plugin: object = None) -> tuple[Path, Path]:
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    manifest = plugin if plugin is not None else {"name": "af", "version": "2026.11.9"}
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), "utf-8")
    if market is not None:
        (tmp_path / ".claude-plugin").mkdir()
        text = market if isinstance(market, str) else json.dumps(market)
        (tmp_path / ".claude-plugin" / "marketplace.json").write_text(text, "utf-8")
    return tmp_path, plugin_dir


def test_matching_versions_pass(tmp_path: Path) -> None:
    root, plugin = _repo(tmp_path, {"plugins": [{"name": "af", "version": "2026.11.9"}]})
    assert validate_marketplace(root, plugin).ok


def test_a_stale_marketplace_version_fails(tmp_path: Path) -> None:
    root, plugin = _repo(tmp_path, {"plugins": [{"name": "af", "version": "2026.11.7"}]})
    report = validate_marketplace(root, plugin)
    assert not report.ok
    assert "'2026.11.7'" in report.render() and "'2026.11.9'" in report.render()


@pytest.mark.parametrize(
    "market",
    [
        {"plugins": [{"name": "other", "version": "2026.11.9"}]},
        {"plugins": []},
        {},
        [],
    ],
)
def test_no_entry_for_the_plugin_fails(tmp_path: Path, market: object) -> None:
    root, plugin = _repo(tmp_path, market)
    assert "no plugins[] entry named 'af'" in validate_marketplace(root, plugin).render()


def test_an_entry_without_a_version_fails(tmp_path: Path) -> None:
    root, plugin = _repo(tmp_path, {"plugins": [{"name": "af"}]})
    assert not validate_marketplace(root, plugin).ok


def test_invalid_marketplace_json_is_reported(tmp_path: Path) -> None:
    root, plugin = _repo(tmp_path, "{not json")
    assert "invalid JSON" in validate_marketplace(root, plugin).render()


def test_no_marketplace_file_is_skipped(tmp_path: Path) -> None:
    root, plugin = _repo(tmp_path, None)
    assert validate_marketplace(root, plugin).ok


def test_an_unreadable_manifest_is_left_to_validate_manifest(tmp_path: Path) -> None:
    root = tmp_path
    (root / "plugin").mkdir()
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text("{}", "utf-8")
    assert validate_marketplace(root, root / "plugin").ok


def test_this_repository_lists_its_own_version() -> None:
    assert validate_marketplace(_REPO, _REPO / "plugin").ok, validate_marketplace(
        _REPO, _REPO / "plugin"
    ).render()
