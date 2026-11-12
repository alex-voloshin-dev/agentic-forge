from __future__ import annotations

import json
import os
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


@pytest.mark.parametrize(
    ("manifest", "content", "expected_pack"),
    [
        ("pyproject.toml", "", "python-patterns"),
        ("tsconfig.json", "{}", "typescript-patterns"),
        ("package.json", "{}", "javascript-patterns"),
        ("go.mod", "module x\n", "go-patterns"),
        ("Cargo.toml", "[package]\n", "rust-patterns"),
        ("build.gradle.kts", "plugins {}\n", "jvm-patterns"),
        ("App.csproj", "<Project/>", "dotnet-patterns"),
        ("Gemfile", "source 'x'\n", "ruby-patterns"),
        ("composer.json", "{}", "php-patterns"),
    ],
)
def test_profile_carries_pack(
    tmp_path: Path, manifest: str, content: str, expected_pack: str
) -> None:
    # End-to-end: a detected stack with a shipped pack surfaces it on the profile.
    assert primary(_repo(tmp_path, {manifest: content})).pack == expected_pack


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


def test_format_profile_unknown_and_no_pack() -> None:
    # Every registered stack now ships a pack, so the "no pack" fallback wording is the
    # UNKNOWN profile's (engineering-standards only, no manifest evidence).
    line = format_profile(UNKNOWN)
    assert "Unknown" in line and "no pack" in line and "—" in line


# --- registry invariants -----------------------------------------------------


def test_shipped_packs() -> None:
    # Every registered stack currently ships a `<id>-patterns` pack. Adding a *detection-only*
    # stack later (pack=None) is allowed by design and simply won't appear here.
    packs = {sid: spec.pack for sid, spec in STACKS.items() if spec.pack}
    assert packs == {
        "python": "python-patterns",
        "typescript": "typescript-patterns",
        "javascript": "javascript-patterns",
        "go": "go-patterns",
        "rust": "rust-patterns",
        "jvm": "jvm-patterns",
        "dotnet": "dotnet-patterns",
        "ruby": "ruby-patterns",
        "php": "php-patterns",
    }


def test_every_spec_has_a_test_command() -> None:
    # A stack with no way to run tests can't gate develop; guard the registry.
    assert all(spec.toolchain.test for spec in STACKS.values())


def test_module_exports_are_importable() -> None:
    for name in stacks.__all__:
        assert hasattr(stacks, name)


# --- pack files: what a role READS (ADR 0015 + CLAUDE.md §2) -------------------

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"


def test_pack_path_is_the_pack_skill_file() -> None:
    assert stacks.pack_path("/root", "python-patterns") == Path(
        "/root/skills/python-patterns/SKILL.md"
    )
    assert stacks.pack_path(Path("/root"), stacks.STANDARDS_PACK) == Path(
        "/root/skills/engineering-standards/SKILL.md"
    )


@pytest.mark.parametrize("bad", ["../escape", "", "Python-Patterns", "a/b", "-lead", "x" * 65])
def test_pack_path_rejects_a_bad_name_rather_than_sanitising(bad: str) -> None:
    with pytest.raises(ValueError):
        stacks.pack_path("/root", bad)


def test_pack_paths_read_the_standards_first_then_the_stack_pack(tmp_path: Path) -> None:
    profile = primary(_repo(tmp_path, {"pyproject.toml": ""}))
    assert stacks.pack_paths("/root", profile) == [
        Path("/root/skills/engineering-standards/SKILL.md"),
        Path("/root/skills/python-patterns/SKILL.md"),
    ]
    # No pack -> the standards alone; never an empty list, never a `None` path.
    assert stacks.pack_paths("/root", UNKNOWN) == [
        Path("/root/skills/engineering-standards/SKILL.md")
    ]


def test_every_registered_pack_ships_and_is_off_the_listing() -> None:
    # The registry names packs a role must be able to READ, so each must exist in the shipped tree
    # at the path `pack_path` builds — and each must be `disable-model-invocation: true` (off the
    # listing, CLAUDE.md §2), which is exactly why the path, not the name, is the contract: a role
    # cannot invoke what is not listed.
    from agentic_forge.frontmatter import parse as parse_frontmatter

    names = [stacks.STANDARDS_PACK, *(spec.pack for spec in STACKS.values() if spec.pack)]
    for name in names:
        path = stacks.pack_path(PLUGIN, name)
        assert path.is_file(), name
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        assert fm.get("disable-model-invocation") is True, name


# --- JavaScript / TypeScript: the declared manager, only what package.json declares -------------


def _pkg(**doc: object) -> str:
    return json.dumps(doc)


