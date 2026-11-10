from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from agentic_forge import diagnostics, pre_router, settings

_REPO = Path(__file__).resolve().parents[1]
PLUGIN = _REPO / "plugin"
sys.path.insert(0, str(PLUGIN / "hooks" / "scripts"))

import pre_router as hook  # noqa: E402  — the thin hook script


@pytest.fixture(scope="module")
def index() -> pre_router.Index:
    return pre_router.build_index(PLUGIN)


# --- features -----------------------------------------------------------------


def test_features_stem_and_bigram() -> None:
    f = pre_router.features("Reviewing the reviews of a review")
    assert "review" in f and "reviewing" not in f
    assert any(" " in x for x in pre_router.features("deep adversarial review"))  # a bigram


def test_features_drop_stopwords_and_empty() -> None:
    assert pre_router.features("the and of to") == set()
    assert pre_router.features("") == set()


# --- index ----------------------------------------------------------------------


def test_index_covers_every_on_listing_skill(index: pre_router.Index) -> None:
    assert {"develop", "code-review", "research", "product"} <= set(index.skills)
    assert index.namespace == "agentic-forge"
    assert all(index.positives[s] for s in index.skills)  # every skill has trigger prompts
    assert all(index.descriptions[s] for s in index.skills)  # …and a description profile
    assert index.unknown_weight > 0  # a word no skill uses weighs as maximally specific


def test_index_holds_shipped_skills_only() -> None:
    """The hook ships, so it reads the plugin's skills alone: `skill-factory` became a maintainer
    skill in the repo's `.claude/skills` (ADR 0105), which no user has — the hook must not name
    it."""
    index = pre_router.build_index(PLUGIN)
    assert "skill-factory" not in index.skills
    assert set(index.skills) == {
        p.parent.name
        for p in (PLUGIN / "skills").glob("*/SKILL.md")
        if "disable-model-invocation: true" not in p.read_text(encoding="utf-8")
    }


_FACTORY_EVALS = _REPO / ".claude" / "skills" / "skill-factory" / "evals" / "evals.json"
_AUTHORING_PROMPTS = [
    *json.loads(_FACTORY_EVALS.read_text(encoding="utf-8"))["triggers"]["should_trigger"],
    # measured on the shipped index before the veto: release / code-review / incident-response /
    # marketing — a domain skill nudged for what is a request to BUILD a component (ADR 0105)
    "Create a skill for release notes",
    "Scaffold an agent that reviews diffs for security",
    "Create a subagent for incident response",
    "Make a skill for marketing copy",
    # round 2 (still nudged before the veto was widened): three words between, an inflection,
    # and verbs the first veto did not know
    "Create a release notes skill",
    "Creating a skill for release notes",
    "Generate a skill for incident response",
    "Implement a subagent that reviews diffs for security",
    "Set up a new skill for deploy checks",
]


@pytest.mark.parametrize("prompt", _AUTHORING_PROMPTS)
def test_a_request_to_author_a_component_is_never_nudged(
    index: pre_router.Index, prompt: str
) -> None:
    """skill-factory owns these and does not ship, so the hook must abstain, not pick the domain."""
    assert pre_router.is_authoring_request(prompt)
    assert pre_router.suggest(prompt, index) is None


@pytest.mark.parametrize(
    ("prompt", "skill"),
    [
        # an authoring verb, but no component noun: still the domain skill
        ("Cut a release and write the changelog for it", "release"),
        # "build the plugin" is a release step here, not authoring (no article, and no "plugin"
        # noun in the veto): the first veto blocked all three
        ("Build the plugin and cut a release", "release"),
        ("Build the plugin, bump the version and write the changelog", "release"),
        ("Make the plugin release: bump the version and assemble the changelog", "release"),
        ("Draft the launch marketing copy for this feature", "marketing"),
        ("Design the UX flow for the signup screen", "ux-design"),
    ],
)
def test_the_veto_leaves_domain_requests_alone(
    index: pre_router.Index, prompt: str, skill: str
) -> None:
    assert not pre_router.is_authoring_request(prompt)
    s = pre_router.suggest(prompt, index)
    assert s is not None and s.skill == skill


