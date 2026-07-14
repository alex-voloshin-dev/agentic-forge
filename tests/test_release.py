from __future__ import annotations

import pytest

from agentic_forge import release
from agentic_forge.release import (
    Summary,
    changelog_groups,
    classify,
    looks_calver,
    next_calver,
    next_version,
    summarize,
)

# --- classify ------------------------------------------------------------------------


def test_classify_feat_maps_to_added() -> None:
    c = classify("feat: add ranking parameter")
    assert (c.type, c.group, c.breaking, c.description) == (
        "feat",
        "Added",
        False,
        "add ranking parameter",
    )


def test_classify_fix_maps_to_fixed() -> None:
    assert classify("fix: cache TTL").group == "Fixed"


def test_classify_scope_is_stripped_from_type() -> None:
    c = classify("feat(search): add facets")
    assert c.type == "feat" and c.description == "add facets"


def test_classify_bang_marks_breaking() -> None:
    c = classify("feat!: drop the v1 API")
    assert c.breaking is True and c.group == "Added"


def test_classify_breaking_change_trailer_marks_breaking() -> None:
    c = classify("refactor: rework config\n\nBREAKING CHANGE: env vars renamed")
    assert c.breaking is True and c.group == "Changed"


def test_classify_breaking_change_hyphen_footer_marks_breaking() -> None:
    # the spec's BREAKING-CHANGE: synonym (uppercase footer) is still honoured
    c = classify("refactor: x\n\nBREAKING-CHANGE: env renamed")
    assert c.breaking is True


def test_classify_breaking_phrase_in_description_is_not_breaking() -> None:
    # the phrase in prose (lowercase, mid-line, no footer) must NOT escalate the bump
    c = classify("fix: handle breaking change in upstream JSON format")
    assert c.breaking is False and c.group == "Fixed"


def test_summarize_breaking_phrase_in_description_stays_patch() -> None:
    s = summarize("2.3.4", ["fix: handle breaking change in upstream JSON"])
    assert (s.version, s.bump) == ("2.3.5", "patch")


def test_summarize_strips_prerelease_and_build_metadata() -> None:
    # a pre-release / build-metadata tag from `git describe` must not crash; the semver suffix is
    # dropped and the core is bumped (was a ValueError before).
    assert summarize("v1.2.3-rc.1", ["feat: add x"]).version == "v1.3.0"
    assert summarize("1.2.3+build", ["fix: y"]).version == "1.2.4"
    assert summarize("2.0.0-beta", ["fix: z"]).version == "2.0.1"


def test_classify_non_conventional_is_other() -> None:
    c = classify("update the README")
    assert c.type == "other" and c.group is None and c.description == "update the README"


@pytest.mark.parametrize(
    "msg,group",
    [
        ("perf: faster index", "Changed"),
        ("refactor: tidy", "Changed"),
        ("revert: undo X", "Removed"),
        ("remove: drop dead code", "Removed"),
        ("deprecate: old flag", "Deprecated"),
        ("security: patch XSS", "Security"),
    ],
)
def test_classify_type_groups(msg: str, group: str) -> None:
    assert classify(msg).group == group


# --- next_version --------------------------------------------------------------------


def test_next_version_patch_on_fix() -> None:
    assert next_version("1.4.2", [classify("fix: x")]) == "1.4.3"


def test_next_version_minor_on_feat() -> None:
    assert next_version("1.4.2", [classify("feat: x")]) == "1.5.0"


def test_next_version_major_on_breaking() -> None:
    assert next_version("1.4.2", [classify("feat!: x")]) == "2.0.0"


def test_next_version_pre_1_0_breaking_bumps_minor() -> None:
    # semver 0.y.z: a breaking change bumps minor, not major.
    assert next_version("0.4.2", [classify("feat!: x")]) == "0.5.0"


def test_next_version_none_when_no_changes() -> None:
    assert next_version("1.4.2", []) == "1.4.2"


def test_next_version_preserves_v_prefix() -> None:
    assert next_version("v1.0.0", [classify("feat: x")]) == "v1.1.0"


def test_next_version_strongest_bump_wins() -> None:
    changes = [classify("fix: a"), classify("feat: b"), classify("chore: c")]
    assert next_version("1.0.0", changes) == "1.1.0"  # feat -> minor beats fix -> patch