def test_field_case_a_yarn_next_app_gets_yarn_and_only_its_own_scripts(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "package.json": _pkg(
            packageManager="yarn@4.12.0",
            scripts={"dev": "next dev", "build": "next build", "lint": "next lint"},
            devDependencies={"typescript": "5", "eslint": "9"},
        ),
        "tsconfig.json": "{}",
        "yarn.lock": "",
    })
    tc = primary(repo).toolchain
    assert tc == stacks.Toolchain(
        test=None, lint="yarn run lint", typecheck="yarn run tsc --noEmit", format=None
    )


def test_field_case_a_playwright_only_package_gets_its_test_and_nothing_else(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path, {"package.json": _pkg(scripts={"test": "playwright test"})})
    assert primary(repo).toolchain == stacks.Toolchain(test="npm run test")


@pytest.mark.parametrize(
    ("files", "manager"),
    [
        ({}, "npm"),  # nothing says otherwise
        ({"package-lock.json": "{}"}, "npm"),
        ({"yarn.lock": ""}, "yarn"),
        ({"pnpm-lock.yaml": ""}, "pnpm"),
        ({"bun.lock": ""}, "bun"),
        ({"bun.lockb": ""}, "bun"),
        ({"yarn.lock": "", "package-lock.json": "{}"}, "yarn"),  # lockfile order
    ],
)
def test_the_lockfile_names_the_manager(
    tmp_path: Path, files: dict[str, str], manager: str
) -> None:
    repo = _repo(tmp_path, {"package.json": _pkg(scripts={"lint": "x"}), **files})
    assert primary(repo).toolchain.lint == f"{manager} run lint"


@pytest.mark.parametrize(
    ("declared", "manager"),
    [
        ("pnpm@9.1.0", "pnpm"),
        ("bun@1.1", "bun"),
        ("npm@10.2.0+sha256.abc", "npm"),
        ("Yarn@4", "yarn"),
        ("/tmp/evil@1", "yarn"),  # unknown: never echoed into argv, the lockfile decides
        ("evil", "yarn"),
        (7, "yarn"),
    ],
)
def test_the_package_manager_field_comes_first_and_only_names_a_known_manager(
    tmp_path: Path, declared: object, manager: str
) -> None:
    repo = _repo(tmp_path, {
        "package.json": json.dumps({"packageManager": declared, "scripts": {"lint": "x"}}),
        "yarn.lock": "",
    })
    assert primary(repo).toolchain.lint == f"{manager} run lint"


@pytest.mark.parametrize(
    ("manager", "lockfile", "exec_prefix"),
    [
        ("npm", "package-lock.json", "npm exec --"),
        ("yarn", "yarn.lock", "yarn run"),
        ("pnpm", "pnpm-lock.yaml", "pnpm exec"),
        ("bun", "bun.lock", "bun run"),
    ],
)
def test_a_declared_tool_runs_through_the_manager(
    tmp_path: Path, manager: str, lockfile: str, exec_prefix: str
) -> None:
    repo = _repo(tmp_path, {
        "package.json": _pkg(
            devDependencies={"typescript": "5", "eslint": "9", "prettier": "3"},
            dependencies={"vitest": "1"},
        ),
        "tsconfig.json": "{}",
        lockfile: "",
    })
    assert primary(repo).toolchain == stacks.Toolchain(
        test=f"{exec_prefix} vitest run",
        lint=f"{exec_prefix} eslint .",
        typecheck=f"{exec_prefix} tsc --noEmit",
        format=f"{exec_prefix} prettier --write .",
    )


def test_the_repos_scripts_beat_a_bare_tool(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "package.json": _pkg(
            scripts={"test": "vitest", "lint": "eslint src", "type-check": "tsc -b", "format": "x"},
            devDependencies={"typescript": "5", "eslint": "9", "prettier": "3", "vitest": "1"},
        ),
        "tsconfig.json": "{}",
    })
    assert primary(repo).toolchain == stacks.Toolchain(
        test="npm run test",
        lint="npm run lint",
        typecheck="npm run type-check",
        format="npm run format",
    )


def test_typecheck_script_wins_over_type_check(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "package.json": _pkg(scripts={"typecheck": "a", "type-check": "b"}),
        "tsconfig.json": "{}",
    })
    assert primary(repo).toolchain.typecheck == "npm run typecheck"


def test_jest_is_the_test_runner_when_vitest_is_absent(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"package.json": _pkg(devDependencies={"jest": "29"})})
    assert primary(repo).toolchain.test == "npm exec -- jest"


