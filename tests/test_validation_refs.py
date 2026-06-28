from __future__ import annotations

from pathlib import Path

from agentic_forge.validation import Report, _check_refs, validate_plugin


def test_check_refs_relative_links(tmp_path: Path) -> None:
    base = tmp_path / "skills" / "s"
    base.mkdir(parents=True)
    (tmp_path / "target.md").write_text("ok", encoding="utf-8")  # ../../target.md from skills/s
    report = Report()
    _check_refs("[ok](../../target.md) and [bad](../../nope.md)", base, "s/SKILL.md", report)
    messages = [i.message for i in report.errors]
    assert len(messages) == 1 and "nope.md" in messages[0]  # only the missing one errors


def test_check_refs_local_and_anchor(tmp_path: Path) -> None:
    base = tmp_path / "skills" / "s"
    (base / "references").mkdir(parents=True)
    (base / "references" / "r.md").write_text("ok", encoding="utf-8")
    report = Report()
    # a resolving references/ link with an #anchor, plus a missing one
    _check_refs("[a](references/r.md#sec) [b](references/missing.md)", base, "s", report)
    messages = [i.message for i in report.errors]
    assert len(messages) == 1 and "missing.md" in messages[0]


def test_validate_plugin_runs_contract_guards(tmp_path: Path) -> None:
    # a present-but-noncompliant `product` skill (also a spine phase): body omits the prd field
    # `goals` and never links the recall pattern -> both wired guards fire (covers the wiring).
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "x", "version": "0"}', encoding="utf-8"
    )
    sk = tmp_path / "skills" / "product"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "---\nname: product\ndescription: d\n---\n"
        "Produce prd.md (frontmatter `feature`, `status`, `acceptance`).\n",
        encoding="utf-8",
    )
    report = validate_plugin(tmp_path)
    assert any(i.location == "skill-contract" and "goals" in i.message for i in report.errors)
    assert any(i.location == "knowledge-recall" for i in report.errors)


def test_validate_plugin_clean_on_partial_plugin(tmp_path: Path) -> None:
    # a manifest-only plugin (no skills) must not trip the contract guards (they scope to present
    # skills) — only the absence of a manifest/skills is the validator's concern elsewhere.
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "x", "version": "0"}', encoding="utf-8"
    )
    report = validate_plugin(tmp_path)
    locations = {i.location for i in report.errors}
    assert "skill-contract" not in locations and "knowledge-recall" not in locations
