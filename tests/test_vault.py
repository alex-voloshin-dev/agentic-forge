from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_forge import vault
from agentic_forge.vault import (
    ROOT_MOC,
    add_note,
    load_vault,
    parse_links,
    recall,
    scaffold,
    session_summary,
    validate_vault,
    vault_path,
    wikilink,
)

# --- pure helpers ------------------------------------------------------------


def test_vault_path() -> None:
    assert vault_path("/repo") == Path("/repo/docs/knowledge")


def test_wikilink() -> None:
    assert wikilink("foo") == "[[foo]]"
    assert wikilink("foo", "Foo Title") == "[[foo|Foo Title]]"


def test_parse_links_forms_and_dedup() -> None:
    text = "see [[a]], [[b|Bee]], [[c#heading]], [[c#h|alias]] and [[a]] again; not [single]."
    assert parse_links(text) == ["a", "b", "c"]  # aliases/anchors stripped, deduped, ordered


def test_parse_links_none() -> None:
    assert parse_links("no links here, [[]] is empty") == []


def test_parse_links_ignores_multiline() -> None:
    assert parse_links("stray [[also\nbad]] across lines") == []  # wikilinks are single-line


# --- load_vault --------------------------------------------------------------


def test_load_vault_absent_is_empty(tmp_path: Path) -> None:
    v = load_vault(tmp_path)
    assert v.notes == {} and v.repo == tmp_path


def test_load_vault_parses_notes(tmp_path: Path) -> None:
    add_note(tmp_path, "alpha", "Alpha", "Links to [[beta]].", tags=("x", "y"))
    add_note(tmp_path, "beta", "Beta", "Plain note.")
    v = load_vault(tmp_path)
    assert set(v.notes) == {"moc", "alpha", "beta"}
    alpha = v.notes["alpha"]
    assert alpha.title == "Alpha" and alpha.type == "note" and alpha.tags == ("x", "y")
    assert alpha.links == ("beta",)


def test_load_vault_title_defaults_to_name(tmp_path: Path) -> None:
    scaffold(tmp_path)
    (vault_path(tmp_path) / "bare.md").write_text("no frontmatter body", encoding="utf-8")
    assert load_vault(tmp_path).notes["bare"].title == "bare"


# --- validate_vault ----------------------------------------------------------


def test_validate_absent_vault(tmp_path: Path) -> None:
    assert validate_vault(tmp_path) == ["vault not found at docs/knowledge/"]


def test_validate_scaffold_is_healthy(tmp_path: Path) -> None:
    scaffold(tmp_path)
    assert validate_vault(tmp_path) == []  # root MOC alone, no broken links, no orphans


def test_validate_linked_notes_healthy(tmp_path: Path) -> None:
    add_note(tmp_path, "alpha", "Alpha", "See [[beta]].")
    add_note(tmp_path, "beta", "Beta", "End.")  # linked from MOC by add_note
    assert validate_vault(tmp_path) == []


def test_validate_broken_link(tmp_path: Path) -> None:
    add_note(tmp_path, "alpha", "Alpha", "Points at [[ghost]].")
    problems = validate_vault(tmp_path)
    assert any("broken wikilink [[ghost]]" in p for p in problems)


def test_validate_orphan(tmp_path: Path) -> None:
    scaffold(tmp_path)
    # written directly, not linked from any note/MOC -> orphan
    (vault_path(tmp_path) / "lonely.md").write_text(
        "---\ntitle: Lonely\ntype: note\ntags: []\n---\n# Lonely\n", encoding="utf-8"
    )
    assert any("lonely: orphan" in p for p in validate_vault(tmp_path))


def test_validate_self_link_does_not_mask_orphan(tmp_path: Path) -> None:
    scaffold(tmp_path)
    # a note whose ONLY inbound link is its own self-reference is still an orphan
    (vault_path(tmp_path) / "island.md").write_text(
        "---\ntitle: Island\ntype: note\ntags: []\n---\n# Island\n\nSee [[island]].\n",
        encoding="utf-8",
    )
    assert any("island: orphan" in p for p in validate_vault(tmp_path))


