"""Tests for model tiering (ADR 0043)."""

from __future__ import annotations

from agentic_forge import models


def test_model_for_default_when_no_override() -> None:
    assert models.model_for("grader", {}, default="claude-opus-4-8") == "claude-opus-4-8"
    # an override for a *different* component doesn't affect this one
    assert models.model_for("grader", {"router": "simple"}, default="D") == "D"
    assert models.model_for("x", {"x": ""}, default="D") == "D"  # empty value -> default, never ""


def test_model_for_tier_name_resolves_to_tier_model() -> None:
    assert models.model_for("grader", {"grader": "simple"}, default="D") == models.TIERS["simple"]
    assert models.model_for("router", {"router": "cheap"}, default="D") == models.TIERS["cheap"]
    assert models.model_for("se", {"se": "default"}, default="D") == models.TIERS["default"]


def test_model_for_model_id_passthrough() -> None:
    # a value that isn't a known tier name is used verbatim as a model id
    assert models.model_for("x", {"x": "claude-custom-9"}, default="D") == "claude-custom-9"


def test_tiers_are_the_three_named_tiers() -> None:
    assert set(models.TIERS) == {"default", "simple", "cheap"}
    assert models.TIERS["default"] == "claude-opus-4-8"  # the safe default = opus