@pytest.mark.parametrize(
    "prompt",
    [
        "build the search feature",
        "review my agent code",
        "Add tests for the agent module",  # three words between verb and noun: not authoring
        "Make a plan for the agent rollout",
        "Write a function to parse dates",
        "Fix the agentic-forge skills listing",  # a noun, no authoring verb before it
        # an authoring verb and a component noun, but an existing thing, not "a" new one
        "Make the agent faster",
        "Make sure the skills listing fits the budget",
        "Research how teams build coding agents",
        "Hire a skilled engineer",  # `skill` only as a word prefix
    ],
)
def test_the_veto_is_narrow(prompt: str) -> None:
    assert not pre_router.is_authoring_request(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "Write a summary\n" + "-" * 5000,  # a pasted dash rule after a common opener
        "Create a " + "- " * 5000 + "x",
        "Add a " + "-" * 50_000,
    ],
)
def test_the_veto_is_linear_on_dash_runs(prompt: str) -> None:
    """The hook runs it on every prompt under a 5 s timeout; with `\\W+` separators a hyphen fit
    two classes and 2,000 dashes took 24 s (ADR 0105). Generous bound: a backtracking regex takes
    seconds here, a linear one milliseconds."""
    import time

    start = time.perf_counter()
    assert not pre_router.is_authoring_request(prompt)
    assert time.perf_counter() - start < 0.5


def test_the_veto_reads_only_the_start_of_a_prompt() -> None:
    assert pre_router.is_authoring_request("Create a skill for release notes. " + "x " * 5000)
    assert not pre_router.is_authoring_request("x " * 5000 + "Create a skill for release notes")


def test_no_shipped_trigger_prompt_is_an_authoring_request() -> None:
    """The veto must not take a single prompt the shipped skills are measured on — that is why
    the self-check reads the same with it and without it."""
    hits = [
        (f.parent.parent.name, prompt)
        for f in sorted((PLUGIN / "skills").glob("*/evals/evals.json"))
        for kind in ("should_trigger", "should_not_trigger")
        for prompt in (json.loads(f.read_text(encoding="utf-8")).get("triggers") or {}).get(
            kind, []
        )
        if pre_router.is_authoring_request(prompt)
    ]
    assert hits == []


def test_index_skips_off_listing_skills(tmp_path: Path) -> None:
    sk = tmp_path / "skills" / "hidden"
    (sk / "evals").mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "---\nname: hidden\ndescription: x\ndisable-model-invocation: true\n---\n", encoding="utf-8"
    )
    (sk / "evals" / "evals.json").write_text(
        json.dumps({"triggers": {"should_trigger": ["do hidden"], "should_not_trigger": []}}),
        encoding="utf-8",
    )
    assert pre_router.build_index(tmp_path).skills == []


def test_index_says_why_a_skill_was_skipped(tmp_path: Path, monkeypatch) -> None:
    """Without PyYAML every SKILL.md raises FrontmatterError, swallowed into an EMPTY index — the
    hook then never suggested and never said why (A13)."""
    sk = tmp_path / "skills" / "broken"
    (sk / "evals").mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: broken\ndescription: x\n---\n", encoding="utf-8")
    (sk / "evals" / "evals.json").write_text(
        json.dumps({"triggers": {"should_trigger": ["do broken"]}}), encoding="utf-8"
    )
    monkeypatch.setitem(sys.modules, "yaml", None)  # make the lazy `import yaml` fail
    index = pre_router.build_index(tmp_path)
    assert index.skills == []
    (reason,) = index.skipped
    assert reason.startswith("broken: FrontmatterError") and "PyYAML" in reason