def test_validate_missing_root_moc(tmp_path: Path) -> None:
    vp = vault_path(tmp_path)
    vp.mkdir(parents=True)
    (vp / "note.md").write_text("---\ntitle: N\ntype: note\ntags: []\n---\n# N\n", encoding="utf-8")
    assert any("missing root MOC" in p for p in validate_vault(tmp_path))


# --- scaffold ----------------------------------------------------------------


def test_scaffold_creates_and_is_idempotent(tmp_path: Path) -> None:
    vp = scaffold(tmp_path)
    assert (vp / f"{ROOT_MOC}.md").is_file() and (vp / "README.md").is_file()
    (vp / f"{ROOT_MOC}.md").write_text("MARKER", encoding="utf-8")  # user edit
    scaffold(tmp_path)  # must not clobber
    assert (vp / f"{ROOT_MOC}.md").read_text(encoding="utf-8") == "MARKER"


# --- add_note ----------------------------------------------------------------


def test_add_note_writes_and_links_moc(tmp_path: Path) -> None:
    path = add_note(tmp_path, "decision-x", "Decision X", "We chose X because Y.", tags=("adr",))
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "title: Decision X" in text and "tags: [adr]" in text and "We chose X" in text
    moc = (vault_path(tmp_path) / f"{ROOT_MOC}.md").read_text(encoding="utf-8")
    assert "[[decision-x|Decision X]]" in moc


def test_add_note_link_is_idempotent(tmp_path: Path) -> None:
    add_note(tmp_path, "n", "N", "body")
    add_note(tmp_path, "n", "N", "body v2")  # re-capture
    moc = (vault_path(tmp_path) / f"{ROOT_MOC}.md").read_text(encoding="utf-8")
    assert moc.count("[[n|") == 1  # not double-listed
    assert "body v2" in (vault_path(tmp_path) / "n.md").read_text(encoding="utf-8")


def test_add_note_without_moc(tmp_path: Path) -> None:
    add_note(tmp_path, "free", "Free", "unlinked", moc=None)
    moc = (vault_path(tmp_path) / f"{ROOT_MOC}.md").read_text(encoding="utf-8")
    assert "[[free" not in moc


def test_add_note_custom_moc_is_created(tmp_path: Path) -> None:
    add_note(tmp_path, "n", "N", "body", moc="themes")  # themes.md does not exist yet
    themes = (vault_path(tmp_path) / "themes.md").read_text(encoding="utf-8")
    assert "type: moc" in themes and "[[n|N]]" in themes
    root = (vault_path(tmp_path) / f"{ROOT_MOC}.md").read_text(encoding="utf-8")
    assert "[[themes]]" in root  # themed MOC reachable from the root MOC
    assert validate_vault(tmp_path) == []  # so it is not an orphan


def test_add_note_two_notes_one_themed_moc_stays_valid(tmp_path: Path) -> None:
    add_note(tmp_path, "a", "A", "x", moc="testing")
    add_note(tmp_path, "b", "B", "y", moc="testing")
    root = (vault_path(tmp_path) / f"{ROOT_MOC}.md").read_text(encoding="utf-8")
    assert root.count("[[testing]]") == 1  # root links the themed MOC exactly once
    testing = (vault_path(tmp_path) / "testing.md").read_text(encoding="utf-8")
    assert "[[a|A]]" in testing and "[[b|B]]" in testing
    assert validate_vault(tmp_path) == []


# --- recall ------------------------------------------------------------------


def test_recall_ranks_by_overlap(tmp_path: Path) -> None:
    add_note(
        tmp_path, "priorities", "Task priorities", "ordering tasks by priority", tags=("tasks",)
    )
    add_note(tmp_path, "search", "Full-text search", "indexing and querying documents")
    ranked = recall(tmp_path, "how do we order tasks by priority?")
    assert ranked and ranked[0][0] == "priorities"
    assert "search" not in [name for name, _ in ranked]  # no token overlap


