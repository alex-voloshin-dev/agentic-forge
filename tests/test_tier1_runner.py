from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forge.tier1_runner import (
    SkillTrigger,
    all_passed,
    build_router_system,
    check_wiring,
    eval_skill,
    load_listing,
    load_triggers,
    parse_selection,
    render_listing,
    run_tier1,
    selection_rate,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

# The nine on-listing router skills (the stack packs + engineering-standards are off-listing).
ON_LISTING = {
    "research",
    "product",
    "architecture",
    "plan",
    "develop",
    "code-review",
    "deep-review",
    "skill-factory",
    "knowledge",
    # Stage 4 — quality & operations
    "qa-test-strategy",
    "security-review",
    "deploy-watch",
    "incident-response",
    "release",
    # Stage 5 — marketing
    "marketing",
    # Stage 6 — design & onboarding
    "ux-design",
    "repo-onboarding",
}


# --- live listing ------------------------------------------------------------


def test_load_listing_is_the_on_listing_skills() -> None:
    names = {c.name for c in load_listing(PLUGIN)}
    assert names == ON_LISTING
    # off-listing packs must be excluded
    assert "python-patterns" not in names and "engineering-standards" not in names


def test_load_listing_descriptions_present() -> None:
    assert all(c.description for c in load_listing(PLUGIN))


def test_load_listing_missing_skills_dir(tmp_path: Path) -> None:
    assert load_listing(tmp_path) == []


def test_render_and_system_prompt() -> None:
    cards = load_listing(PLUGIN)
    system = build_router_system(cards)
    assert "Available skills:" in system
    assert "research:" in render_listing(cards)
    assert "none" in system.lower()


# --- parse_selection ---------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("research", "research"),
        ("`research`", "research"),
        ("The research skill applies here.", "research"),
        ("code-review", "code-review"),
        ("none", "none"),
        ("", "none"),
        ("definitely no skill", "none"),  # 'no' is not 'none'
        ("I'd use product, or maybe plan", "product"),  # first-mentioned wins
        ("skill-factory", "skill-factory"),
    ],
)
def test_parse_selection(reply: str, expected: str) -> None:
    names = sorted(ON_LISTING)
    assert parse_selection(reply, names) == expected


