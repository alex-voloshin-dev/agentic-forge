"""``artifact_home``: where a feature's documents and ADRs go in a repository with its own
convention, detected from the tree (field reports: a monorepo's ``features/<state>/<slug>/`` and
three ADR series; PRDs in a metadata-table format)."""

from __future__ import annotations

import os
import re
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
    artifact = result["artifact"]
    assert (artifact["kind"], artifact["path"]) == ("design", "docs/sdlc/foo/tech-design.md")
    assert (artifact["exists"], artifact["format"], "unsafe" in artifact) == (False, None, False)
    assert artifact["abs"] == str(tmp_path.resolve() / "docs/sdlc/foo/tech-design.md")
    assert set(result["documents"]) == {"research", "prd", "design", "plan", "ux"}
    assert result["documents"]["ux"]["path"] == "docs/sdlc/foo/ux-spec.md"


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
    assert result["artifact"]["path"] == "features/architecture/adr/adr-067-<title>.md"
    assert result["artifact"]["exists"] is False
    assert result["ambiguous"] is True
    why = " ".join(result["ambiguities"])
    assert "2 ADR series are equally near" in why and "ADR-GNN-<title>.md" in why
    assert "feature-local ADR folders" in why
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
    assert artifact["path"] == "features/in-progress/foo/prd.md"
    assert (artifact["exists"], artifact["format"]) == (True, "foreign")


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


# --- review round 1: every proposed path is safe on a command line --------------------------------

_HOSTILE = ["$(touch PWNED)", "`id`", "a;b", "a b", "-rf", "a|b", "a&b", "a'b", 'a"b', "a\\b",
            "a*b", "a$b", "a\nb", "ü"]


@pytest.mark.parametrize("bad", _HOSTILE)
def test_a_feature_folder_under_a_hostile_name_is_skipped_and_named(
    tmp_path: Path, bad: str
) -> None:
    try:
        _touch(tmp_path, f"features/{bad}/foo/prd.md")
    except OSError:
        pytest.skip("this filesystem refuses the name")
    result = _home(tmp_path, kind="prd")
    assert result["feature_dir"] == "docs/sdlc/foo" and result["detected"] is False
    assert result["ambiguous"] is True
    assert "skipped a feature folder" in result["ambiguities"][0]
    assert not (tmp_path / "PWNED").exists()


@pytest.mark.parametrize("bad", _HOSTILE)
def test_an_adr_series_under_a_hostile_name_is_skipped_and_named(
    tmp_path: Path, bad: str
) -> None:
    try:
        _touch(tmp_path, f"{bad}/adr/adr-007-x.md", "docs/adr/adr-002-y.md")
    except OSError:
        pytest.skip("this filesystem refuses the name")
    result = _home(tmp_path)
    assert result["adr"]["dir"] == "docs/adr" and result["adr"]["series_count"] == 1
    assert any("skipped an ADR series in" in why for why in result["ambiguities"])


def test_every_proposed_path_is_safe(tmp_path: Path) -> None:
    _monorepo(tmp_path)
    _touch(tmp_path, "features/$(x)/foo/prd.md", "odd dir/adr/adr-099-x.md")
    result = _home(tmp_path, kind="adr")
    assert ah.is_safe_path(result["feature_dir"]) and ah.is_safe_path(result["adr"]["dir"])
    assert all(ah.is_safe_path(s["dir"]) for s in result["adr"]["series"])
    assert all(ah.is_safe_path(d) for d in result["feature_candidates"])


@pytest.mark.parametrize(("rel", "safe"), [
    ("", True), ("a/b.c/d_e-f", True), ("A1", True), (".hidden", False), ("-x", False),
    ("a/-x", False), ("a b", False), ("a//b", False), ("a/", False), ("x\n", False),
])
def test_is_safe_path(rel: str, safe: bool) -> None:
    assert ah.is_safe_path(rel) is safe


# --- the spelling on disk -------------------------------------------------------------------------