def test_recall_empty_query(tmp_path: Path) -> None:
    add_note(tmp_path, "a", "A", "body")
    assert recall(tmp_path, "the and of") == []  # all stopwords -> no tokens


def test_recall_weights_title_over_body(tmp_path: Path) -> None:
    # a title/tag hit weighs 3x a body hit — assert the EXACT scores so a 1.0-weight mutation fails
    # (ordering alone wouldn't catch it: alphabetical tie-break keeps "atitle" first either way).
    add_note(tmp_path, "atitle", "Priority Handling", "general notes here")
    add_note(tmp_path, "bbody", "Misc Notes", "this mentions priority once")
    ranked = dict(recall(tmp_path, "priority"))
    # add_note repeats the title as the body H1, so a title word scores 3 (frontmatter title) + 1
    # (body) = 4.0; a body-only word scores 1.0. A 1.0-weight mutation would make atitle 2.0.
    assert ranked["atitle"] == 4.0
    assert ranked["bbody"] == 1.0


def test_recall_no_overlap_returns_empty(tmp_path: Path) -> None:
    # tokens present but nothing matches -> [] (guards the `if score > 0` filter)
    add_note(tmp_path, "n", "Alpha", "body text")
    assert recall(tmp_path, "zzzznomatch") == []


# --- session_summary ---------------------------------------------------------


def test_session_summary_no_vault(tmp_path: Path) -> None:
    assert session_summary(tmp_path) == ""


def test_session_summary_empty_vault(tmp_path: Path) -> None:
    vault_path(tmp_path).mkdir(parents=True)  # dir but no notes
    assert session_summary(tmp_path) == ""


def test_session_summary_lists_map_and_key_notes(tmp_path: Path) -> None:
    add_note(tmp_path, "central", "Central idea", "the hub")
    add_note(tmp_path, "spoke", "A spoke", "links to [[central]]")
    summary = session_summary(tmp_path)
    assert "Project knowledge" in summary
    assert "[[MOC]]" in summary  # the root map
    assert "[[central]] — Central idea" in summary  # highest in-degree note listed


def test_session_summary_only_root_moc(tmp_path: Path) -> None:
    scaffold(tmp_path)  # root MOC only, no other notes
    summary = session_summary(tmp_path)
    assert "[[MOC]]" in summary and "Key notes:" not in summary


def test_session_summary_no_root_moc(tmp_path: Path) -> None:
    vp = vault_path(tmp_path)
    vp.mkdir(parents=True)
    (vp / "solo.md").write_text(
        "---\ntitle: Solo\ntype: note\ntags: []\n---\n# Solo\n", encoding="utf-8"
    )
    summary = session_summary(tmp_path)
    assert "Map:" not in summary  # no root MOC -> no Map line
    assert "[[solo]] — Solo" in summary


def test_module_exports() -> None:
    for name in vault.__all__:
        assert hasattr(vault, name)


# --- the skills' documented calls, as written, in processes of their own -----------------------

_REPO = Path(__file__).resolve().parents[1]
_SKILLS_USING_THE_VAULT = ("knowledge", "repo-onboarding")
# The bytes 2026.11.1 wrote, plus a note someone wrote by hand and linked from a map.
_VAULT_FROM_BEFORE = {
    "MOC.md": (
        "---\ntitle: Knowledge Map\ntype: moc\ntags: [moc]\n---\n\n# Knowledge Map\n\n"
        "The map-of-content for this project's knowledge vault. Link notes here under themes.\n\n"
        "## Notes\n- [[decisions]]\n"
    ),
    "README.md": (
        "# Knowledge vault\n\nObsidian-format project knowledge maintained by agentic-forge's "
        "`knowledge` skill: atomic notes (`*.md` with `[[wikilinks]]`), maps-of-content "
        "(`type: moc`), entry point `MOC.md`.\n"
    ),
    "decisions.md": (
        "---\ntitle: Decisions\ntype: moc\ntags: [moc]\n---\n\n# Decisions\n\n## Notes\n"
        "- [[use-sqlite|Use SQLite]]\n- [[by-hand]]\n"
    ),
    "use-sqlite.md": (
        "---\ntitle: Use SQLite\ntype: note\ntags: [decision]\n---\n\n# Use SQLite\n\n"
        "We chose SQLite because it is one file.\n"
    ),
    "by-hand.md": "No frontmatter on this one. See [[use-sqlite]].\n",
}