def test_next_version_rejects_bad_version() -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        next_version("1.x", [classify("fix: x")])


# --- changelog_groups ----------------------------------------------------------------


def test_changelog_groups_orders_and_groups() -> None:
    changes = [classify("fix: f1"), classify("feat: a1"), classify("feat: a2")]
    groups = changelog_groups(changes)
    assert list(groups) == ["Added", "Fixed"]  # GROUP_ORDER: Added before Fixed
    assert groups["Added"] == ["a1", "a2"]
    assert groups["Fixed"] == ["f1"]


def test_changelog_groups_prefixes_breaking() -> None:
    groups = changelog_groups([classify("feat!: drop v1")])
    assert groups["Added"] == ["**BREAKING:** drop v1"]


def test_changelog_groups_omits_uncategorised() -> None:
    assert changelog_groups([classify("chore: deps"), classify("just text")]) == {}


# --- summarize -----------------------------------------------------------------------


def test_summarize_end_to_end() -> None:
    messages = [
        "feat: add facets",
        "fix: cache TTL",
        "refactor: rework config\n\nBREAKING CHANGE: env renamed",
        "chore: bump deps",
    ]
    s = summarize("1.2.3", messages)
    assert isinstance(s, Summary)
    assert s.bump == "major" and s.version == "2.0.0"
    assert s.breaking == ["rework config"]
    assert s.groups["Added"] == ["add facets"]
    assert s.groups["Changed"] == ["**BREAKING:** rework config"]
    assert s.groups["Fixed"] == ["cache TTL"]


def test_summarize_no_changes_keeps_version() -> None:
    s = summarize("1.2.3", [])
    assert s.bump == "none" and s.version == "1.2.3" and s.groups == {}


def test_module_exports_group_order() -> None:
    assert release.GROUP_ORDER[0] == "Added" and "Security" in release.GROUP_ORDER


# --- CalVer (ADR 0055): <year>.<month>.<inc>, inc restarts each month -----------------


def test_next_calver_first_release_of_month_from_semver_current() -> None:
    # the migration step itself: 0.1.0 -> 2026.7.1 (counter starts at 1 under the new scheme)
    assert next_calver("0.1.0", year=2026, month=7) == "2026.7.1"


def test_next_calver_increments_within_month() -> None:
    assert next_calver("2026.7.1", year=2026, month=7) == "2026.7.2"
    assert next_calver("2026.7.9", year=2026, month=7) == "2026.7.10"


def test_next_calver_restarts_on_new_month_and_year() -> None:
    assert next_calver("2026.7.4", year=2026, month=8) == "2026.8.1"
    assert next_calver("2026.12.3", year=2027, month=1) == "2027.1.1"


def test_next_calver_preserves_v_prefix_and_drops_suffix() -> None:
    assert next_calver("v2026.7.1", year=2026, month=7) == "v2026.7.2"
    assert next_calver("2026.7.1-rc1", year=2026, month=7) == "2026.7.2"


def test_next_calver_tolerates_unparseable_current() -> None:
    assert next_calver("garbage", year=2026, month=7) == "2026.7.1"


def test_next_calver_stays_semver_ordered() -> None:
    # no zero-padding -> a valid semver triple that sorts above the pre-migration versions,
    # so marketplace update flows comparing versions keep working across the migration.
    def key(v: str) -> tuple[int, int, int]:
        a, b, c = (int(p) for p in v.split("."))
        return (a, b, c)

    ordered = ["0.1.0", "2026.7.1", "2026.7.2", "2026.8.1", "2026.12.9", "2027.1.1"]
    assert sorted(ordered, key=key) == ordered


def test_looks_calver() -> None:
    assert looks_calver("2026.7.1") and looks_calver("v2027.1.10")
    assert not looks_calver("0.1.0") and not looks_calver("1.4.2") and not looks_calver("x.y")


def test_summarize_calver_uses_date_and_keeps_semantic_bump() -> None:
    s = summarize("2026.7.1", ["feat!: new api"], calver=(2026, 7))
    assert s.version == "2026.7.2"
    assert s.bump == "major"  # semantic level still reported for the changelog reader
    assert s.breaking == ["new api"]


def test_summarize_calver_no_changes_keeps_current() -> None:
    s = summarize("2026.7.1", [], calver=(2026, 7))
    assert s.version == "2026.7.1" and s.bump == "none"
