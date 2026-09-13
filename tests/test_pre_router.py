from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from agentic_forge import pre_router, settings

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


# --- suggest --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prompt", "skill"),
    [
        ("Do a thorough adversarial review of these architecture docs", "deep-review"),
        ("Cut a release and write the changelog for it", "release"),
        ("What's the test strategy for this feature?", "qa-test-strategy"),
        ("Scaffold a new skill for release notes", "skill-factory"),
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
    assert r.recall >= 0.5  # it must also DO something


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
