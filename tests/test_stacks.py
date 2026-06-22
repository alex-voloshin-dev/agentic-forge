from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forge import stacks
from agentic_forge.stacks import (
    STACKS,
    UNKNOWN,
    detect,
    format_profile,
    primary,
)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# --- manifest detection ------------------------------------------------------


def test_python_from_pyproject(tmp_path: Path) -> None:
    p = primary(_repo(tmp_path, {"pyproject.toml": "[project]\nname='x'\n"}))
    assert p.stack_id == "python"
    assert p.pack == "python-patterns"
    assert p.toolchain.test == "pytest"
    assert p.toolchain.typecheck == "mypy ."
    assert p.source == "manifest"
    assert p.manifests == ("pyproject.toml",)


def test_python_from_requirements_only(tmp_path: Path) -> None:
    assert primary(_repo(tmp_path, {"requirements.txt": "pytest\n"})).stack_id == "python"


def test_typescript_supersedes_javascript(tmp_path: Path) -> None:
    profiles = detect(_repo(tmp_path, {"tsconfig.json": "{}", "package.json": "{}"}))
    ids = [p.stack_id for p in profiles]
    assert ids == ["typescript"]  # javascript suppressed when tsconfig present
    assert profiles[0].pack == "typescript-patterns"


def test_javascript_from_bare_package_json(tmp_path: Path) -> None:
    p = primary(_repo(tmp_path, {"package.json": "{}"}))
    assert p.stack_id == "javascript"
    assert p.toolchain.typecheck is None  # bare JS has no conventional typecheck


@pytest.mark.parametrize(
    ("manifest", "content", "expected"),
    [
        ("go.mod", "module x\n", "go"),
        ("Cargo.toml", "[package]\n", "rust"),
        ("Gemfile", "source 'x'\n", "ruby"),
        ("composer.json", "{}", "php"),
    ],
)
def test_single_manifest_stacks(
    tmp_path: Path, manifest: str, content: str, expected: str
) -> None:
    # Distinct tmp_path per case (parametrize) so manifests don't accumulate.
    assert primary(_repo(tmp_path, {manifest: content})).stack_id == expected


def test_jvm_from_gradle(tmp_path: Path) -> None:
    assert primary(_repo(tmp_path, {"build.gradle.kts": "plugins {}\n"})).stack_id == "jvm"


def test_dotnet_from_glob(tmp_path: Path) -> None:
    p = primary(_repo(tmp_path, {"App.csproj": "<Project/>"}))
    assert p.stack_id == "dotnet"
    assert p.manifests == ("App.csproj",)  # glob resolves to the real filename


# --- ranking / monorepo ------------------------------------------------------


def test_monorepo_ranks_by_specificity(tmp_path: Path) -> None:
    # python (2) and bare javascript (1) both present -> python primary, both returned.
    profiles = detect(_repo(tmp_path, {"pyproject.toml": "", "package.json": "{}"}))
    assert [p.stack_id for p in profiles] == ["python", "javascript"]


# --- explicit hint precedence ------------------------------------------------


def test_hint_overrides_manifests(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"go.mod": "module x\n", "CLAUDE.md": "stack: python\n"})
    p = primary(repo)
    assert p.stack_id == "python"
    assert p.source == "hint"


def test_hint_alias_and_markdown_bullet(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"AGENTS.md": "- stack: ts\n"})
    assert primary(repo).stack_id == "typescript"


def test_hint_quoted_value(tmp_path: Path) -> None:
    assert primary(_repo(tmp_path, {"CLAUDE.md": 'stack: "rust"\n'})).stack_id == "rust"


def test_unknown_hint_falls_through_to_manifests(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"go.mod": "module x\n", "CLAUDE.md": "stack: cobol\n"})
    assert primary(repo).stack_id == "go"  # bogus hint ignored, manifest wins


def test_no_hint_when_file_absent(tmp_path: Path) -> None:
    # No CLAUDE.md/AGENTS.md at all -> manifest detection path.
    assert primary(_repo(tmp_path, {"Cargo.toml": "[package]\n"})).source == "manifest"


def test_bogus_hint_in_first_file_falls_through_to_second(tmp_path: Path) -> None:
    # CLAUDE.md's stack: value is unrecognised; AGENTS.md has a real one -> the loop continues
    # to the second file (exercises the normalize-failed -> next-file branch).
    repo = _repo(tmp_path, {"CLAUDE.md": "stack: cobol\n", "AGENTS.md": "stack: rust\n"})
    p = primary(repo)
    assert p.stack_id == "rust"
    assert p.source == "hint"


@pytest.mark.parametrize(
    ("hint_line", "expected"),
    [
        ("stack: python", "python"),
        ("- stack: ts", "typescript"),  # bullet + alias
        ("**Stack:** go", "go"),  # bold markers around key/value
        ("STACK = rust", "rust"),  # case-insensitive + `=` delimiter
        ("  stack: java", "jvm"),  # indented + alias
        ('stack: "ruby"', "ruby"),  # quoted value
        ("> stack: node.js", "javascript"),  # blockquote + dotted alias
    ],
)
def test_hint_forms_parsed(tmp_path: Path, hint_line: str, expected: str) -> None:
    assert primary(_repo(tmp_path, {"CLAUDE.md": hint_line + "\n"})).stack_id == expected


@pytest.mark.parametrize(
    "text",
    [
        "## Tech stack\n",  # heading, no delimiter
        "stackoverflow: foo\n",  # different word
        "stack:\npython\n",  # value on the next line must NOT bridge
        "stack:\n  - python\n",  # YAML block list is not an inline value
    ],
)
def test_non_hints_do_not_match(tmp_path: Path, text: str) -> None:
    # None is a valid inline `stack:` hint -> detection falls through to the manifest (go).
    repo = _repo(tmp_path, {"CLAUDE.md": text, "go.mod": "module x\n"})
    p = primary(repo)
    assert p.stack_id == "go"
    assert p.source == "manifest"


# --- unknown -----------------------------------------------------------------


def test_empty_repo_is_unknown(tmp_path: Path) -> None:
    profiles = detect(tmp_path)
    assert profiles == [UNKNOWN]
    assert profiles[0].stack_id == "unknown"
    assert profiles[0].pack is None


def test_detect_accepts_str_path(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    assert primary(str(tmp_path)).stack_id == "go"


# --- formatting --------------------------------------------------------------


def test_format_profile_python(tmp_path: Path) -> None:
    line = format_profile(primary(_repo(tmp_path, {"pyproject.toml": ""})))
    assert "Python" in line and "python-patterns" in line and "pytest" in line


def test_format_profile_unknown_and_no_pack(tmp_path: Path) -> None:
    assert "no pack" in format_profile(primary(_repo(tmp_path, {"go.mod": "module x\n"})))
    unknown_line = format_profile(UNKNOWN)
    assert "Unknown" in unknown_line and "—" in unknown_line


# --- registry invariants -----------------------------------------------------


def test_shipped_packs() -> None:
    packs = {sid: spec.pack for sid, spec in STACKS.items() if spec.pack}
    assert packs == {"python": "python-patterns", "typescript": "typescript-patterns"}


def test_every_spec_has_a_test_command() -> None:
    # A stack with no way to run tests can't gate develop; guard the registry.
    assert all(spec.toolchain.test for spec in STACKS.values())


def test_module_exports_are_importable() -> None:
    for name in stacks.__all__:
        assert hasattr(stacks, name)
