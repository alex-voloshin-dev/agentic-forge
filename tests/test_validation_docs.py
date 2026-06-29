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
