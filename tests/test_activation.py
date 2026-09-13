from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "lib"))
sys.path.insert(0, str(_REPO / "dev"))

from agentic_forge import activation  # noqa: E402
from agentic_forge.tier1_runner import load_triggers  # noqa: E402

PLUGIN = _REPO / "plugin"


def _stream(*blocks: dict) -> str:
    """A stream-json transcript: one assistant message per block dict."""
    return "\n".join(
        json.dumps({"type": "assistant", "message": {"content": [b]}}) for b in blocks
    )


def _skill_call(name: str) -> dict:
    return {"type": "tool_use", "name": "Skill", "input": {"skill": name}}


def _bash(cmd: str) -> dict:
    return {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}


# --- skill_invoked ------------------------------------------------------------


def test_skill_invoked_matches_bare_and_namespaced() -> None:
    assert activation.skill_invoked(_stream(_skill_call("research")), "research")
    assert activation.skill_invoked(_stream(_skill_call("agentic-forge:research")), "research")
    # target may itself be namespaced (as run_activation could pass it)
    assert activation.skill_invoked(_stream(_skill_call("research")), "agentic-forge:research")


def test_a_session_that_only_did_the_work_did_not_activate() -> None:
    # the field shape: Bash/Read, never a Skill call
    stream = _stream(_bash("git show --stat HEAD"), _bash("git diff HEAD~1"))
    assert not activation.skill_invoked(stream, "code-review")


def test_naming_a_skill_in_prose_is_not_invoking_it() -> None:
    text = {"type": "text", "text": "The code-review skill would fit, but I'll just do it."}
    assert not activation.skill_invoked(_stream(text), "code-review")


def test_the_wrong_skill_call_is_not_a_hit() -> None:
    assert not activation.skill_invoked(_stream(_skill_call("develop")), "code-review")


def test_skill_invoked_tolerates_a_single_json_envelope() -> None:
    envelope = json.dumps(
        {"type": "assistant", "message": {"content": [_skill_call("plan")]}}
    )
    assert activation.skill_invoked(envelope, "plan")


def test_skill_invoked_ignores_unparseable_lines() -> None:
    stream = "not json\n" + _stream(_skill_call("release")) + "\n{partial"
    assert activation.skill_invoked(stream, "release")


# --- activation_rate / run_activation -----------------------------------------


def _router(by_prompt: dict[str, str]):
    """A fake session: returns a Skill call for prompts in the map, plain Bash otherwise."""

    def run(system: str, prompt: str, workdir: Path) -> str:
        name = by_prompt.get(prompt)
        return _stream(_skill_call(name)) if name else _stream(_bash("ls"))

    return run


def test_activation_rate_counts_only_invocations(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "research")
    # activate on the first prompt only
    run = _router({trig.should_trigger[0]: "research"})
    report = activation.activation_rate(trig, run, tmp_path, target="research", min_activation=None)
    assert report.activated == 1 and report.prompts == len(trig.should_trigger)
    assert report.passed  # no threshold -> a measurement never fails
    assert len(report.misses) == report.prompts - 1


def test_min_activation_gates(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "research")
    run = _router({})  # never activates
    report = activation.activation_rate(trig, run, tmp_path, target="research", min_activation=0.9)
    assert report.rate == 0.0 and not report.passed and report.reasons


def test_run_activation_measures_all_and_a_subset(tmp_path: Path) -> None:
    def never(system: str, prompt: str, workdir: Path) -> str:
        return _stream(_bash("git status"))

    all_reports = activation.run_activation(PLUGIN, never, workdir=tmp_path)
    assert len(all_reports) > 1 and all(r.rate == 0.0 and r.passed for r in all_reports)
    one = activation.run_activation(PLUGIN, never, skills=["plan"], workdir=tmp_path)
    assert [r.skill for r in one] == ["plan"]


def test_summary_line_shows_measure_when_ungated(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "plan")
    run = _router({})
    report = activation.activation_rate(trig, run, tmp_path, target="plan", min_activation=None)
    line = report.summary_line()
    assert "----" in line and "activation=0.000" in line
