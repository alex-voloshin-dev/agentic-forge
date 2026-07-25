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
        ("", "invalid"),  # empty reply is NOT a "no skill fits" decision — no answer at all
        ("definitely no skill", "invalid"),  # 'no' is not 'none', and nothing known is named
        ("I'd use product, or maybe plan", "product"),  # first-mentioned wins
        ("skill-factory", "skill-factory"),
    ],
)
def test_parse_selection(reply: str, expected: str) -> None:
    names = sorted(ON_LISTING)
    assert parse_selection(reply, names) == expected


def test_parse_selection_rejects_prose_instead_of_mining_it(tmp_path: Path) -> None:
    # THE bug this guards (ADR 0064): an off-format reply — the model answering some other
    # question at length — used to be scanned for the first skill-like word and scored as a
    # routing decision, silently turning "never answered" into "chose knowledge".
    prose = (
        "Both explorations agreed: docs/ and the repository root are outside this session's "
        "sandbox, so I could not confirm the roadmap or the ADR index by reading them. "
        "Based on the knowledge I have, here is a summary of what the repository contains "
        "and what I would recommend doing next about it."
    )
    assert parse_selection(prose, sorted(ON_LISTING)) == "invalid"


def test_parse_selection_allows_a_short_wrapped_answer() -> None:
    # The cap must not reject a legitimately terse-but-not-bare reply.
    assert parse_selection("The answer is: `research`.", sorted(ON_LISTING)) == "research"


def test_selection_rate_is_fraction_for_target(tmp_path: Path) -> None:
    replies = iter(["research", "product", "research"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return next(replies)

    got = selection_rate(run, "sys", "p", ["research", "product"], 3, tmp_path, target="research")
    assert abs((got.rate or 0) - 2 / 3) < 1e-9
    assert got.invalid == 0 and got.runs == 3


def test_selection_rate_excludes_invalid_calls_from_the_denominator(tmp_path: Path) -> None:
    # 1 hit + 1 real miss + 1 non-answer -> 1/2, not 1/3. A call that produced no decision is
    # missing data; averaging it in as a miss understates recall (ADR 0064).
    replies = iter(["research", "product", "a" * 5 + " long prose reply that answers nothing here"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return next(replies)

    got = selection_rate(run, "sys", "p", ["research", "product"], 3, tmp_path, target="research")
    assert got.rate == 0.5 and got.invalid == 1


def test_selection_rate_all_invalid_is_unmeasured_not_zero(tmp_path: Path) -> None:
    # Reporting 0.0 here would fabricate a routing failure out of a measurement failure.
    def run(system: str, prompt: str, workdir: Path) -> str:
        return ""

    got = selection_rate(run, "sys", "p", ["research"], 3, tmp_path, target="research")
    assert got.rate is None and got.invalid == 3


# --- eval_skill --------------------------------------------------------------

_THRESH = {"tier1_trigger": {"recall": 0.9, "specificity": 0.9}}


def test_eval_skill_perfect(tmp_path: Path) -> None:
    trig = SkillTrigger("research", _THRESH, ["a", "b"], ["c", "d"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        return "research" if prompt in ("a", "b") else "none"

    rep = eval_skill(trig, ["research", "product"], run, "sys", 1, tmp_path)
    assert rep.recall == 1.0 and rep.specificity == 1.0 and rep.passed
    assert "PASS" in rep.summary_line()


def test_eval_skill_unmeasured_prompt_fails_and_is_named(tmp_path: Path) -> None:
    # Every call for prompt "b" is a non-answer. The gate must NOT pass (we did not measure it)
    # and must NOT report it as a 0.0 routing failure either — it says the prompt is unmeasured.
    trig = SkillTrigger("research", _THRESH, ["a", "b"], ["c"])

    def run(system: str, prompt: str, workdir: Path) -> str:
        if prompt == "b":
            return "this reply is a long piece of prose that answers an entirely different question"
        return "research" if prompt == "a" else "none"

    rep = eval_skill(trig, ["research", "product"], run, "sys", 2, tmp_path)
    assert rep.passed is False
    assert rep.unmeasured == ["b"]
    assert any("unmeasured" in r for r in rep.reasons)
    assert rep.recall == 1.0  # computed from the prompts that DID answer, not dragged to 0.5
    assert rep.invalid_calls == 2 and rep.total_calls == 6


def test_eval_skill_reports_discarded_calls_even_when_passing(tmp_path: Path) -> None:
    # A green number computed from half the samples is weaker evidence — the line must say so.
    trig = SkillTrigger("research", _THRESH, ["a"], ["c"])
    seen: dict[str, int] = {}

    def run(system: str, prompt: str, workdir: Path) -> str:
        seen[prompt] = seen.get(prompt, 0) + 1
        if seen[prompt] == 1:
            return "a long prose reply that does not answer the routing question being asked here"
        return "research" if prompt == "a" else "none"

    rep = eval_skill(trig, ["research", "product"], run, "sys", 2, tmp_path)
    assert rep.passed is True and rep.invalid_calls == 2
    assert "no decision" in rep.summary_line()


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
