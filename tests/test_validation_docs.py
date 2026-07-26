"""Tests for the Tier-0 doc-sync checks (validation.validate_docs)."""

from __future__ import annotations

from pathlib import Path

from agentic_forge.validation import validate_docs

_REPO = Path(__file__).resolve().parents[1]


def _scaffold(root: Path, modules: list[str], table_rows: list[str],
              adr_files: list[str], index_links: list[str]) -> None:
    """Build a minimal repo tree: lib modules, a meta-core lib table, ADR files + an index."""
    lib = root / "plugin" / "lib" / "agentic_forge"
    lib.mkdir(parents=True)
    (lib / "__init__.py").write_text("", encoding="utf-8")
    for m in modules:
        (lib / f"{m}.py").write_text("", encoding="utf-8")

    arch = root / "docs" / "architecture"
    arch.mkdir(parents=True)
    table = "| Module | Responsibility |\n| --- | --- |\n" + "".join(
        f"| `{r}.py` | does {r} |\n" for r in table_rows
    )
    (arch / "meta-core.md").write_text(table, encoding="utf-8")

    decisions = arch / "decisions"
    decisions.mkdir()
    for f in adr_files:
        (decisions / f).write_text("# adr\n", encoding="utf-8")
    index = "# ADRs\n\n" + "".join(f"- [{ln}]({ln})\n" for ln in index_links)
    (decisions / "README.md").write_text(index, encoding="utf-8")


def test_in_sync_is_ok(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=["alpha", "beta"], table_rows=["alpha", "beta"],
        adr_files=["0001-a.md"], index_links=["0001-a.md"],
    )
    assert validate_docs(tmp_path).ok


def test_module_missing_from_table_errors(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=["alpha", "beta"], table_rows=["alpha"],  # beta undocumented
        adr_files=["0001-a.md"], index_links=["0001-a.md"],
    )
    report = validate_docs(tmp_path)
    assert not report.ok
    assert any("beta.py" in i.message for i in report.errors)


def test_stale_table_row_errors(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=["alpha"], table_rows=["alpha", "ghost"],  # ghost no longer exists
        adr_files=["0001-a.md"], index_links=["0001-a.md"],
    )
    report = validate_docs(tmp_path)
    assert not report.ok
    assert any("ghost.py" in i.message for i in report.errors)


def test_adr_not_indexed_errors(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=["alpha"], table_rows=["alpha"],
        adr_files=["0001-a.md", "0002-b.md"], index_links=["0001-a.md"],  # 0002 missing
    )
    report = validate_docs(tmp_path)
    assert not report.ok
    assert any("0002-b.md" in i.message for i in report.errors)


def test_dangling_index_link_errors(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=["alpha"], table_rows=["alpha"],
        adr_files=["0001-a.md"], index_links=["0001-a.md", "0099-gone.md"],
    )
    report = validate_docs(tmp_path)
    assert not report.ok
    assert any("0099-gone.md" in i.message for i in report.errors)


def test_real_repo_is_in_sync() -> None:
    # The live repo must satisfy its own doc-sync gate.
    assert validate_docs(_REPO).ok


# --- orphaned ADRs (a rule whose rationale cannot be found from the rule) -----


def test_uncited_adr_warns_but_does_not_block(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=[], table_rows=[],
        adr_files=["0042-a.md"], index_links=["0042-a.md"],
    )
    report = validate_docs(tmp_path)
    assert report.ok  # a purely procedural ADR is legitimate -> warning, never an error
    assert any("ADR 0042" in i.message for i in report.warnings)


def test_adr_cited_from_an_artifact_is_not_flagged(tmp_path: Path) -> None:
    _scaffold(
        tmp_path,
        modules=[], table_rows=[],
        adr_files=["0042-a.md"], index_links=["0042-a.md"],
    )
    pattern = tmp_path / "plugin" / "patterns"
    pattern.mkdir(parents=True)
    (pattern / "thing.md").write_text("The rule, because of ADR 0042.\n", encoding="utf-8")
    assert not validate_docs(tmp_path).warnings


def test_a_citation_inside_decisions_does_not_count(tmp_path: Path) -> None:
    """One ADR citing another must not make the cited one look reachable from a rule."""
    _scaffold(
        tmp_path,
        modules=[], table_rows=[],
        adr_files=["0042-a.md", "0043-b.md"], index_links=["0042-a.md", "0043-b.md"],
    )
    decisions = tmp_path / "docs" / "architecture" / "decisions"
    (decisions / "0043-b.md").write_text("# adr\n\nSupersedes ADR 0042.\n", encoding="utf-8")
    warned = {i.message for i in validate_docs(tmp_path).warnings}
    assert any("ADR 0042" in m for m in warned)

