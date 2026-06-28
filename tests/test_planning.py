from __future__ import annotations

import pytest

from agentic_forge.planning import plan_batches


def _t(tid: object, *deps: object) -> dict[str, object]:
    return {"id": tid, "deps": list(deps), "title": f"task {tid}"}


def test_empty() -> None:
    assert plan_batches([]) == []


def test_single_task_no_deps() -> None:
    assert plan_batches([_t("T1")]) == [["T1"]]


def test_independent_tasks_one_level() -> None:
    assert plan_batches([_t("T1"), _t("T2"), _t("T3")]) == [["T1", "T2", "T3"]]


def test_chain_is_one_per_level() -> None:
    assert plan_batches([_t("T1"), _t("T2", "T1"), _t("T3", "T2")]) == [["T1"], ["T2"], ["T3"]]


def test_diamond() -> None:
    tasks = [_t("T1"), _t("T2", "T1"), _t("T3", "T1"), _t("T4", "T2", "T3")]
    assert plan_batches(tasks) == [["T1"], ["T2", "T3"], ["T4"]]


def test_int_ids_coerced() -> None:
    assert plan_batches([_t(1), _t(2, 1)]) == [["1"], ["2"]]


def test_missing_deps_key_treated_as_none() -> None:
    assert plan_batches([{"id": "T1"}, {"id": "T2", "deps": ["T1"]}]) == [["T1"], ["T2"]]


def test_cycle_raises() -> None:
    with pytest.raises(ValueError, match="cycle"):
        plan_batches([_t("T1", "T2"), _t("T2", "T1")])


def test_self_dependency_is_a_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        plan_batches([_t("T1", "T1")])


def test_unknown_dep_raises() -> None:
    with pytest.raises(ValueError, match="unknown task"):
        plan_batches([_t("T1", "T9")])


def test_duplicate_id_raises() -> None:
    with pytest.raises(ValueError, match="duplicate task id"):
        plan_batches([_t("T1"), _t("T1")])


def test_missing_id_raises() -> None:
    with pytest.raises(ValueError, match="missing an 'id'"):
        plan_batches([{"deps": []}])


def test_numeric_ids_sort_numerically_not_lexically() -> None:
    assert plan_batches([_t(10), _t(2), _t(1)]) == [["1", "2", "10"]]


def test_unicode_digit_id_does_not_crash() -> None:
    # str.isdigit() is True for "²" but int() rejects it -> must fall back to the string branch
    # (the isascii() guard in _sort_key), not raise an uncaught ValueError.
    assert plan_batches([{"id": "²"}]) == [["²"]]


def test_deterministic_regardless_of_input_order() -> None:
    tasks = [_t("T4", "T2", "T3"), _t("T1"), _t("T3", "T1"), _t("T2", "T1")]
    assert plan_batches(tasks) == [["T1"], ["T2", "T3"], ["T4"]]


def test_explicit_none_deps() -> None:
    assert plan_batches([{"id": "T1", "deps": None}]) == [["T1"]]


def test_duplicate_after_coercion_raises() -> None:
    with pytest.raises(ValueError, match="duplicate task id"):
        plan_batches([_t(1), _t("1")])