def test_a_document_keeps_the_spelling_it_has_on_disk(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/PRD.md", text=_TABLE_PRD)
    result = _home(tmp_path, kind="prd")
    assert result["artifact"]["path"] == "features/foo/PRD.md"
    assert result["artifact"]["exists"] is True and result["artifact"]["format"] == "foreign"
    assert result["documents"]["plan"]["path"] == "features/foo/plan.md"  # none yet: ours
    assert result["ambiguous"] is False


def test_several_spellings_of_one_document_are_ambiguous(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/PRD.md", "features/foo/prd.md")
    if len(list((tmp_path / "features" / "foo").iterdir())) < 2:
        pytest.skip("a case-insensitive filesystem holds one of them")
    result = _home(tmp_path, kind="prd")
    assert result["artifact"]["path"] == "features/foo/prd.md"
    assert any("2 spellings of prd.md" in why for why in result["ambiguities"])


# --- what is at the path: never write through a link ----------------------------------------------


def test_a_symlinked_document_is_reported_unsafe(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/plan.md", "elsewhere.md")
    (tmp_path / "features" / "foo" / "prd.md").symlink_to(tmp_path / "elsewhere.md")
    artifact = _home(tmp_path, kind="prd")["artifact"]
    assert artifact["exists"] is True and artifact["unsafe"] == "symlink: features/foo/prd.md"
    assert artifact["format"] is None


def test_a_dangling_symlink_is_reported_unsafe(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/plan.md")
    (tmp_path / "features" / "foo" / "tech-design.md").symlink_to(tmp_path / "nowhere.md")
    artifact = _home(tmp_path, kind="design")["artifact"]
    assert artifact["exists"] is True and artifact["unsafe"].startswith("symlink")


def test_a_fifo_or_directory_at_the_path_is_unsafe(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/plan.md")
    os.mkfifo(tmp_path / "features" / "foo" / "prd.md")
    (tmp_path / "features" / "foo" / "tech-design.md").mkdir()
    result = _home(tmp_path)
    assert result["documents"]["prd"]["unsafe"] == "not a regular file: features/foo/prd.md"
    assert result["documents"]["design"]["unsafe"] == "directory: features/foo/tech-design.md"


def test_a_symlink_on_the_way_to_the_fallback_is_unsafe(tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "docs").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    result = _home(tmp_path, kind="plan")
    assert result["artifact"]["unsafe"] == "symlink: docs"
    assert result["adr"]["unsafe"] == "symlink: docs"


def test_a_file_on_the_way_is_unsafe(tmp_path: Path) -> None:
    _touch(tmp_path, "docs/sdlc")
    assert _home(tmp_path)["documents"]["prd"]["unsafe"] == "not a directory: docs/sdlc"


def test_an_adr_directory_to_create_that_is_a_link_is_unsafe(tmp_path: Path) -> None:
    _touch(tmp_path, "features/a/prd.md", "features/a/adr/adr-001-x.md", "features/foo/prd.md")
    (tmp_path / "features" / "foo" / "adr").symlink_to(tmp_path, target_is_directory=True)
    adr = _home(tmp_path)["adr"]
    assert adr["create_dir"] is True and adr["unsafe"] == "symlink: features/foo/adr"


def test_an_existing_adr_directory_is_reported(tmp_path: Path) -> None:
    _monorepo(tmp_path)
    adr = _home(tmp_path)["adr"]
    assert adr["dir_exists"] is True and "unsafe" not in adr


# --- the walk's caps, the root, the owner, the slug, dated names ----------------------------------


def test_the_depth_cap_is_reported(tmp_path: Path) -> None:
    _touch(tmp_path, "a/b/c/d/foo/prd.md")
    found = ah.scan(str(tmp_path), max_depth=3)
    assert found.depth_capped is True and found.truncated is False
    result = ah.resolve(found, "foo")
    assert result["truncated"] is True and result["ambiguous"] is True
    assert "depth" in result["ambiguities"][-1]
    assert ah.scan(str(tmp_path), max_depth=6).depth_capped is False


def test_a_skipped_directory_at_the_depth_cap_is_not_reported(tmp_path: Path) -> None:
    _touch(tmp_path, "a/node_modules/x.js", "a/.git_like/x")
    assert ah.scan(str(tmp_path), max_depth=1).depth_capped is False


def test_records_at_the_top_are_not_a_series(tmp_path: Path) -> None:
    _touch(tmp_path, "adr-005-x.md", "ADR-G01-y.md")
    adr = _home(tmp_path)["adr"]
    assert adr["series_count"] == 0 and adr["scope"] == "none"


@pytest.mark.parametrize("folder", ["decisions", "adrs", "ADR"])
def test_a_feature_local_decisions_folder_is_that_features_own(
    tmp_path: Path, folder: str
) -> None:
    _touch(tmp_path, "features/a/prd.md", f"features/a/{folder}/0001-x.md",
           f"features/a/{folder}/0002-y.md", "features/foo/prd.md")
    adr = _home(tmp_path)["adr"]
    assert adr["series"][0]["scope"] == "feature"
    assert adr["dir"] == f"features/foo/{folder}" and adr["create_dir"] is True
    assert adr["next_id"] == "0001"  # foo starts its own; a's 0002 is not continued


@pytest.mark.parametrize("slug", ["build", "vendor", "target", "out"])
def test_a_folder_named_like_the_slug_is_read_even_if_it_is_usually_skipped(
    tmp_path: Path, slug: str
) -> None:
    _touch(tmp_path, f"features/{slug}/prd.md", "node_modules/foo/prd.md")
    assert _home(tmp_path, slug=slug)["feature_dir"] == f"features/{slug}"
    assert _home(tmp_path)["feature_dir"] == "docs/sdlc/foo"


@pytest.mark.parametrize(
    "name", ["2024-01-15-retro.md", "2024_03-notes.md", "2024-1-x.md", "2023-12.md"]
)
def test_dated_notes_are_not_decision_records(name: str) -> None:
    assert ah.adr_file(name, "decisions") is None


def test_a_numbered_record_is_not_mistaken_for_a_date() -> None:
    assert ah.adr_file("0012-3d-printing.md", "adr") is not None


# --- a document the user named --------------------------------------------------------------------


def _linked(checkout: Path, worktree: Path, name: str = "wt") -> None:
    """What `git worktree add` lays down: a private git directory whose `commondir` points back."""
    private = checkout / ".git" / "worktrees" / name
    private.mkdir(parents=True)
    (private / "commondir").write_text("../..\n", encoding="utf-8")
    worktree.mkdir(parents=True, exist_ok=True)
    (worktree / ".git").write_text(f"gitdir: {private}\n", encoding="utf-8")


def test_a_checkout_path_maps_to_the_same_path_in_the_worktree(tmp_path: Path) -> None:
    checkout, worktree = tmp_path / "repo", tmp_path / "wt"
    _touch(checkout, ".git/HEAD", "features/foo/PRD-export.md", "features/foo/plan.md")
    _linked(checkout, worktree)
    _touch(worktree, "features/foo/plan.md")
    named = str(checkout / "features" / "foo" / "PRD-export.md")
    assert ah.relative_document(str(worktree), named) == "features/foo/PRD-export.md"
    result = ah.home(str(worktree), "foo", "prd", named)
    artifact = result["artifact"]
    assert artifact["path"] == "features/foo/PRD-export.md" and artifact["named"] is True
    assert artifact["abs"] == str(worktree.resolve() / "features/foo/PRD-export.md")
    assert artifact["exists"] is False  # not in the worktree yet: never the checkout's copy
    assert result["documents"]["prd"]["path"] == "features/foo/PRD-export.md"


def test_a_relative_named_path_is_read_against_the_repo(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/spec/prd.md")
    result = ah.home(str(tmp_path), "foo", "prd", "features/foo/spec/prd.md")
    assert result["artifact"]["exists"] is True


@pytest.mark.parametrize(
    ("named", "says"),
    [("../x.md", "must name a file in the repository"),
     ("features/$(id)/prd.md", "must name a file in the repository"),
     ("features/a b/prd.md", "must name a file in the repository"),
     ("features/foo/prd.txt", "not a Markdown document"),
     (".", "must name a file in the repository")],
)
def test_a_named_path_is_refused_unless_safe(tmp_path: Path, named: str, says: str) -> None:
    with pytest.raises(ValueError, match=re.escape(says)):
        ah.relative_document(str(tmp_path), named)


def test_an_absolute_path_outside_any_working_tree_is_refused(tmp_path: Path) -> None:
    _touch(tmp_path, "loose/prd.md")
    with pytest.raises(ValueError, match="not inside a git working tree"):
        ah.relative_document(str(tmp_path), str(tmp_path / "loose" / "prd.md"))


def test_a_named_path_needs_a_document_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--path needs --kind of a document"):
        ah.home(str(tmp_path), "foo", "adr", "x.md")
    with pytest.raises(ValueError, match="--path needs --kind of a document"):
        ah.home(str(tmp_path), "foo", None, "x.md")


def test_a_ux_spec_marks_a_feature_folder(tmp_path: Path) -> None:
    _touch(tmp_path, "apps/web/features/foo/ux-spec.md")
    result = _home(tmp_path, kind="ux")
    assert result["feature_dir"] == "apps/web/features/foo"
    assert result["artifact"]["exists"] is True


# --- review round 2 -------------------------------------------------------------------------------


def test_a_path_from_another_repository_is_refused(tmp_path: Path) -> None:
    """Same relative path, unrelated repository: mapping it would edit a file the user never
    named. A separate clone has its own git directory, so it is another repository too."""
    mine, other = tmp_path / "mine", tmp_path / "other"
    _touch(mine, ".git/HEAD", "features/foo/prd.md")
    _touch(other, ".git/HEAD", "features/foo/prd.md")
    with pytest.raises(ValueError, match="in another repository than --repo"):
        ah.relative_document(str(mine), str(other / "features" / "foo" / "prd.md"))
    worktree = tmp_path / "wt"
    _linked(other, worktree)
    with pytest.raises(ValueError, match="in another repository than --repo"):
        ah.relative_document(str(worktree), str(mine / "features" / "foo" / "prd.md"))
    assert ah.relative_document(str(worktree), str(other / "features" / "foo" / "prd.md")) == (
        "features/foo/prd.md"
    )


def test_a_path_cannot_be_mapped_into_a_directory_outside_any_repository(tmp_path: Path) -> None:
    _touch(tmp_path, "repo/.git/HEAD", "repo/features/foo/prd.md")
    loose = tmp_path / "loose"
    loose.mkdir()
    with pytest.raises(ValueError, match="in another repository"):
        ah.relative_document(str(loose), str(tmp_path / "repo" / "features" / "foo" / "prd.md"))


def test_an_unreadable_git_file_is_no_repository(tmp_path: Path) -> None:
    _touch(tmp_path, "repo/.git/HEAD", "repo/features/foo/prd.md", "wt/.git", text="nonsense\n")
    with pytest.raises(ValueError, match="in another repository"):
        ah.relative_document(str(tmp_path / "wt"),
                             str(tmp_path / "repo" / "features" / "foo" / "prd.md"))


@pytest.mark.parametrize("slug", ["foo\n", "foo\nbar", "a\n"])
def test_a_slug_with_a_trailing_newline_is_refused(tmp_path: Path, slug: str) -> None:
    with pytest.raises(ValueError, match="invalid feature slug"):
        _home(tmp_path, slug=slug)
    assert ah.marks_feature(["prd.md"], slug) is False


@pytest.mark.parametrize(("name", "directory"), [
    ("adr-001.md\n", ""), ("ADR-G14-x.md\n", ""), ("0001-x.md\n", "decisions"),
])
def test_a_record_name_with_a_trailing_newline_is_not_one(name: str, directory: str) -> None:
    assert ah.adr_file(name, directory) is None


def test_the_fallback_is_checked_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ah, "FALLBACK_ROOT", "docs/s dlc")
    with pytest.raises(ValueError, match="invalid feature slug"):
        ah.resolve(ah.Scan({}), "foo")


def test_rounds_are_listed_by_iteration_as_a_number(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/prd.md", "features/foo/review-prd-10.md",
           "features/foo/review-prd-2.md", "features/foo/review-plan-1.md",
           "features/foo/review.md", "features/foo/review-notes.md", "features/foo/REVIEW-prd-3.md")
    rounds = _home(tmp_path)["rounds"]
    assert [(r["artifact"], r["iteration"]) for r in rounds] == [
        ("plan", 1), ("prd", 2), ("prd", 10),
    ]
    assert rounds[-1]["abs"] == str(tmp_path.resolve() / "features/foo/review-prd-10.md")
    assert all("unsafe" not in r for r in rounds)


def test_a_linked_round_is_never_offered(tmp_path: Path) -> None:
    """The walk does not read through links, so a linked round is not listed for removal."""
    _touch(tmp_path, "features/foo/prd.md", "elsewhere.md")
    (tmp_path / "features" / "foo" / "review-prd-1.md").symlink_to(tmp_path / "elsewhere.md")
    assert _home(tmp_path)["rounds"] == []


def test_a_round_replaced_by_a_link_after_the_walk_is_unsafe(tmp_path: Path) -> None:
    _touch(tmp_path, "features/foo/prd.md", "elsewhere.md", "features/foo/review-prd-1.md")
    found = ah.scan(str(tmp_path), keep="foo")
    (tmp_path / "features" / "foo" / "review-prd-1.md").unlink()
    (tmp_path / "features" / "foo" / "review-prd-1.md").symlink_to(tmp_path / "elsewhere.md")
    (round_,) = ah.resolve(found, "foo")["rounds"]
    ah._on_disk(str(tmp_path.resolve()), round_, None)
    assert round_["unsafe"].startswith("symlink")