def test_typescript_without_a_tsconfig_is_no_typecheck(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"package.json": _pkg(devDependencies={"typescript": "5"})})
    p = primary(repo)
    assert p.stack_id == "javascript"
    assert p.toolchain.typecheck is None


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[1, 2]",
        '{"scripts": ["lint"], "devDependencies": "eslint"}',
        '{"scripts": {"lint": 3}}',
        "[" * 100_000,  # deep nesting is not a crash
    ],
)
def test_a_malformed_package_json_declares_nothing(tmp_path: Path, content: str) -> None:
    p = primary(_repo(tmp_path, {"package.json": content}))
    assert p.stack_id == "javascript"
    assert p.toolchain == stacks.Toolchain()


def test_an_oversized_package_json_declares_nothing(tmp_path: Path) -> None:
    big = _pkg(scripts={"lint": "x"}, pad="x" * (1024 * 1024))
    assert primary(_repo(tmp_path, {"package.json": big})).toolchain.lint is None


def test_a_package_json_linked_out_of_the_repo_is_not_read(tmp_path: Path) -> None:
    outside = _repo(tmp_path / "outside", {"package.json": _pkg(scripts={"lint": "x"})})
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").symlink_to(outside / "package.json")
    p = primary(repo)
    assert p.stack_id == "javascript"  # the name is still evidence
    assert p.toolchain.lint is None  # but its content is not read


def test_a_package_json_linked_inside_the_repo_is_read(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"real/package.json": _pkg(scripts={"lint": "x"})})
    (repo / "package.json").symlink_to(repo / "real" / "package.json")
    assert primary(repo).toolchain.lint == "npm run lint"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs a FIFO")
def test_a_pipe_at_a_read_name_never_hangs(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "CLAUDE.md")
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    assert primary(tmp_path).stack_id == "go"


# --- Go / JVM / Terraform ----------------------------------------------------------------------


def test_go_tests_with_the_race_detector_and_vets_without_a_golangci_config(
    tmp_path: Path,
) -> None:
    tc = primary(_repo(tmp_path, {"go.mod": "module x\n"})).toolchain
    assert tc.test == "go test -race ./..."
    assert tc.lint == "go vet ./..."


@pytest.mark.parametrize(
    "config", [".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"]
)
def test_go_lints_with_golangci_when_it_is_configured(tmp_path: Path, config: str) -> None:
    repo = _repo(tmp_path, {"go.mod": "module x\n", config: ""})
    assert primary(repo).toolchain.lint == "golangci-lint run"


@pytest.mark.parametrize(
    ("files", "test"),
    [
        ({"pom.xml": "<project/>"}, "mvn verify"),
        ({"pom.xml": "<project/>", "mvnw": ""}, "./mvnw verify"),
        ({"build.gradle": ""}, "gradle check"),
        ({"build.gradle.kts": "", "gradlew": ""}, "./gradlew check"),
        ({"pom.xml": "<project/>", "build.gradle": "", "gradlew": ""}, "mvn verify"),
        ({"CLAUDE.md": "stack: java\n"}, "mvn verify"),  # hinted, no build file: the convention
    ],
)
def test_jvm_runs_the_phase_that_includes_integration_tests(
    tmp_path: Path, files: dict[str, str], test: str
) -> None:
    p = primary(_repo(tmp_path, files))
    assert p.stack_id == "jvm"
    assert p.toolchain.test == test


def test_field_case_a_terraform_root_with_tests_is_terraform(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "main.tf": "", "modules/net/main.tf": "", "tests/plan.tftest.hcl": "",
    })
    p = primary(repo)
    assert (p.stack_id, p.pack, p.manifests) == ("terraform", None, ("main.tf",))
    assert p.toolchain == stacks.Toolchain(
        test="terraform test",
        lint=None,
        typecheck="terraform init -backend=false && terraform validate",
        format="terraform fmt -check -recursive",
    )
    assert stacks.pack_paths("/root", p) == [Path("/root/skills/engineering-standards/SKILL.md")]


@pytest.mark.parametrize(
    ("files", "test"),
    [
        ({"main.tf": ""}, None),  # no tests, no `terraform test`
        ({"main.tf": "", "unit.tftest.hcl": ""}, "terraform test"),
        ({".terraform.lock.hcl": "", "tests/a.tftest.hcl": ""}, "terraform test"),
        ({"main.tf": "", "tests/readme.md": ""}, None),
    ],
)
def test_terraform_test_only_when_tests_exist(
    tmp_path: Path, files: dict[str, str], test: str | None
) -> None:
    p = primary(_repo(tmp_path, files))
    assert p.stack_id == "terraform"
    assert p.toolchain.test == test