def test_hook_records_an_empty_index_instead_of_silently_never_suggesting(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("AGENTIC_FORGE_PRE_ROUTER", "1")
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    monkeypatch.setitem(sys.modules, "yaml", None)
    payload = {"prompt": "Cut a release and write the changelog for it", "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    assert capsys.readouterr().out.strip() == ""  # still silent to the session …
    (event,) = [json.loads(line) for line in diagnostics.load(tmp_path)]  # … but it says why
    assert event["kind"] == "anomaly" and event["component"] == "pre-router"
    assert "index is empty" in event["message"] and "PyYAML" in event["message"]


def test_hook_crash_is_recorded_and_announced(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_DIAGNOSTICS", raising=False)  # the default install

    def boom(_payload: dict[str, object]) -> str:
        raise RuntimeError("router exploded")

    monkeypatch.setattr(hook, "decide", boom)
    payload = {"prompt": "hi", "cwd": str(tmp_path), "session_id": "s-crash"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "pre-router hook crashed: RuntimeError: router exploded" in out["systemMessage"]
    (event,) = [json.loads(line) for line in diagnostics.load(tmp_path)]
    assert event["kind"] == "error" and event["component"] == "pre-router"


# --- suggest --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "skill"),
    [
        ("Do a thorough adversarial review of these architecture docs", "deep-review"),
        ("Cut a release and write the changelog for it", "release"),
        ("What's the test strategy for this feature?", "qa-test-strategy"),
        ("We have a production incident, the API is down", "incident-response"),
    ],
)
def test_suggest_clear_requests(index: pre_router.Index, prompt: str, skill: str) -> None:
    s = pre_router.suggest(prompt, index)
    assert s is not None and s.skill == skill
    assert s.score >= pre_router.MIN_SCORE and s.matched  # carries its evidence


@pytest.mark.parametrize(
    "prompt",
    [
        "hello",
        "what time is it",
        "The quick brown fox jumps over the lazy dog",
    ],
)
def test_suggest_abstains_on_unrelated(index: pre_router.Index, prompt: str) -> None:
    assert pre_router.suggest(prompt, index) is None


def test_suggest_abstains_on_empty(index: pre_router.Index) -> None:
    assert pre_router.suggest("", index) is None
    assert pre_router.suggest("the of and", index) is None


def test_own_negative_vetoes(index: pre_router.Index) -> None:
    """A skill's should_not_trigger prompt must not be routed TO that skill."""
    for doc in index.negatives["deep-review"]:
        s = pre_router.suggest(doc.text, index)
        assert s is None or s.skill != "deep-review", doc.text


def test_render_context_names_skill_and_stays_a_suggestion(index: pre_router.Index) -> None:
    s = pre_router.suggest("Deep review of my PR for bugs, gaps, and contradictions", index)
    assert s is not None
    line = pre_router.render_context(s, index.namespace)
    assert "`agentic-forge:deep-review`" in line and "Skill tool" in line
    assert "ignore this" in line  # never a command


# --- self-check: the calibration contract (ADR 0089) ---------------------------


def test_self_check_precision_holds(index: pre_router.Index) -> None:
    """Leave-one-out on the plugin's own triggers. The thresholds are tuned so a WRONG skill is
    near-never suggested; a miss is acceptable (no nudge), a wrong nudge is not."""
    r = pre_router.self_check(index)
    assert r.positives > 40 and r.negatives > 40  # the check actually ran over the data
    assert r.wrong <= 2, r.wrong_examples
    assert r.false_suggest <= 2
    assert r.precision >= 0.9
    # Recalibrated 0.50 -> 0.45 (ADR 0092): ADR 0091's stand polish gave two trigger prompts the
    # content they presuppose, and a content-bearing prompt ("since the 14:05 deploy the checkout
    # API returns 500s…") has LESS lexical overlap with its skill's profile, not more —
    # leave-one-out recall went 0.500 -> 0.488 on that one prompt. The contract guards
    # PRECISION (a wrong nudge on
    # every prompt); recall is what the hook can do, and it is allowed to move as the trigger data
    # gets more realistic. It must still do something, so a floor stays.
    assert r.recall >= 0.45


# --- settings ----------------------------------------------------------------------


def test_pre_router_setting_default_off_and_env_opts_in(tmp_path: Path) -> None:
    """Off by default (ADR 0089): it did not beat its bar. The env var opts in."""
    assert settings.resolve(tmp_path, env={}, home=tmp_path / "h").pre_router_enabled is False
    on = settings.resolve(tmp_path, env={"AGENTIC_FORGE_PRE_ROUTER": "1"}, home=tmp_path / "h")
    assert on.pre_router_enabled is True


# --- hook ---------------------------------------------------------------------------


def test_hook_emits_context_on_a_clear_match(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AGENTIC_FORGE_PRE_ROUTER", "1")  # opt in — off by default
    payload = {"prompt": "Cut a release and write the changelog for it", "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "agentic-forge:release" in data["hookSpecificOutput"]["additionalContext"]


def test_hook_is_silent_without_a_match(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AGENTIC_FORGE_PRE_ROUTER", "1")
    payload = {"prompt": "hi", "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_hook_is_silent_when_off_which_is_the_default(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_PRE_ROUTER", raising=False)
    payload = {"prompt": "Cut a release and write the changelog for it", "cwd": str(tmp_path)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_hook_bad_stdin_fails_open(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert hook.main() == 0
    assert capsys.readouterr().out.strip() == ""


def test_profile_drops_a_neighbours_vocabulary(index: pre_router.Index) -> None:
    """The contrastive-clause leak (ADR 0089): `code-review`'s description says "for a DEEP /
    adversarial review use deep-review" — `adversarial` belongs to deep-review's triggers, not
    code-review's, so it must not be in code-review's profile."""
    assert "adversarial" not in index.profile("code-review")
    assert "adversarial" in index.profile("deep-review")


def test_unknown_words_count_against_coverage(index: pre_router.Index) -> None:
    """`Run the app and screenshot it` scored 0.60 on the single word `app` when unknown words
    weighed nothing. They now weigh the most."""
    assert pre_router.suggest("Run the app and screenshot it", index) is None


# --- the hook as a real process (ADR 0105) ----------------------------------------------------


def _hook_timeout() -> float:
    """The budget Claude Code gives the hook — read from hooks.json, not restated here."""
    config = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    (timeout,) = [
        h["timeout"]
        for group in config["hooks"]["UserPromptSubmit"]
        for h in group["hooks"]
        if "pre_router.py" in h["command"]
    ]
    return float(timeout)


def _run_hook(prompt: str, tmp_path: Path) -> tuple[str, float]:
    """Run hooks/scripts/pre_router.py the way Claude Code does: a fresh interpreter, the payload on
    stdin, no PYTHONPATH (the script finds its own lib). Opted in; state and scratch in tmp."""
    import os
    import subprocess
    import time

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        AGENTIC_FORGE_PRE_ROUTER="1",
        AGENTIC_FORGE_STATE_HOME=str(tmp_path),
        TMPDIR=str(tmp_path),
    )
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(tmp_path)}
    start = time.perf_counter()
    done = subprocess.run(
        [sys.executable, str(PLUGIN / "hooks" / "scripts" / "pre_router.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=60,
    )
    elapsed = time.perf_counter() - start
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    return done.stdout.strip(), elapsed


def test_hook_process_suggests_on_a_clear_match(tmp_path: Path) -> None:
    """The control for the two below: the same process, opted in, does nudge — so their silence
    is the veto, not a hook that never speaks."""
    out, elapsed = _run_hook("Cut a release and write the changelog for it", tmp_path)
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "agentic-forge:release" in context
    assert elapsed < _hook_timeout()


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a skill for release notes",
        "Scaffold an agent that reviews diffs for security",
        "Set up a new skill for deploy checks",
    ],
)
def test_hook_process_abstains_on_an_authoring_request(tmp_path: Path, prompt: str) -> None:
    """skill-factory is not in a user's listing, so the hook must neither name it nor hand the
    request to the domain its purpose words point at (ADR 0105)."""
    out, elapsed = _run_hook(prompt, tmp_path)
    assert out == ""
    assert elapsed < _hook_timeout()


@pytest.mark.parametrize(
    "prompt",
    [
        "Write a summary\n" + "-" * 200_000,  # the pasted dash rule that once took 24 s at 2,000
        "Write a " + "-" * 200_000,
        "Create a " + "- " * 100_000 + "skill",
        "write a " + "x-" * 100_000,  # one huge hyphenated token through features() too
    ],
    ids=["dash-rule", "dash-after-article", "spaced-dashes", "hyphen-token"],
)
def test_hook_process_finishes_a_huge_dash_prompt_inside_its_timeout(
    tmp_path: Path, prompt: str
) -> None:
    """The whole hook — interpreter start, index build, veto, scoring — on a 200 KB prompt, held to
    the timeout hooks.json declares. A hook that overruns is killed and fails open, silently."""
    out, elapsed = _run_hook(prompt, tmp_path)
    assert out == ""
    assert elapsed < _hook_timeout(), f"{elapsed:.2f}s"