def _documented_call(skill: str) -> str:
    """The one line the skill tells a model to run. Read from the skill, so a test cannot go on
    passing for a call that the skill no longer documents."""
    text = (_REPO / "plugin" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    found = re.findall(r'^python -c "(.+)"$', text, flags=re.MULTILINE)
    assert len(found) == 1, found
    return found[0]


def _python(code: str, repo: Path) -> subprocess.CompletedProcess[str]:
    """``python -c`` in the repo. The interpreter and the import path are the two things the skills
    leave to the installation; everything else is as written."""
    env = {**os.environ, "PYTHONPATH": str(_REPO / "plugin" / "lib")}
    return subprocess.run(
        [sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


def _vault_call(body: str, repo: Path) -> str:
    result = _python(f"from agentic_forge import vault; {body}", repo)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _session_context(repo: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(_REPO / "plugin" / "hooks" / "scripts" / "session_start.py")],
        input=json.dumps({"cwd": str(repo), "session_id": "s1"}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("skill", _SKILLS_USING_THE_VAULT)
def test_the_documented_call_on_a_fresh_repo(tmp_path: Path, skill: str) -> None:
    """The knowledge skill's recall path: nothing there, scaffold it, capture, check."""
    call = _documented_call(skill)
    first = _python(call, tmp_path)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == str(["vault not found at docs/knowledge/"])
    assert list(tmp_path.iterdir()) == []  # asking creates nothing

    _vault_call("vault.scaffold('.')", tmp_path)
    assert _python(call, tmp_path).stdout.strip() == "[]"
    _vault_call(
        "vault.add_note('.', 'use-sqlite', 'Use SQLite', 'It is one file.', "
        "tags=('decision',), moc='decisions')",
        tmp_path,
    )
    assert _python(call, tmp_path).stdout.strip() == "[]"
    assert "use-sqlite" in _vault_call("print(vault.recall('.', 'sqlite'))", tmp_path)
    assert "[[use-sqlite]] — Use SQLite" in _session_context(tmp_path)
    vpath = tmp_path / "docs" / "knowledge"
    assert sorted(p.name for p in vpath.iterdir()) == [
        "MOC.md", "README.md", "decisions.md", "use-sqlite.md",
    ]


@pytest.mark.parametrize("skill", _SKILLS_USING_THE_VAULT)
def test_the_documented_call_on_a_vault_from_the_last_release(tmp_path: Path, skill: str) -> None:
    """Capturing into an existing vault changes what it must and no more: the map gains one line,
    every other file keeps its bytes, and a mode someone chose stays."""
    vpath = tmp_path / "docs" / "knowledge"
    vpath.mkdir(parents=True)
    for name, text in _VAULT_FROM_BEFORE.items():
        (vpath / name).write_text(text, encoding="utf-8")
    (vpath / "decisions.md").chmod(0o664)

    call = _documented_call(skill)
    assert _python(call, tmp_path).stdout.strip() == "[]"
    assert "[[use-sqlite]] — Use SQLite" in _session_context(tmp_path)
    assert "use-sqlite" in _vault_call("print(vault.recall('.', 'sqlite'))", tmp_path)

    add = "vault.add_note('.', 'next', 'Next', 'See [[use-sqlite]].', tags=('x',), moc='decisions')"
    _vault_call(add, tmp_path)
    _vault_call(add, tmp_path)  # capturing the same note again adds no second link
    assert _python(call, tmp_path).stdout.strip() == "[]"
    expected = dict(_VAULT_FROM_BEFORE)
    expected["decisions.md"] += "- [[next|Next]]\n"
    written = {p.name: p.read_text(encoding="utf-8") for p in vpath.iterdir()}
    del written["next.md"]
    assert written == expected
    assert (vpath / "next.md").read_text(encoding="utf-8").startswith("---\ntitle: Next\n")
    assert (vpath / "decisions.md").stat().st_mode & 0o777 == 0o664


@pytest.mark.parametrize("skill", _SKILLS_USING_THE_VAULT)
def test_the_documented_call_on_a_vault_kept_elsewhere(tmp_path: Path, skill: str) -> None:
    """The upgrade of someone who keeps the vault outside the repo: told the remedy by the call the
    skill makes, nothing changed out there, and the setting brings everything back."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for name, text in _VAULT_FROM_BEFORE.items():
        (elsewhere / name).write_text(text, encoding="utf-8")
    (repo / "docs" / "knowledge").symlink_to(elsewhere, target_is_directory=True)

    call = _documented_call(skill)
    told = _python(call, repo)
    assert told.returncode == 0 and "knowledge.allow_external_vault" in told.stdout
    add = "vault.add_note('.', 'next', 'Next', 'Body.', moc='decisions')"
    refused = _python(f"from agentic_forge import vault; {add}", repo)
    assert refused.returncode != 0
    assert "StateWriteRefused" in refused.stderr
    assert "knowledge.allow_external_vault" in refused.stderr
    assert sorted(p.name for p in elsewhere.iterdir()) == sorted(_VAULT_FROM_BEFORE)
    assert "Use SQLite" not in _session_context(repo)
    assert _vault_call("print(vault.recall('.', 'sqlite'))", repo) == "[]"

    config = Path(os.environ["HOME"]) / ".agentic-forge" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"knowledge": {"allow_external_vault": True}}), encoding="utf-8")
    assert _python(call, repo).stdout.strip() == "[]"
    assert "[[use-sqlite]] — Use SQLite" in _session_context(repo)
    _vault_call(add, repo)
    assert (elsewhere / "next.md").is_file()
    assert (repo / "docs" / "knowledge").is_symlink()


# --- pre-checks refuse only what would be written (ADR 0102) ------------------


def _git_entry(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


def test_a_link_inside_the_git_repo_works_from_a_package_directory(tmp_path: Path) -> None:
    repo = _git_entry(tmp_path / "repo")
    add_note(repo, "a", "A", "a", moc="decisions")
    pkg = repo / "packages" / "app"
    pkg.mkdir(parents=True)
    (pkg / "docs").symlink_to("../../docs")
    assert validate_vault(pkg) == []
    assert "a" in load_vault(pkg).notes


def test_a_linked_readme_inside_the_repo_does_not_stop_captures(tmp_path: Path) -> None:
    """README.md is not a note, and nothing writes to it once it exists."""
    repo = _git_entry(tmp_path / "repo")
    add_note(repo, "a", "A", "a")
    vpath = vault_path(repo)
    (repo / "NOTES.md").write_text("# n\n", encoding="utf-8")
    (vpath / "README.md").unlink()
    (vpath / "README.md").symlink_to("../../NOTES.md")
    assert validate_vault(repo) == []
    add_note(repo, "b", "B", "b")
    assert (vpath / "b.md").is_file()
    assert (repo / "NOTES.md").read_text(encoding="utf-8") == "# n\n"


def test_a_read_only_root_moc_that_need_not_change_does_not_stop_captures(tmp_path: Path) -> None:
    """The themed map is already linked from the root, so nothing is written to the root."""
    repo = _git_entry(tmp_path / "repo")
    add_note(repo, "a", "A", "a", moc="decisions")
    (vault_path(repo) / "MOC.md").chmod(0o444)
    add_note(repo, "b", "B", "b", moc="decisions")
    assert "[[b|B]]" in (vault_path(repo) / "decisions.md").read_text(encoding="utf-8")
