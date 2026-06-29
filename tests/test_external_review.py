"""Tests for the external reviewer seam (ADR 0042)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_forge import external_review

_FINDING = {"severity": "major", "location": "a.py:1", "issue": "bug", "suggestion": "fix"}
_VALID = json.dumps({"verdict": "changes", "findings": [_FINDING]})


def _runner(out: str):  # type: ignore[no-untyped-def]
    def run(command: str, prompt: str, workdir: Path, timeout: int) -> str:
        return out

    return run


# --- build_prompt ------------------------------------------------------------


def test_build_prompt_kinds_and_fallback() -> None:
    for kind in external_review.KINDS:
        prompt = external_review.build_prompt("TARGET-X", kind)
        assert "TARGET-X" in prompt and '"verdict"' in prompt  # criteria + format + target
    # unknown kind falls back to the code criteria
    assert external_review.build_prompt("t", "bogus") == external_review.build_prompt("t", "code")


# --- is_available / run_external (the subprocess seam) -----------------------


def test_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_review.shutil, "which", lambda c: "/usr/bin/" + c)
    assert external_review.is_available("codex")
    monkeypatch.setattr(external_review.shutil, "which", lambda c: None)
    assert not external_review.is_available("codex")
    assert not external_review.is_available("")  # empty command


def test_run_external_unavailable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_review.shutil, "which", lambda c: None)
    assert external_review.run_external("codex", "p", Path("."), runner=_runner("x")) is None


def test_run_external_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_review.shutil, "which", lambda c: "/bin/codex")
    assert external_review.run_external("codex", "p", Path("."), runner=_runner("OUT")) == "OUT"

    def boom(command: str, prompt: str, workdir: Path, timeout: int) -> str:
        raise RuntimeError("cli failed")

    assert external_review.run_external("codex", "p", Path("."), runner=boom) is None


# --- parse_review ------------------------------------------------------------


def test_parse_review_valid() -> None:
    assert external_review.parse_review("prose " + _VALID + " trailing") == {
        "verdict": "changes",
        "findings": [_FINDING],
    }


def test_parse_review_normalises_and_skips_non_dict_findings() -> None:
    out = '{"verdict":"approve","findings":[{"text":"x"}, 5, {"severity":"nit"}]}'
    result = external_review.parse_review(out)
    assert result is not None and result["verdict"] == "approve"
    assert len(result["findings"]) == 2  # the bare int 5 is skipped
    assert result["findings"][0] == {
        "severity": "minor",  # default
        "location": "",
        "issue": "x",  # text -> issue fallback
        "suggestion": "",
    }


def test_parse_review_rejects_garbage_and_bad_shapes() -> None:
    assert external_review.parse_review("no json here at all") is None  # no JSON object
    assert external_review.parse_review('{"verdict":"maybe","findings":[]}') is None  # bad verdict
    bad_findings = '{"verdict":"approve","findings":"nope"}'  # findings not a list
    assert external_review.parse_review(bad_findings) is None


# --- review (orchestration) --------------------------------------------------


def test_review_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(external_review.shutil, "which", lambda c: "/bin/codex")
    got = external_review.review("t", "code", runner=_runner(_VALID))
    assert got is not None and got["verdict"] == "changes"
    assert external_review.review("t", "code", runner=_runner("garbage")) is None  # unparseable
    monkeypatch.setattr(external_review.shutil, "which", lambda c: None)
    assert external_review.review("t", "code", runner=_runner(_VALID)) is None  # unavailable


# --- safety: read-only invocation + robust/sanitised parsing -----------------


def test_argv_is_read_only() -> None:
    argv = external_review._argv("codex", "PROMPT")
    assert argv[0] == "codex" and "exec" in argv and "PROMPT" in argv
    assert "read-only" in argv  # a reviewer must never be able to mutate the repo


def test_parse_review_skips_leading_non_review_json() -> None:
    # codex exec can print a session/event object first; the review object comes later
    out = '{"session_id":"abc"}\n{"verdict":"changes","findings":[]}'
    result = external_review.parse_review(out)
    assert result is not None and result["verdict"] == "changes"


def test_parse_review_clamps_severity_and_sanitises_fields() -> None:
    out = '{"verdict":"changes","findings":[{"severity":"WAT","issue":"l1\\n---\\n## h"}]}'
    result = external_review.parse_review(out)
    assert result is not None
    finding = result["findings"][0]
    assert finding["severity"] == "minor"  # unknown severity clamped to the vocab
    assert "\n" not in finding["issue"] and "l1" in finding["issue"]  # newlines collapsed
