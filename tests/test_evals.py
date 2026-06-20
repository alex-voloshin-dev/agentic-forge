from __future__ import annotations

from agentic_forge import evals as evals_mod


def test_valid_evals() -> None:
    data = {
        "component": {"id": "x", "type": "skill", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
    }
    assert evals_mod.validate_evals(data) == []


def test_missing_component() -> None:
    data = {"thresholds": {"tier2_quality": {"runs": 5}}}
    assert any("component" in e for e in evals_mod.validate_evals(data))


def test_missing_thresholds() -> None:
    data = {"component": {"id": "x", "type": "skill", "purpose": "p"}}
    assert any("thresholds" in e for e in evals_mod.validate_evals(data))


def test_bad_component_type() -> None:
    data = {
        "component": {"id": "x", "type": "nonsense", "purpose": "p"},
        "thresholds": {"tier2_quality": {"runs": 5}},
    }
    assert evals_mod.validate_evals(data) != []


def test_pass_rate_out_of_range() -> None:
    data = {
        "component": {"id": "x", "type": "skill", "purpose": "p"},
        "thresholds": {"tier2_quality": {"min_pass_rate": 1.5, "runs": 5}},
    }
    assert evals_mod.validate_evals(data) != []


def test_load_evals_roundtrip(tmp_path) -> None:
    p = tmp_path / "evals.json"
    p.write_text('{"component": {"id": "x", "type": "skill", "purpose": "p"},'
                 ' "thresholds": {"tier2_quality": {"runs": 5}}}', encoding="utf-8")
    data = evals_mod.load_evals(p)
    assert data["component"]["id"] == "x"


def test_load_evals_bad_json(tmp_path) -> None:
    p = tmp_path / "evals.json"
    p.write_text("{not json", encoding="utf-8")
    try:
        evals_mod.load_evals(p)
    except evals_mod.EvalsError:
        return
    raise AssertionError("expected EvalsError")
