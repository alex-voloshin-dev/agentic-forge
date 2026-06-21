"""Tests for the taskstore fixture library (run inside the spine E2E copy, not the plugin suite)."""

from __future__ import annotations

import pytest

from taskstore import TaskStore


def test_add_returns_incrementing_ids() -> None:
    store = TaskStore()
    assert store.add("first") == 1
    assert store.add("second") == 2


def test_add_rejects_empty_title() -> None:
    store = TaskStore()
    with pytest.raises(ValueError):
        store.add("   ")


def test_list_open_by_default_and_with_done() -> None:
    store = TaskStore()
    a = store.add("a")
    store.add("b")
    store.complete(a)
    assert [t.title for t in store.list()] == ["b"]
    assert {t.title for t in store.list(include_done=True)} == {"a", "b"}


def test_complete_unknown_raises() -> None:
    store = TaskStore()
    with pytest.raises(KeyError):
        store.complete(999)