def test_terraform_beside_a_language_is_not_the_primary(tmp_path: Path) -> None:
    profiles = detect(_repo(tmp_path, {"pyproject.toml": "", "infra.tf": ""}))
    assert [p.stack_id for p in profiles] == ["python", "terraform"]


def test_terraform_hint_alias(tmp_path: Path) -> None:
    assert primary(_repo(tmp_path, {"CLAUDE.md": "stack: tf\n"})).stack_id == "terraform"


# --- monorepo scan: a root with no manifest, services one level down --------------------------


def test_field_case_a_service_one_level_down_is_found(tmp_path: Path) -> None:
    profiles = detect(_repo(tmp_path, {"svc/pom.xml": "<project/>"}))
    assert [(p.stack_id, p.dir, p.manifests) for p in profiles] == [("jvm", "svc", ("pom.xml",))]
    assert profiles[0].source == "manifest"


def test_a_polyglot_root_yields_one_profile_per_service(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "README.md": "",
        "api/go.mod": "module x\n",
        "web/package.json": _pkg(scripts={"lint": "x"}),
        "web/tsconfig.json": "{}",
        "worker/pyproject.toml": "",
        "billing/pom.xml": "<project/>",
        "yarn.lock": "",  # the workspace root's lockfile names the service's manager
    })
    profiles = detect(repo)
    assert [(p.stack_id, p.dir) for p in profiles] == [
        ("typescript", "web"), ("go", "api"), ("jvm", "billing"), ("python", "worker"),
    ]
    assert profiles[0].toolchain.lint == "yarn run lint"


def test_one_service_with_two_stacks_and_ts_supersedes_js_per_dir(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "a/pyproject.toml": "", "a/package.json": "{}", "b/package.json": "{}",
        "b/tsconfig.json": "{}",
    })
    assert [(p.stack_id, p.dir) for p in detect(repo)] == [
        ("typescript", "b"), ("python", "a"), ("javascript", "a"),
    ]


def test_a_root_manifest_means_no_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"go.mod": "module x\n", "svc/pom.xml": "<project/>"})
    assert [(p.stack_id, p.dir) for p in detect(repo)] == [("go", ".")]


@pytest.mark.parametrize(
    "skipped",
    [
        ".claude/worktrees/x", ".git", ".venv", ".hidden", "node_modules", "vendor", "target",
        "build", "dist", "out", "bin", "obj", "venv", "env", "__pycache__", "coverage",
    ],
)
def test_the_scan_skips_dot_dirs_and_dependency_or_build_output(
    tmp_path: Path, skipped: str
) -> None:
    repo = _repo(tmp_path, {f"{skipped}/go.mod": "module x\n"})
    if "/" in skipped:  # a manifest two levels down is never reached either
        repo = _repo(tmp_path, {f"{skipped.split('/')[0]}/go.mod": "module x\n"})
    assert detect(repo) == [UNKNOWN]


def test_the_scan_is_one_level_deep(tmp_path: Path) -> None:
    assert detect(_repo(tmp_path, {"services/api/go.mod": "module x\n"})) == [UNKNOWN]


def test_the_scan_does_not_follow_a_linked_directory(tmp_path: Path) -> None:
    outside = _repo(tmp_path / "outside", {"go.mod": "module x\n"})
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "svc").symlink_to(outside, target_is_directory=True)
    assert detect(repo) == [UNKNOWN]


def test_the_scan_examines_a_bounded_number_of_dirs_in_name_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stacks, "_SCAN_MAX_DIRS", 3)
    repo = _repo(tmp_path, {f"d{i}/x.txt": "" for i in range(5)})
    _repo(tmp_path, {"d2/go.mod": "module x\n", "d3/Cargo.toml": ""})
    assert [(p.stack_id, p.dir) for p in detect(repo)] == [("go", "d2")]  # d3 is past the bound


def test_the_scan_reads_a_bounded_number_of_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stacks, "_SCAN_MAX_ENTRIES", 0)
    assert detect(_repo(tmp_path, {"svc/go.mod": "module x\n"})) == [UNKNOWN]


def test_scan_subdirs_false_keeps_detection_to_the_root(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"svc/go.mod": "module x\n"})
    assert detect(repo, scan_subdirs=False) == [UNKNOWN]
    assert primary(repo, scan_subdirs=False) == UNKNOWN


def test_an_unreadable_root_scans_nothing(tmp_path: Path) -> None:
    assert detect(tmp_path / "missing") == [UNKNOWN]


# --- a hint may name several stacks ------------------------------------------------------------


