"""Regression tests for the third deep-review round's code fixes."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from agentic_forge import benchmark, connectors, naming, tier1_runner
from agentic_forge.frontmatter import parse
from agentic_forge.validation import Report, _check_refs, validate_skill

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
sys.path.insert(0, str(_REPO / "dev"))

import run_agent_evals  # noqa: E402
import run_skill_evals  # noqa: E402
import run_tier1_evals  # noqa: E402


def test_naming_rejects_trailing_newline() -> None:
    assert naming.is_valid_name("abc")
    assert not naming.is_valid_name("abc\n")  # \Z, not $ (which would accept a trailing newline)


def test_parse_gh_runs_null_fields_become_empty() -> None:
    payload = json.dumps(
        [{"headSha": None, "createdAt": None, "status": "completed", "conclusion": "success"}]
    )
    runs = connectors.parse_gh_runs(payload, "prod")
    assert runs and runs[0].sha == "" and runs[0].at == ""  # explicit JSON null -> "" not "None"


def test_check_refs_ignores_links_in_code_spans(tmp_path: Path) -> None:
    base = tmp_path / "skills" / "s"
    base.mkdir(parents=True)
    report = Report()
    # a relative link AND a local ref, both inside code spans -> examples, not real refs
    _check_refs("```\n[x](../../nope.md)\n```\n`](references/nope.md)`", base, "s", report)
    assert report.errors == []


def test_parse_handles_crlf_frontmatter() -> None:
    fm, body = parse("---\r\na: 1\r\n---\r\nbody line\r\n")
    assert fm == {"a": 1} and "body line" in body


def test_summarize_stddev_is_sample_stdev() -> None:
    b = benchmark.summarize([{"summary": {"pass_rate": 0.8}}, {"summary": {"pass_rate": 0.9}}])
    sd = b["run_summary"]["with_skill"]["pass_rate"]["stddev"]
    assert abs(sd - statistics.stdev([0.8, 0.9])) < 1e-9  # sample stdev (n-1), not pstdev


def test_selection_rate_runs_zero_does_not_crash() -> None:
    rate = tier1_runner.selection_rate(
        lambda s, p, w: "x", "sys", "prompt", ["x"], 0, Path("."), target="x"
    )
    assert rate == 0.0


def test_description_length_boundary(make_skill) -> None:
    ok = validate_skill(make_skill(frontmatter="name: demo\ndescription: " + "d" * 1024))
    assert not any("description exceeds" in i.message for i in ok.errors)
    over = validate_skill(make_skill(frontmatter="name: demo\ndescription: " + "d" * 1025))
    assert any("description exceeds" in i.message for i in over.errors)


def test_build_runners_claude_paths_return_callables() -> None:
    # exercises the real "claude" construction branch (tool selection / turn caps), not just the
    # bogus-raise path — the dev/ coverage hole R3 flagged. Builds closures; no model call.
    r, g = run_agent_evals._build_runners("claude", "reviewer", _PLUGIN, "m")
    assert callable(r) and callable(g)
    sr, sg = run_skill_evals._build_runners("claude", "python-patterns", _PLUGIN, "m")
    assert callable(sr) and callable(sg)
    assert callable(run_tier1_evals._build_router("claude", "m"))
