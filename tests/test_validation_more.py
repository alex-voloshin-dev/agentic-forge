from __future__ import annotations

import json
from pathlib import Path

from agentic_forge.validation import (
    LISTING_BUDGET_CHARS,
    Issue,
    Report,
    budget_line,
    listing_budget,
    validate_agent,
    validate_listing_budget,
    validate_manifest,
    validate_plugin,
    validate_python_compat,
    validate_skill,
)

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"

AGENT_EVALS = {
    "skill_name": "foo",
    "evals": [{"id": 1, "prompt": "do the thing", "assertions": ["it did"]}],
    "component": {"id": "foo", "type": "agent", "purpose": "A test agent."},
    "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
}


def _make_agent(
    tmp_path: Path,
    name: str = "foo",
    *,
    frontmatter: str | None = None,
    with_evals: bool = True,
    evals: dict | None = None,
) -> Path:
    agents = tmp_path / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    if frontmatter is None:
        frontmatter = f"name: {name}\ndescription: A test subagent role.\nmodel: inherit"
    md = agents / f"{name}.md"
    md.write_text(f"---\n{frontmatter}\n---\nYou are a test agent.\n", encoding="utf-8")
    if with_evals:
        evals_dir = agents / "evals"
        evals_dir.mkdir(exist_ok=True)
        (evals_dir / f"{name}.evals.json").write_text(
            json.dumps(evals or AGENT_EVALS), encoding="utf-8"
        )
    return md


# --- validate_agent ---

def test_agent_valid(tmp_path) -> None:
    md = _make_agent(tmp_path)
    report = validate_agent(md)
    assert report.ok, report.render()


def test_agent_missing_evals(tmp_path) -> None:
    md = _make_agent(tmp_path, with_evals=False)
    report = validate_agent(md)
    assert any("eval contract" in i.message for i in report.errors)


def test_agent_missing_description(tmp_path) -> None:
    md = _make_agent(tmp_path, frontmatter="name: foo")
    report = validate_agent(md)
    assert any("description" in i.message for i in report.errors)


def test_agent_wrong_component_type(tmp_path) -> None:
    bad = {**AGENT_EVALS, "component": {"id": "foo", "type": "skill", "purpose": "p"}}
    md = _make_agent(tmp_path, evals=bad)
    report = validate_agent(md)
    assert any("component.type must be 'agent'" in i.message for i in report.errors)


def test_agent_bad_file_name(tmp_path) -> None:
    md = _make_agent(tmp_path, name="Bad")  # uppercase invalid
    report = validate_agent(md)
    assert any("file name" in i.message for i in report.errors)


def test_agent_without_name_frontmatter_is_ok(tmp_path) -> None:
    # no `name` in frontmatter -> name defaults to the filename; the name check is skipped, not an
    # error (covers the `if fm_name:` false branch in validate_agent).
    md = _make_agent(tmp_path, frontmatter="description: A role.")
    report = validate_agent(md)
    assert not any(i.message.startswith("name:") for i in report.errors)


def test_agent_model_drift_errors(tmp_path) -> None:
    # model frontmatter != the validated tier policy (foo -> default -> inherit) -> Tier-0 error
    md = _make_agent(
        tmp_path, frontmatter="name: foo\ndescription: A role.\nmodel: claude-opus-4-8"
    )
    report = validate_agent(md)
    assert any("validated tier policy" in i.message for i in report.errors)


def test_agent_missing_model_errors(tmp_path) -> None:
    md = _make_agent(tmp_path, frontmatter="name: foo\ndescription: A role.")  # no model: line
    report = validate_agent(md)
    assert any("missing 'model'" in i.message for i in report.errors)


def test_agent_malformed_frontmatter(tmp_path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    md = agents / "foo.md"
    md.write_text("no frontmatter here", encoding="utf-8")
    report = validate_agent(md)
    assert not report.ok


# --- validate_skill error branches + Report rendering ---

def _make_skill(tmp_path: Path, body: str, *, evals: str | None = "valid") -> Path:
    d = tmp_path / "skills" / "s"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    if evals in ("valid", "bad"):
        ed = d / "evals"
        ed.mkdir()
        content = (
            "{bad json"
            if evals == "bad"
            else json.dumps(
                {
                    "skill_name": "s",
                    "evals": [{"id": 1, "prompt": "p", "assertions": ["a"]}],
                    "component": {"id": "s", "type": "skill", "purpose": "p"},
                    "thresholds": {"tier2_quality": {"min_pass_rate": 0.8, "runs": 5}},
                }
            )
        )
        (ed / "evals.json").write_text(content, encoding="utf-8")
    return d


def test_skill_malformed_frontmatter(tmp_path) -> None:
    # the skill-side FrontmatterError branch (twin of the agent test above)
    report = validate_skill(_make_skill(tmp_path, "no frontmatter here", evals=None))
    assert not report.ok


def test_skill_malformed_evals_json(tmp_path) -> None:
    # the skill-side EvalsError branch in _check_evals
    body = "---\nname: s\ndescription: A test skill.\n---\nBody.\n"
    report = validate_skill(_make_skill(tmp_path, body, evals="bad"))
    assert not report.ok


def test_report_render_and_issue_str() -> None:
    report = Report()
    report.error("loc", "boom")
    rendered = report.render()
    assert "ERROR" in rendered and "boom" in rendered and "1 error" in rendered
    assert str(Issue("warning", "l", "m")) == "[WARNING] l: m"


# --- validate_manifest ---

def test_manifest_missing(tmp_path) -> None:
    report = validate_manifest(tmp_path)
    assert any("plugin.json" in i.message for i in report.errors)


def test_manifest_bad_json(tmp_path) -> None:
    d = tmp_path / ".claude-plugin"
    d.mkdir()
    (d / "plugin.json").write_text("{not json", encoding="utf-8")
    report = validate_manifest(tmp_path)
    assert any("invalid JSON" in i.message for i in report.errors)


def test_manifest_missing_keys(tmp_path) -> None:
    d = tmp_path / ".claude-plugin"
    d.mkdir()
    (d / "plugin.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    report = validate_manifest(tmp_path)
    assert any("version" in i.message for i in report.errors)


def test_manifest_valid(tmp_path) -> None:
    d = tmp_path / ".claude-plugin"
    d.mkdir()
    (d / "plugin.json").write_text(json.dumps({"name": "x", "version": "1"}), encoding="utf-8")
    report = validate_manifest(tmp_path)
    assert report.ok


# --- validate_plugin end to end ---

def test_validate_plugin_aggregates(tmp_path) -> None:
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "p", "version": "0"}), encoding="utf-8"
    )
    _make_agent(plugin, name="foo")
    report = validate_plugin(plugin)
    assert report.ok, report.render()


