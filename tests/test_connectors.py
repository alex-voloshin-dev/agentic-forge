from __future__ import annotations

import json

import pytest

from agentic_forge import connectors, ops
from agentic_forge.connectors import (
    GhPipelineSource,
    parse_gh_runs,
    pipeline_source,
)


def _runs(*runs: dict) -> str:
    return json.dumps(list(runs))


# --- parse_gh_runs: status mapping -----------------------------------------------------


@pytest.mark.parametrize(
    "run,expected",
    [
        ({"status": "completed", "conclusion": "success"}, "passing"),
        ({"status": "completed", "conclusion": "failure"}, "failing"),
        ({"status": "completed", "conclusion": "timed_out"}, "failing"),
        ({"status": "completed", "conclusion": "startup_failure"}, "failing"),
        ({"status": "completed", "conclusion": "cancelled"}, "passing"),  # not a failure
        ({"status": "completed", "conclusion": "skipped"}, "passing"),
        ({"status": "in_progress"}, "running"),
        ({"status": "queued"}, "queued"),
        ({"status": "waiting"}, "queued"),
        ({"status": "weird"}, "running"),  # unknown in-flight -> running
    ],
)
def test_parse_status_mapping(run: dict, expected: str) -> None:
    run = {"headSha": "abcdef0123", "createdAt": "2026-06-24T10:00:00Z", **run}
    deploys = parse_gh_runs(_runs(run), "production")
    assert len(deploys) == 1 and deploys[0].status == expected


def test_parse_fields_and_sha_shortened() -> None:
    payload = _runs({"headSha": "abcdef0123456789", "status": "completed", "conclusion": "success",
                     "createdAt": "2026-06-24T10:00:00Z"})
    d = parse_gh_runs(payload, "staging")[0]
    assert d.sha == "abcdef0" and d.environment == "staging" and d.at == "2026-06-24T10:00:00Z"


def test_parse_preserves_order() -> None:
    payload = _runs(
        {"headSha": "aaa", "status": "completed", "conclusion": "failure"},
        {"headSha": "bbb", "status": "completed", "conclusion": "success"},
    )
    deploys = parse_gh_runs(payload, "prod")
    assert [d.sha for d in deploys] == ["aaa", "bbb"]  # gh returns newest first; order kept


# --- parse_gh_runs: tolerance ----------------------------------------------------------


def test_parse_empty_list() -> None:
    assert parse_gh_runs("[]", "prod") == []


def test_parse_invalid_json_is_empty() -> None:
    assert parse_gh_runs("not json", "prod") == []


def test_parse_non_list_is_empty() -> None:
    assert parse_gh_runs('{"runs": 1}', "prod") == []


def test_parse_skips_non_dict_entries() -> None:
    good = {"headSha": "a", "status": "completed", "conclusion": "success"}
    payload = json.dumps([good, 42, "x"])
    assert len(parse_gh_runs(payload, "prod")) == 1


def test_parse_run_missing_fields() -> None:
    d = parse_gh_runs("[{}]", "prod")[0]
    assert d.sha == "" and d.status == "running" and d.at == ""


# --- GhPipelineSource.recent_deploys (seam monkeypatched) ------------------------------


def test_recent_deploys_parses_fetched_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _runs({"headSha": "abc1234", "status": "completed", "conclusion": "success"})
    monkeypatch.setattr(connectors, "_gh_run_list", lambda repo, limit: payload)
    deploys = GhPipelineSource("owner/repo").recent_deploys("prod")
    assert len(deploys) == 1 and deploys[0].status == "passing"


def test_recent_deploys_degrades_on_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(repo: str, limit: int) -> str:
        raise OSError("gh not found")

    monkeypatch.setattr(connectors, "_gh_run_list", boom)
    assert GhPipelineSource("owner/repo").recent_deploys("prod") == []


# --- pipeline_source selection ---------------------------------------------------------


def test_pipeline_source_uses_gh_when_available() -> None:
    src = pipeline_source("owner/repo", available=lambda: True)
    assert isinstance(src, GhPipelineSource)
    assert isinstance(src, ops.PipelineSource)  # satisfies the Protocol


def test_pipeline_source_falls_back_without_gh() -> None:
    src = pipeline_source("owner/repo", available=lambda: False)
    assert isinstance(src, ops.InMemoryPipeline)
    assert src.recent_deploys("prod") == []  # empty, graceful
