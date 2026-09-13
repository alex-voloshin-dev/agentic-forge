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
    report = activation.activation_rate(trig, run, tmp_path, target="research")
    assert report.activated == 1 and report.prompts == len(trig.should_trigger)
    assert report.rate == 1 / report.prompts
    assert len(report.misses) == report.prompts - 1


def _report(skill: str, activated: int, prompts: int) -> activation.ActivationReport:
    return activation.ActivationReport(skill, activated, prompts, activated / prompts)


def test_the_gate_is_pooled_over_prompts_not_per_skill() -> None:
    """ADR 0093: per-skill n is 4-9, so the verdict is one binomial over the run. 3/5 and 5/5 pool
    to 8/10 = 0.800 — a per-skill floor of 0.8 would fail the first skill; the pooled gate at 0.8
    passes. 0/5 and 4/4 pool to 4/9 = 0.444 and fail with the reason on the line."""
    verdict = activation.pooled([_report("a", 3, 5), _report("b", 5, 5)], min_activation=0.8)
    assert (verdict.activated, verdict.prompts, verdict.rate, verdict.skills) == (8, 10, 0.8, 2)
    assert verdict.passed and verdict.gated and "PASS" in verdict.summary_line()
    assert verdict.mean_of_rates == 0.8  # printed beside the pooled rate, never gated
    short = activation.pooled([_report("a", 0, 5), _report("b", 4, 4)], min_activation=0.8)
    assert not short.passed and "0.444" in short.reasons[0] and "FAIL" in short.summary_line()


def test_pooled_without_a_floor_measures_and_never_fails() -> None:
    verdict = activation.pooled([_report("a", 0, 5)])
    assert verdict.passed and not verdict.gated and "----" in verdict.summary_line()
    empty = activation.pooled([], min_activation=0.5)
    assert empty.rate == 0.0 and not empty.passed  # a gated run that measured nothing fails


def test_run_activation_measures_all_and_a_subset(tmp_path: Path) -> None:
    def never(system: str, prompt: str, workdir: Path) -> str:
        return _stream(_bash("git status"))

    all_reports = activation.run_activation(PLUGIN, never, workdir=tmp_path)
    assert len(all_reports) > 1 and all(r.rate == 0.0 for r in all_reports)
    one = activation.run_activation(PLUGIN, never, skills=["plan"], workdir=tmp_path)
    assert [r.skill for r in one] == ["plan"]


def test_summary_line_is_a_lens_without_a_verdict(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "plan")
    run = _router({})
    report = activation.activation_rate(trig, run, tmp_path, target="plan")
    line = report.summary_line()
    assert line.startswith("[plan] activation=0.000 (0/") and "FAIL" not in line


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
        trig, run, tmp_path, target="research", ask_why=ask
    )
    assert report.activated == 1
    assert len(report.why) == len(trig.should_trigger) - 1 == len(asked)
    assert all("agentic-forge:research" in q for _, q in asked)  # the skill it had available
    assert all(p != hit for p, _ in report.why)  # never asked about the hit
    assert activation.bucket_why(report.why[0][1]) == "task-is-simple"


def test_a_miss_without_a_session_id_is_never_silent(tmp_path: Path) -> None:
    """A transcript with no init line (the session never started, or a timeout cut it off first)
    cannot be resumed and asked — so the miss carries NO_SESSION as its reason instead of
    vanishing from the why-list (ADR 0093)."""
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "plan")

    def run(system: str, prompt: str, workdir: Path) -> str:
        return _stream(_bash("ls"))  # a turn happened, but no init line survived

    asked: list[str] = []
    report = activation.activation_rate(
        trig, run, tmp_path, target="plan", ask_why=lambda sid, q: asked.append(sid) or "x"
    )
    assert not asked and len(report.why) == len(trig.should_trigger)
    assert all(reason == activation.NO_SESSION for _, reason in report.why)


def _limit_hit(sid: str) -> str:
    """The transcript of a session the usage limit refused: an init line and an error result, no
    assistant turn — what 4 of 5 `research` sessions handed back on 2026-09-13."""
    result = {"type": "result", "subtype": "error", "is_error": True,
              "result": "You've hit your session limit · resets 4pm (America/New_York)"}
    return _init(sid) + "\n" + json.dumps(result)


def test_a_session_that_never_ran_is_neither_a_hit_nor_a_miss(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "research")
    hit = trig.should_trigger[0]

    def run(system: str, prompt: str, workdir: Path) -> str:
        return _stream(_skill_call("research")) if prompt == hit else _limit_hit("s")

    asked: list[str] = []
    report = activation.activation_rate(
        trig, run, tmp_path, target="research", ask_why=lambda sid, q: asked.append(sid) or "x"
    )
    n = len(trig.should_trigger)
    assert (report.activated, report.prompts, report.determined) == (1, n, 1)
    assert report.rate == 1.0 and not report.misses and not asked  # nothing to ask why
    assert len(report.undetermined) == n - 1
    assert all("session limit" in err for _, err in report.undetermined)
    assert f"(1/1; {n - 1} never ran)" in report.summary_line()
    assert not activation.session_ran("") and activation.session_error("") == "<no transcript>"


def test_pooled_fails_a_gated_run_whose_sessions_mostly_never_ran() -> None:
    dead = [("p", "limit")]
    thin = [_report("a", 5, 5), activation.ActivationReport("b", 0, 5, 0.0, undetermined=dead * 5)]
    verdict = activation.pooled(thin, min_activation=0.8)
    assert verdict.rate == 1.0 and verdict.determined == 5 and verdict.undetermined == 5
    assert not verdict.passed and "never ran" in verdict.reasons[0]  # 5 of 10 > 10%
    assert "5 of 10 never ran" in verdict.summary_line()
    stray = [_report("a", 9, 9), activation.ActivationReport("b", 4, 5, 1.0, undetermined=dead)]
    assert activation.pooled(stray, min_activation=0.8).passed  # 1 of 14: excluded, not a miss
    assert activation.pooled(thin).passed  # ungated: a measurement, reported as it is


def test_ask_why_failure_does_not_lose_the_measurement(tmp_path: Path) -> None:
    trig = next(t for t in load_triggers(PLUGIN) if t.name == "plan")

    def run(system: str, prompt: str, workdir: Path) -> str:
        return _init("s1") + "\n" + _stream(_bash("ls"))

    def boom(sid: str, question: str) -> str:
        raise RuntimeError("resume failed")

    report = activation.activation_rate(
        trig, run, tmp_path, target="plan", ask_why=boom
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
        trig, run, tmp_path, target="plan", workspace_factory=factory
    )
    assert made[0] == len(trig.should_trigger) and len(set(seen)) == len(seen)  # one fresh dir each