# --- validate_python_compat (py3.9 hook-path safety, ADR 0050/0054 review) ---


def test_python_compat_flags_runtime_files_without_future_import(tmp_path) -> None:
    plugin = tmp_path / "plugin"
    (plugin / "lib").mkdir(parents=True)
    (plugin / "hooks" / "scripts").mkdir(parents=True)
    (plugin / "lib" / "ok.py").write_text(
        "from __future__ import annotations\nx: int | None = None\n", encoding="utf-8"
    )
    (plugin / "hooks" / "scripts" / "bad.py").write_text("def f(x: int | None): ...\n")
    report = validate_python_compat(plugin)
    assert not report.ok
    assert any("hooks/scripts/bad.py" in i.location for i in report.errors)
    assert not any("ok.py" in i.location for i in report.errors)


def test_python_compat_exempts_fixtures_and_empty_files(tmp_path) -> None:
    plugin = tmp_path / "plugin"
    (plugin / "lib").mkdir(parents=True)
    (plugin / "eval" / "fixtures").mkdir(parents=True)
    (plugin / "skills" / "s" / "scripts").mkdir(parents=True)
    (plugin / "lib" / "__init__.py").write_text("", encoding="utf-8")  # empty -> exempt
    (plugin / "eval" / "fixtures" / "subject.py").write_text("x=1\n")  # fixture -> exempt
    (plugin / "skills" / "s" / "scripts" / "run.py").write_text("x=1\n")  # shipped -> flagged
    report = validate_python_compat(plugin)
    assert [i for i in report.errors if "subject.py" in i.location] == []
    assert any("skills/s/scripts/run.py" in i.location for i in report.errors)


def test_real_plugin_is_python_compat_clean() -> None:
    # the actual shipped tree must stay importable on a user's bare python3 (3.9)
    plugin = Path(__file__).resolve().parents[1] / "plugin"
    report = validate_python_compat(plugin)
    assert report.ok, report.render()


# --- the always-on listing budget (ADR 0095) --------------------------------------------


def _plugin_with_listing(root: Path, skills: dict[str, tuple[str, bool]]) -> Path:
    """A plugin dir whose skills are {name: (description, off_listing)}."""
    for name, (description, off_listing) in skills.items():
        skill = root / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        extra = "\ndisable-model-invocation: true" if off_listing else ""
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}{extra}\n---\nBody\n",
            encoding="utf-8",
        )
    return root


def test_listing_budget_measures_the_rendered_listing_and_skips_off_listing(
    tmp_path: Path,
) -> None:
    plugin = _plugin_with_listing(
        tmp_path,
        {"plan": ("Plan the work.", False), "python-patterns": ("Python conventions.", True)},
    )
    total, rows = listing_budget(plugin)
    assert [name for name, _ in rows] == ["plan"]  # the off-listing pack costs no context
    assert total == len("- agentic-forge:plan: Plan the work.") == rows[0][1]


def test_listing_budget_is_a_ratchet_that_fails_growth(tmp_path: Path) -> None:
    """A new on-listing skill (~600 chars) trips it; the message says where to trim and that the
    constant itself is the budget review."""
    fat = "x" * (LISTING_BUDGET_CHARS // 2)
    plugin = _plugin_with_listing(tmp_path, {"a": (fat, False), "b": (fat, False)})
    report = validate_listing_budget(plugin)
    assert not report.ok
    (issue,) = report.errors
    assert "over a budget of" in issue.message and "LISTING_BUDGET_CHARS" in issue.message
    assert "a (" in issue.message  # the longest descriptions are named
    assert validate_listing_budget(_plugin_with_listing(tmp_path / "small", {})).ok


def test_the_shipped_listing_is_within_its_recorded_budget() -> None:
    """The ratchet's own self-test: this is the number CLAUDE.md carried by hand for two years."""
    total, rows = listing_budget(PLUGIN)
    assert 0 < total <= LISTING_BUDGET_CHARS, f"{total} chars over {LISTING_BUDGET_CHARS}"
    assert len(rows) == 17  # the on-listing set; growing it is a deliberate budget review
    assert validate_plugin(PLUGIN).ok


def test_budget_line_is_printed_pass_or_fail() -> None:
    line = budget_line(PLUGIN)
    assert line.startswith("listing budget: ") and "on-listing skills)" in line
