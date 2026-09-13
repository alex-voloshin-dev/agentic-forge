from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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


# --- ask why (ADR 0088, step 4) --------------------------------------------------------


def _init(sid: str) -> str:
    return json.dumps({"type": "system", "subtype": "init", "session_id": sid})


def test_session_id_of_reads_the_init_object() -> None:
    stream = _init("abc-123") + "\n" + _stream(_bash("ls"))
    assert activation.session_id_of(stream) == "abc-123"
    assert activation.session_id_of(_stream(_bash("ls"))) is None


def test_ask_why_is_called_only_for_misses_and_kept_beside_the_prompt(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "research")
    hit = trig.should_trigger[0]

    def run(system: str, prompt: str, workdir: Path) -> str:
        body = _skill_call("research") if prompt == hit else _bash("ls")
        return _init("sid-" + str(abs(hash(prompt)) % 1000)) + "\n" + _stream(body)

    asked: list[tuple[str, str]] = []

    def ask(sid: str, question: str) -> str:
        asked.append((sid, question))
        return "It looked simple enough to do directly."

    report = activation.activation_rate(
        trig, run, tmp_path, target="research", min_activation=None, ask_why=ask
    )
    assert report.activated == 1
    assert len(report.why) == len(trig.should_trigger) - 1 == len(asked)
    assert all("agentic-forge:research" in q for _, q in asked)  # the skill it had available
    assert all(p != hit for p, _ in report.why)  # never asked about the hit
    assert activation.bucket_why(report.why[0][1]) == "task-is-simple"


def test_ask_why_failure_does_not_lose_the_measurement(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "plan")

    def run(system: str, prompt: str, workdir: Path) -> str:
        return _init("s1") + "\n" + _stream(_bash("ls"))

    def boom(sid: str, question: str) -> str:
        raise RuntimeError("resume failed")

    report = activation.activation_rate(
        trig, run, tmp_path, target="plan", min_activation=None, ask_why=boom
    )
    assert report.rate == 0.0 and all("follow-up failed" in a for _, a in report.why)


@pytest.mark.parametrize(
    ("answer", "bucket"),
    [
        ("Invoking it felt like overhead for a small change.", "cost/overhead"),
        ("The request was straightforward so I did it directly.", "task-is-simple"),
        ("I did not notice the skill was available.", "not-noticed"),
        ("The skill did not apply to this kind of request.", "not-applicable"),
        ("Because.", "other"),
    ],
)
def test_bucket_why(answer: str, bucket: str) -> None:
    assert activation.bucket_why(answer) == bucket


# --- a real workspace per prompt (ADR 0090) --------------------------------------


def test_prepare_workspace_gives_a_prompt_something_to_work_on(tmp_path: Path) -> None:
    """The first runs used one empty temp dir for all 84 prompts; 36/36 stated reasons were
    "there was nothing to review / implement / audit". Now each prompt gets a repo with a
    history, a feature branch, a diff, and the plan."""
    import subprocess

    repo = activation.prepare_workspace(PLUGIN, tmp_path)
    assert (repo / "taskstore.py").is_file()
    assert (repo / "docs/sdlc/task-priorities/plan.md").is_file()

    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout

    assert git("branch", "--show-current").strip() == "feature/task-priorities"
    assert git("log", "--oneline", "main..HEAD").strip()  # a committed change on the branch
    assert git("diff", "--stat").strip()  # …and an unstaged edit
    assert "priority_of" in (repo / "taskstore.py").read_text(encoding="utf-8")
    assert not (repo / "__pycache__").exists()


def test_prepare_workspace_is_fresh_per_call(tmp_path: Path) -> None:
    a = activation.prepare_workspace(PLUGIN, tmp_path / "one")
    (a / "leftover.txt").write_text("from prompt one", encoding="utf-8")
    b = activation.prepare_workspace(PLUGIN, tmp_path / "two")
    assert not (b / "leftover.txt").exists()  # no cross-prompt contamination


def test_run_activation_uses_the_workspace_factory(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "plan")
    seen: list[Path] = []

    def run(system: str, prompt: str, workdir: Path) -> str:
        seen.append(workdir)
        return _stream(_bash("ls"))

    made = [0]

    def factory() -> Path:
        made[0] += 1
        return tmp_path / f"w{made[0]}"

    activation.activation_rate(
        trig, run, tmp_path, target="plan", min_activation=None, workspace_factory=factory
    )
    assert made[0] == len(trig.should_trigger) and len(set(seen)) == len(seen)  # one fresh dir each
