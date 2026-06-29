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


# --- runtime routing (ADR 0046) ---------------------------------------------


def test_validated_tiers_ship_all_default() -> None:
    # no downgrade out of the box; every committed role resolves to inherit
    assert set(models.VALIDATED_TIERS.values()) == {"default"}
    assert all(models.frontmatter_model(r) == "inherit" for r in models.VALIDATED_TIERS)


def test_frontmatter_model_default_is_inherit() -> None:
    assert models.frontmatter_model("grader") == "inherit"  # policy default -> inherit
    assert models.frontmatter_model("unknown-role") == "inherit"  # unknown -> default -> inherit


def test_frontmatter_model_promoted_tier_pins_the_model_id() -> None:
    promoted = {"grader": "cheap", "reviewer": "default"}
    assert models.frontmatter_model("grader", promoted) == models.TIERS["cheap"]  # pinned id
    assert models.frontmatter_model("reviewer", promoted) == "inherit"  # default stays inherit
    assert models.frontmatter_model("se", {"se": "claude-x"}) == "claude-x"  # literal id kept


def test_set_frontmatter_model_replaces_only_the_frontmatter_line() -> None:
    text = "---\nname: grader\nmodel: inherit\n---\nBody mentions model: foo in prose.\n"
    out = models.set_frontmatter_model(text, "claude-haiku-4-5-20251001")
    assert "model: claude-haiku-4-5-20251001\n" in out
    assert "model: inherit" not in out
    assert "Body mentions model: foo in prose." in out  # body untouched (count=1)


def test_set_frontmatter_model_raises_without_a_model_line() -> None:
    import pytest

    with pytest.raises(ValueError, match="no 'model:'"):
        models.set_frontmatter_model("---\nname: x\n---\nbody\n", "inherit")


def test_set_frontmatter_model_ignores_a_body_model_line() -> None:
    import pytest

    # frontmatter has NO model: line, but the body documents one -> must raise (not silently rewrite
    # the body and "succeed"); regression for the ADR 0046 review's MAJOR finding.
    text = "---\nname: x\n---\nExample frontmatter:\nmodel: cheap\n"
    with pytest.raises(ValueError, match="no 'model:'"):
        models.set_frontmatter_model(text, "inherit")


def test_set_frontmatter_model_raises_without_frontmatter() -> None:
    import pytest

    with pytest.raises(ValueError, match="no frontmatter block"):
        models.set_frontmatter_model("plain text, no frontmatter\n", "inherit")
