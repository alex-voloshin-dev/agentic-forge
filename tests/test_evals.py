from __future__ import annotations

from agentic_forge import evals as evals_mod

VALID = {
    "skill_name": "x",
    "evals": [{"id": 1, "prompt": "do x", "assertions": ["it did x"]}],
    "component": {"id": "x", "type": "skill", "purpose": "p"},
    "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
}


def _without(key: str) -> dict:
    data = {k: v for k, v in VALID.items() if k != key}
    return data


def test_valid_evals() -> None:
    assert evals_mod.validate_evals(VALID) == []


def test_missing_skill_name() -> None:
    assert any("skill_name" in e for e in evals_mod.validate_evals(_without("skill_name")))


def test_missing_evals_array() -> None:
    assert any("evals" in e for e in evals_mod.validate_evals(_without("evals")))


def test_empty_evals_array() -> None:
    data = {**VALID, "evals": []}
    assert evals_mod.validate_evals(data) != []


def test_missing_component() -> None:
    assert any("component" in e for e in evals_mod.validate_evals(_without("component")))


def test_missing_thresholds() -> None:
    assert any("thresholds" in e for e in evals_mod.validate_evals(_without("thresholds")))


def test_bad_component_type() -> None:
    data = {**VALID, "component": {"id": "x", "type": "nonsense", "purpose": "p"}}
    assert evals_mod.validate_evals(data) != []


def test_pass_rate_out_of_range() -> None:
    data = {**VALID, "thresholds": {"tier2_quality": {"min_pass_rate": 1.5}}}
    assert evals_mod.validate_evals(data) != []


def test_eval_id_must_be_integer() -> None:
    data = {**VALID, "evals": [{"id": "one", "prompt": "do x"}]}
    assert evals_mod.validate_evals(data) != []


def test_load_evals_bad_json(tmp_path) -> None:
    p = tmp_path / "evals.json"
    p.write_text("{not json", encoding="utf-8")
    try:
        evals_mod.load_evals(p)
    except evals_mod.EvalsError:
        return
    raise AssertionError("expected EvalsError")