def test_a_hint_names_several_stacks_in_its_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"CLAUDE.md": "stack: go, java\n", "go.mod": "module x\n"})
    profiles = detect(repo)
    assert [(p.stack_id, p.dir, p.source) for p in profiles] == [
        ("go", ".", "hint"), ("jvm", ".", "hint"),
    ]
    assert profiles[0].manifests == ("go.mod",)


@pytest.mark.parametrize(
    ("hint_line", "expected"),
    [
        ("stack: python,typescript", ["python", "typescript"]),
        ("- **stack:** `go` ,  rust", ["go", "rust"]),
        ('stack: "ts", "py"', ["typescript", "python"]),
        ("stack: cobol, rust", ["rust"]),  # an unknown name is skipped, not fatal
        ("stack: ts, typescript, node", ["typescript", "javascript"]),  # deduplicated
        ("stack: go , ", ["go"]),  # a trailing comma ends the list
    ],
)
def test_hint_lists_parsed(tmp_path: Path, hint_line: str, expected: list[str]) -> None:
    repo = _repo(tmp_path, {"CLAUDE.md": hint_line + "\n"})
    assert [p.stack_id for p in detect(repo)] == expected


def test_a_hinted_stack_is_located_one_level_down(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "AGENTS.md": "stack: java, go, rust\n",
        "a/pom.xml": "<project/>", "b/pom.xml": "<project/>", "api/go.mod": "module x\n",
    })
    assert [(p.stack_id, p.dir, p.manifests) for p in detect(repo)] == [
        ("jvm", "a", ("pom.xml",)),
        ("jvm", "b", ("pom.xml",)),
        ("go", "api", ("go.mod",)),
        ("rust", ".", ()),  # found nowhere: the root, no evidence, as a single hint always was
    ]
    root_only = detect(repo, scan_subdirs=False)
    assert [(p.stack_id, p.dir) for p in root_only] == [("jvm", "."), ("go", "."), ("rust", ".")]


def test_a_hint_file_linked_out_of_the_repo_is_not_read(tmp_path: Path) -> None:
    outside = _repo(tmp_path / "outside", {"CLAUDE.md": "stack: rust\n"})
    repo = _repo(tmp_path / "repo", {"go.mod": "module x\n"})
    (repo / "CLAUDE.md").symlink_to(outside / "CLAUDE.md")
    assert primary(repo).source == "manifest"


# --- the toolchain is a fallback; where the repo declares its gate -----------------------------


def test_the_summary_says_the_commands_are_fallbacks_and_where_a_service_lives(
    tmp_path: Path,
) -> None:
    profiles = detect(_repo(tmp_path, {"svc/go.mod": "module x\n", "web/pyproject.toml": ""}))
    line = stacks.format_profiles(profiles)
    assert line.startswith("stack=Go [go] in svc/ via manifest")
    assert "fallbacks: the repo's declared gate wins" in line
    assert line.endswith("; also: python (web)")
    assert stacks.format_profiles(profiles[:1]) == format_profile(profiles[0])
    assert stacks.TOOLCHAIN_ROLE == "fallback"


def test_declared_gate_sources(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {
        "AGENTS.md": "", ".github/workflows/ci.yml": "", ".github/workflows/rel.yaml": "",
        ".github/workflows/notes.txt": "", "svc/Makefile": "", "svc/go.mod": "module x\n",
        "other/Makefile": "",  # not a profile directory
    })
    outside = _repo(tmp_path.parent / f"{tmp_path.name}-out", {"Makefile": ""})
    (repo / "Makefile").symlink_to(outside / "Makefile")  # resolves out of the repo: left out
    assert stacks.declared_gate_sources(repo, detect(repo)) == [
        ".github/workflows/ci.yml", ".github/workflows/rel.yaml", "AGENTS.md", "svc/Makefile",
    ]
    assert stacks.declared_gate_sources(repo) == [
        ".github/workflows/ci.yml", ".github/workflows/rel.yaml", "AGENTS.md",
    ]


def test_declared_gate_sources_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stacks, "_GATE_SOURCES_MAX", 2)
    repo = _repo(tmp_path, {f".github/workflows/w{i}.yml": "" for i in range(5)})
    assert stacks.declared_gate_sources(repo) == [
        ".github/workflows/w0.yml", ".github/workflows/w1.yml",
    ]


def test_a_long_hint_list_stays_linear(tmp_path: Path) -> None:
    """The commit gate reads the hint; a list of names must not backtrack (ADR 0104)."""
    import time

    line = "stack: " + "go, " * 60_000 + "!\n"
    _repo(tmp_path, {"CLAUDE.md": line})
    started = time.monotonic()
    assert [p.stack_id for p in detect(tmp_path)] == ["go"]
    assert time.monotonic() - started < 2
