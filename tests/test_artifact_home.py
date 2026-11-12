"""``artifact_home``: where a feature's documents and ADRs go in a repository with its own
convention, detected from the tree (field reports: a monorepo's ``features/<state>/<slug>/`` and
three ADR series; PRDs in a metadata-table format)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agentic_forge import artifact_home as ah
from agentic_forge import doc_delivery


def _touch(root: Path, *relatives: str, text: str = "x\n") -> None:
    for relative in relatives:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _home(root: Path, slug: str = "foo", kind: str | None = None) -> dict:
    return ah.home(str(root), slug, kind)


# --- what counts as a decision record -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "directory", "ident", "pattern"),
    [
        ("adr-001-use-postgres.md", "", "adr-001", "adr-NNN-<title>.md"),
        ("ADR-G14-global-auth.md", "", "ADR-G14", "ADR-GNN-<title>.md"),
        ("adr_0042.md", "", "adr_0042", "adr_NNNN-<title>.md"),
        ("ADR-7.MD", "", "ADR-7", "ADR-N-<title>.md"),
        ("adr001_title.md", "", "adr001", "adrNNN_<title>.md"),
        ("0001-record-decisions.md", "decisions", "0001", "NNNN-<title>.md"),
        ("0012-x.md", "ADR", "0012", "NNNN-<title>.md"),
    ],
)
def test_a_numbered_record_is_a_series_member(
    name: str, directory: str, ident: str, pattern: str
) -> None:
    member = ah.adr_file(name, directory)
    assert member is not None
    assert member.ident() == ident
    assert member.pattern() == pattern


@pytest.mark.parametrize(
    ("name", "directory"),
    [
        ("adr-datastore.md", ""),  # the plugin's own unnumbered form: no series to continue
        ("adr-db2-migration.md", ""),  # a letter prefix needs two digits: this is a title
        ("adr-001foo.md", ""),
        ("adr-001.txt", ""),
        ("0001-x.md", "src"),  # a bare number is a record only in a decisions directory
        ("01-x.md", "decisions"),
        ("readme.md", "adr"),
        ("myadr-001.md", ""),
    ],
)
def test_other_names_are_not(name: str, directory: str) -> None:
    assert ah.adr_file(name, directory) is None


@pytest.mark.parametrize(
    ("highest", "following"),
    [("adr-066-x.md", "adr-067"), ("ADR-G14-x.md", "ADR-G15"), ("adr-099.md", "adr-100"),
     ("adr-999.md", "adr-1000"), ("ADR-G09-x.md", "ADR-G10")],
)
def test_numbering_continues_in_the_series_spelling(highest: str, following: str) -> None:
    member = ah.adr_file(highest)
    assert member is not None
    assert member.ident(member.number + 1) == following


# --- the feature folder ---------------------------------------------------------------------------


def test_a_greenfield_repository_falls_back_to_docs_sdlc(tmp_path: Path) -> None:
    _touch(tmp_path, "README.md", "src/app.py")
    result = _home(tmp_path, kind="design")
    assert result["feature_dir"] == "docs/sdlc/foo"
    assert result["detected"] is False and result["existing"] == []
    assert result["adr"]["scope"] == "none" and result["adr"]["detected"] is False
    assert result["adr"]["dir"] == "docs/sdlc/foo"
    assert result["adr"]["next_file"] == "adr-<decision>.md" and result["adr"]["next_id"] is None
    assert result["ambiguous"] is False and result["ambiguities"] == []
    assert result["artifact"] == {
        "kind": "design", "path": "docs/sdlc/foo/tech-design.md", "exists": False, "format": None,
    }


def test_the_plugins_own_folder_is_detected_as_itself(tmp_path: Path) -> None:
    _touch(tmp_path, "docs/sdlc/foo/prd.md", "docs/sdlc/foo/adr-datastore.md")
    result = _home(tmp_path)
    assert result["feature_dir"] == "docs/sdlc/foo" and result["detected"] is True
    assert result["adr"]["scope"] == "none"  # unnumbered records are not a series


@pytest.mark.parametrize("document", ["prd.md", "plan.md", "design.md", "tech-design.md",
                                      "research-brief.md", "PRD.md"])
def test_an_existing_feature_folder_is_where_documents_go(tmp_path: Path, document: str) -> None:
    _touch(tmp_path, f"features/in-progress/foo/{document}", "features/planned/bar/prd.md")
    result = _home(tmp_path, kind="plan")
    assert result["feature_dir"] == "features/in-progress/foo"
    assert result["detected"] is True and result["existing"] == [document]
    assert result["artifact"]["path"] == "features/in-progress/foo/plan.md"


@pytest.mark.parametrize("relative", ["features/foo/README.md", "features/foo/notes.md",
                                      "features/foo-bar/prd.md", "features/Foo/prd.md"])
def test_a_folder_without_a_feature_document_or_of_another_name_is_not_it(
    tmp_path: Path, relative: str
) -> None:
    _touch(tmp_path, relative)
    assert _home(tmp_path)["feature_dir"] == "docs/sdlc/foo"


def test_several_folders_for_one_slug_are_ambiguous(tmp_path: Path) -> None:
    _touch(tmp_path, "docs/sdlc/foo/prd.md",
           "features/in-progress/foo/prd.md", "features/in-progress/foo/design.md")
    result = _home(tmp_path)
    assert result["feature_dir"] == "features/in-progress/foo"  # holds the most documents
    assert result["feature_candidates"] == ["features/in-progress/foo", "docs/sdlc/foo"]
    assert result["ambiguous"] is True and "2 folders named foo" in result["ambiguities"][0]


def test_with_equal_documents_the_shallowest_folder_wins(tmp_path: Path) -> None:
    _touch(tmp_path, "a/b/c/foo/prd.md", "x/foo/prd.md")
    assert _home(tmp_path)["feature_dir"] == "x/foo"


# --- the ADR series -------------------------------------------------------------------------------


def _monorepo(root: Path) -> None:
    """The field report's shape: a central series, a second series beside it, feature-local adr/
    folders, and features in lifecycle folders."""
    central = root / "features" / "architecture" / "adr"
    for n in range(1, 67):
        _touch(central, f"adr-{n:03d}-decision.md")
    for n in range(1, 15):
        _touch(central, f"ADR-G{n:02d}-global.md")
    _touch(root, "features/implemented/old/prd.md", "features/implemented/old/adr/adr-001-x.md",
           "features/implemented/old/adr/adr-002-y.md", "features/in-progress/foo/prd.md")


def test_the_monorepo_case_is_ambiguous_and_continues_the_main_series(tmp_path: Path) -> None:
    _monorepo(tmp_path)
    result = _home(tmp_path, kind="adr")
    adr = result["adr"]
    assert result["feature_dir"] == "features/in-progress/foo"
    assert adr["series_count"] == 3
    assert adr["dir"] == "features/architecture/adr" and adr["scope"] == "shared"
    assert adr["highest"] == "adr-066" and adr["next_id"] == "adr-067"
    assert adr["next_file"] == "adr-067-<title>.md"
    assert result["artifact"] == {
        "kind": "adr", "path": "features/architecture/adr/adr-067-<title>.md", "exists": False,
    }
    assert result["ambiguous"] is True
    why = " ".join(result["ambiguities"])
    assert "2 ADR series are equally near" in why and "ADR-GNN-<title>.md" in why
    assert "feature-local adr/ folders" in why
    second = next(s for s in adr["series"] if s["pattern"].startswith("ADR-G"))
    assert second["highest"] == "ADR-G14" and second["next_id"] == "ADR-G15"
    assert second["count"] == 14
    local = next(s for s in adr["series"] if s["scope"] == "feature")
    assert local["dir"] == "features/implemented/old/adr" and local["next_id"] == "adr-003"


def test_the_features_own_series_wins_and_is_not_ambiguous(tmp_path: Path) -> None:
    _monorepo(tmp_path)
    _touch(tmp_path, "features/in-progress/foo/adr/adr-001-mine.md")
    adr = _home(tmp_path)["adr"]
    assert adr["dir"] == "features/in-progress/foo/adr" and adr["scope"] == "feature"
    assert adr["next_id"] == "adr-002"
    assert _home(tmp_path)["ambiguous"] is False


def test_records_in_the_feature_folder_itself_are_its_own_series(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/prd.md", "features/foo/ADR-003-x.md", "decisions/adr-040-y.md")
    adr = _home(tmp_path)["adr"]
    assert adr["dir"] == "features/foo" and adr["next_id"] == "ADR-004"


def test_the_nearest_shared_series_is_chosen_without_ambiguity(tmp_path: Path) -> None:
    _touch(tmp_path, "services/pay/docs/adr/adr-004-x.md", "docs/adr/adr-020-y.md",
           "services/pay/features/foo/prd.md")
    result = _home(tmp_path)
    assert result["adr"]["dir"] == "services/pay/docs/adr"
    assert result["adr"]["next_id"] == "adr-005"
    assert result["adr"]["series_count"] == 2 and result["ambiguous"] is False
    assert [s["dir"] for s in result["adr"]["series"]] == ["services/pay/docs/adr", "docs/adr"]


def test_adr_tools_numbering_is_continued(tmp_path: Path) -> None:
    _touch(tmp_path, "doc/adr/0001-record.md", "doc/adr/0002-use-x.md")
    adr = _home(tmp_path)["adr"]
    assert adr["dir"] == "doc/adr" and adr["next_file"] == "0003-<title>.md"


def test_only_other_features_series_means_a_feature_local_convention(tmp_path: Path) -> None:
    _touch(tmp_path, "features/a/prd.md", "features/a/adr/ADR-01-x.md",
           "features/b/prd.md", "features/b/adr/ADR-01-y.md", "features/b/adr/ADR-02-z.md",
           "features/foo/prd.md")
    adr = _home(tmp_path)["adr"]
    assert adr["dir"] == "features/foo/adr" and adr["create_dir"] is True
    assert adr["next_id"] == "ADR-01" and adr["highest"] is None and adr["scope"] == "feature"


def test_a_feature_local_convention_in_the_folder_itself_needs_no_new_directory(
    tmp_path: Path
) -> None:
    _touch(tmp_path, "features/a/prd.md", "features/a/adr-001-x.md", "features/foo/plan.md")
    adr = _home(tmp_path)["adr"]
    assert adr["dir"] == "features/foo" and adr["create_dir"] is False
    assert adr["next_id"] == "adr-001"


def test_a_top_level_adr_directory_is_shared_even_beside_a_root_plan(tmp_path: Path) -> None:
    _touch(tmp_path, "plan.md", "adr/adr-005-x.md")
    adr = _home(tmp_path)["adr"]
    assert adr["scope"] == "shared" and adr["next_id"] == "adr-006"


def test_the_series_report_is_capped(tmp_path: Path) -> None:
    for n in range(25):
        _touch(tmp_path, f"area{n:02d}/adr/adr-001-x.md")
    adr = _home(tmp_path)["adr"]
    assert adr["series_count"] == 25 and len(adr["series"]) == 20


# --- the walk's bounds ----------------------------------------------------------------------------


def test_a_capped_walk_says_so_and_is_ambiguous(tmp_path: Path) -> None:
    for n in range(30):
        _touch(tmp_path, f"d{n:02d}/file.txt")
    found = ah.scan(str(tmp_path), max_entries=10)
    assert found.truncated is True
    result = ah.resolve(found, "foo")
    assert result["truncated"] is True and result["ambiguous"] is True
    assert "cap" in result["ambiguities"][-1]


def test_the_depth_cap_stops_the_walk(tmp_path: Path) -> None:
    _touch(tmp_path, "a/b/c/foo/prd.md")
    assert "a/b/c/foo" not in ah.scan(str(tmp_path), max_depth=3).dirs
    assert "a/b/c/foo" in ah.scan(str(tmp_path), max_depth=4).dirs


@pytest.mark.parametrize(
    "relative",
    ["node_modules/x/foo/prd.md", "vendor/foo/prd.md", "build/foo/prd.md", "dist/foo/plan.md",
     ".claude/worktrees/wt/features/foo/prd.md", ".git/foo/prd.md", ".hidden/foo/prd.md",
     "target/foo/prd.md"],
)
def test_hidden_dependency_and_build_directories_are_skipped(
    tmp_path: Path, relative: str
) -> None:
    _touch(tmp_path, relative)
    assert _home(tmp_path)["feature_dir"] == "docs/sdlc/foo"


def test_a_nested_repository_is_skipped(tmp_path: Path) -> None:
    _touch(tmp_path, "third_party/lib/.git", "third_party/lib/features/foo/prd.md",
           "third_party/lib/adr/adr-009-x.md")
    result = _home(tmp_path)
    assert result["feature_dir"] == "docs/sdlc/foo" and result["adr"]["series_count"] == 0


def test_a_symlinked_directory_is_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _touch(outside, "foo/prd.md", "adr/adr-010-x.md")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "features").symlink_to(outside, target_is_directory=True)
    result = _home(repo)
    assert result["feature_dir"] == "docs/sdlc/foo" and result["adr"]["series_count"] == 0


def test_a_symlinked_document_does_not_make_a_feature_folder(tmp_path: Path) -> None:
    _touch(tmp_path, "elsewhere/prd.md")
    (tmp_path / "features" / "foo").mkdir(parents=True)
    (tmp_path / "features" / "foo" / "prd.md").symlink_to(tmp_path / "elsewhere" / "prd.md")
    assert _home(tmp_path)["detected"] is False


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs file modes")
def test_an_unreadable_directory_is_skipped(tmp_path: Path) -> None:
    _touch(tmp_path, "locked/foo/prd.md", "open/foo/prd.md")
    (tmp_path / "locked").chmod(0)
    try:
        assert _home(tmp_path)["feature_dir"] == "open/foo"
    finally:
        (tmp_path / "locked").chmod(0o755)


def test_a_bad_slug_or_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid feature slug"):
        _home(tmp_path, slug="../etc")
    with pytest.raises(ValueError, match="unknown kind"):
        _home(tmp_path, kind="readme")


# --- the document's format ------------------------------------------------------------------------


_TABLE_PRD = "# Export\n\n| Field | Value |\n| --- | --- |\n| **Status** | Draft |\n\n## Goals\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\ntype: prd\nfeature: foo\n---\nbody\n", "handoff"),
        ("---\ntype: 'prd'\n---\n", "handoff"),
        (_TABLE_PRD, "foreign"),
        ("---\ntitle: Export\nstatus: draft\n---\n", "foreign"),  # another tool's header
        ("---\ntype: plan\n---\n", "foreign"),
        ("", "foreign"),
        ("intro\n---\ntype: prd\n---\n", "foreign"),
    ],
)
def test_the_format_is_ours_only_with_our_header(text: str, expected: str) -> None:
    assert ah.artifact_format(text, "prd") == expected


def test_an_existing_prd_reports_its_format(tmp_path: Path) -> None:
    _touch(tmp_path, "features/in-progress/foo/prd.md", text=_TABLE_PRD)
    artifact = _home(tmp_path, kind="prd")["artifact"]
    assert artifact == {
        "kind": "prd", "path": "features/in-progress/foo/prd.md", "exists": True,
        "format": "foreign",
    }


def test_a_symlinked_artifact_is_reported_absent(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/plan.md", "elsewhere.md")
    (tmp_path / "features" / "foo" / "prd.md").symlink_to(tmp_path / "elsewhere.md")
    assert _home(tmp_path, kind="prd")["artifact"]["exists"] is False


# --- the review files diagnostics reads -----------------------------------------------------------


def test_review_files_are_those_beside_a_feature_document(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/prd.md", "features/foo/review-prd-2.md",
           "features/foo/notes.md", "random/review-x.md")
    assert ah.review_files(ah.scan(str(tmp_path))) == ["features/foo/review-prd-2.md"]


# --- what the role-scope hook asks about one directory --------------------------------------------


def test_is_feature_dir_needs_a_slug_name_and_a_regular_document(tmp_path: Path) -> None:
    _touch(tmp_path, "good/plan.md", "Bad Name/plan.md", "empty/notes.md", "elsewhere.md")
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / "prd.md").symlink_to(tmp_path / "elsewhere.md")
    assert ah.is_feature_dir(str(tmp_path / "good")) is True
    assert ah.is_feature_dir(str(tmp_path / "Bad Name")) is False
    assert ah.is_feature_dir(str(tmp_path / "empty")) is False
    assert ah.is_feature_dir(str(tmp_path / "linked")) is False
    assert ah.is_feature_dir(str(tmp_path / "missing")) is False


def test_holds_adr_series(tmp_path: Path) -> None:
    _touch(tmp_path, "a/adr-001-x.md", "decisions/0001-x.md", "b/adr-notes.md", "c/0001-x.md")
    assert ah.holds_adr_series(str(tmp_path / "a")) is True
    assert ah.holds_adr_series(str(tmp_path / "decisions")) is True
    assert ah.holds_adr_series(str(tmp_path / "b")) is False
    assert ah.holds_adr_series(str(tmp_path / "c")) is False
    assert ah.holds_adr_series(str(tmp_path / "missing")) is False


def test_a_directory_over_the_listing_cap_is_not_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch(tmp_path, "foo/a.md", "foo/b.md", "foo/prd.md")
    monkeypatch.setattr(ah, "MAX_DIR_ENTRIES", 2)
    assert ah.is_feature_dir(str(tmp_path / "foo")) is False


def test_the_slug_shape_is_doc_deliverys() -> None:
    assert ah.SLUG_RE.pattern == doc_delivery.SLUG_RE.pattern
