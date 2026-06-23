from __future__ import annotations

from pathlib import Path

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