def test_selection_rate_is_fraction_for_target(tmp_path: Path) -> None:
    replies = iter(["research", "product", "research"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return next(replies)

    rate = selection_rate(run, "sys", "p", ["research", "product"], 3, tmp_path, target="research")
    assert abs(rate - 2 / 3) < 1e-9


# --- eval_skill --------------------------------------------------------------

_THRESH = {"tier1_trigger": {"recall": 0.9, "specificity": 0.9}}


def test_eval_skill_perfect(tmp_path: Path) -> None:
    trig = SkillTrigger("research", _THRESH, ["a", "b"], ["c", "d"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return "research" if prompt in ("a", "b") else "none"

    rep = eval_skill(trig, ["research", "product"], run, "sys", 1, tmp_path)
    assert rep.recall == 1.0 and rep.specificity == 1.0 and rep.passed
    assert "PASS" in rep.summary_line()


def test_eval_skill_low_recall_fails(tmp_path: Path) -> None:
    trig = SkillTrigger("research", _THRESH, ["a", "b"], ["c", "d"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return "none"  # never selects research

    rep = eval_skill(trig, ["research", "product"], run, "sys", 1, tmp_path)
    assert rep.recall == 0.0 and not rep.passed
    assert any("recall" in r for r in rep.reasons)
    assert "FAIL" in rep.summary_line()


def test_eval_skill_low_specificity_fails(tmp_path: Path) -> None:
    trig = SkillTrigger("research", _THRESH, ["a", "b"], ["c", "d"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return "research"  # wrongly fires on the should-not prompts too

    rep = eval_skill(trig, ["research", "product"], run, "sys", 1, tmp_path)
    assert rep.recall == 1.0 and rep.specificity == 0.0 and not rep.passed
    assert any("specificity" in r for r in rep.reasons)


# --- load_triggers + run_tier1 (integration on the real plugin) --------------


def test_load_triggers_covers_the_on_listing_skills() -> None:
    trigs = {t.name: t for t in load_triggers(PLUGIN)}
    assert set(trigs) == ON_LISTING
    for t in trigs.values():
        assert t.should_trigger and t.should_not_trigger
        assert not t.off_listing


def _oracle(plugin: Path):
    """A perfect router: maps each should_trigger prompt to its owning skill, else 'none'."""
    owner: dict[str, str] = {}
    for trig in load_triggers(plugin):
        for prompt in trig.should_trigger:
            owner[prompt] = trig.name

    def run(system: str, prompt: str, workdir: Path) -> str:
        return owner.get(prompt, "none")

    return run


def test_run_tier1_all_pass_with_perfect_router(tmp_path: Path) -> None:
    reports = run_tier1(PLUGIN, _oracle(PLUGIN), runs=1, workdir=tmp_path)
    assert {r.skill for r in reports} == ON_LISTING
    assert all_passed(reports), [r.summary_line() for r in reports if not r.passed]


def test_run_tier1_subset_and_bad_router(tmp_path: Path) -> None:
    def always_none(system: str, prompt: str, workdir: Path) -> str:
        return "none"

    reports = run_tier1(PLUGIN, always_none, skills=["research"], runs=1, workdir=tmp_path)
    assert [r.skill for r in reports] == ["research"]
    assert not reports[0].passed  # recall collapses to 0


def test_run_tier1_rejects_nonpositive_runs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="runs must be"):
        run_tier1(PLUGIN, _oracle(PLUGIN), runs=0, workdir=tmp_path)


# --- check_wiring ------------------------------------------------------------


def test_check_wiring_clean_on_real_plugin() -> None:
    assert check_wiring(PLUGIN) == []


def _write_skill(root: Path, name: str, frontmatter: str, evals: str) -> None:
    d = root / "skills" / name
    (d / "evals").mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n# {name}\n", encoding="utf-8")
    (d / "evals" / "evals.json").write_text(evals, encoding="utf-8")


def test_check_wiring_reports_problems(tmp_path: Path) -> None:
    # An off-listing skill that nonetheless declares tier1_trigger and has no trigger prompts.
    _write_skill(
        tmp_path,
        "bad",
        "name: bad\ndescription: \ndisable-model-invocation: true",
        '{"skill_name":"bad","evals":[],"component":{"id":"bad","type":"skill","purpose":"p"},'
        '"thresholds":{"tier1_trigger":{"recall":0.9,"specificity":0.9}}}',
    )
    problems = check_wiring(tmp_path)
    assert any("live listing is empty" in p for p in problems)  # off-listing -> nothing to route
    assert any("off-listing" in p for p in problems)
    assert any("no should_trigger" in p for p in problems)
    assert any("no should_not_trigger" in p for p in problems)


def test_check_wiring_flags_empty_description(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "thin",
        "name: thin\ndescription: ",
        '{"skill_name":"thin","evals":[],"component":{"id":"thin","type":"skill","purpose":"p"},'
        '"thresholds":{"tier2_quality":{"min_pass_rate":0.8,"runs":5}}}',
    )
    assert any("empty description" in p for p in check_wiring(tmp_path))


def test_all_passed_empty_is_false() -> None:
    assert all_passed([]) is False


def test_loaders_skip_incomplete_skill_dirs(tmp_path: Path) -> None:
    # load_triggers on a path with no skills/ dir.
    assert load_triggers(tmp_path) == []
    # A dir with no SKILL.md is skipped by load_listing; a dir with no evals.json by load_triggers.
    (tmp_path / "skills" / "empty").mkdir(parents=True)
    (tmp_path / "skills" / "noevals").mkdir(parents=True)
    (tmp_path / "skills" / "noevals" / "SKILL.md").write_text(
        "---\nname: noevals\ndescription: d\n---\n# x\n", encoding="utf-8"
    )
    assert {c.name for c in load_listing(tmp_path)} == {"noevals"}  # 'empty' skipped (no SKILL.md)
    assert load_triggers(tmp_path) == []  # neither has evals.json


def test_check_wiring_flags_tier1_skill_absent_from_listing(tmp_path: Path) -> None:
    # On-listing SKILL.md but its evals skill_name doesn't match -> declared tier1 not routable.
    _write_skill(
        tmp_path,
        "foo",
        "name: foo\ndescription: d",
        '{"skill_name":"bar","evals":[],"component":{"id":"bar","type":"skill","purpose":"p"},'
        '"thresholds":{"tier1_trigger":{"recall":0.9,"specificity":0.9}},'
        '"triggers":{"should_trigger":["x"],"should_not_trigger":["y"]}}',
    )
    assert any("not in the live listing" in p for p in check_wiring(tmp_path))


# A tier1_trigger block with no recall/specificity values would pass vacuously (gate skips a
# None target) — guard against that latent false-pass in both the dry check and the live run.
_INCOMPLETE_THRESHOLD = (
    '{"skill_name":"research","evals":[],'
    '"component":{"id":"research","type":"skill","purpose":"p"},'
    '"thresholds":{"tier1_trigger":{}},'
    '"triggers":{"should_trigger":["a"],"should_not_trigger":["b"]}}'
)


def test_check_wiring_flags_incomplete_threshold(tmp_path: Path) -> None:
    _write_skill(tmp_path, "research", "name: research\ndescription: d", _INCOMPLETE_THRESHOLD)
    problems = check_wiring(tmp_path)
    assert any("recall/specificity threshold" in p for p in problems)
    assert not any("no should_trigger" in p for p in problems)  # otherwise clean


def test_run_tier1_refuses_miswired_plugin(tmp_path: Path) -> None:
    _write_skill(tmp_path, "research", "name: research\ndescription: d", _INCOMPLETE_THRESHOLD)

    def run(system: str, prompt: str, workdir: Path) -> str:  # pragma: no cover - never called
        return "research"

    with pytest.raises(ValueError, match="wiring problems"):
        run_tier1(tmp_path, run, runs=1, workdir=tmp_path)
