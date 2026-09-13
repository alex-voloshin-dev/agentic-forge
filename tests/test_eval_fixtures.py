"""Every eval contract's fixture wiring resolves on the real tree (audit C6b/C6d).

`dev/validate.py` checks a skill contract's `files` exist; the Tier-2 runners check wiring only for
the component they are about to run. This walks BOTH contract families up front: every `files`
entry is a file under `plugin/`, no case lands two fixtures on one sandbox path, the `tree/`
layouts materialize as the prompts describe them, and no trigger prompt still carries a literal
`X` placeholder (two did — a router cannot be measured on "prior art for X")."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentic_forge.agent_eval import materialize_fixtures
from agentic_forge.evals import eval_case_problems, fixture_dest, load_evals

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
CONTRACTS = sorted(PLUGIN.glob("skills/*/evals/evals.json")) + sorted(
    PLUGIN.glob("agents/evals/*.evals.json")
)
PACKS = ("python", "typescript", "javascript", "go", "rust", "jvm", "dotnet", "php", "ruby")


def _label(path: Path) -> str:
    return path.relative_to(PLUGIN).as_posix()


def test_contracts_were_found() -> None:
    assert len(CONTRACTS) > 20  # both families walked; an empty glob must not pass vacuously


@pytest.mark.parametrize("contract", CONTRACTS, ids=_label)
def test_every_files_entry_resolves_and_lands_uniquely(contract: Path) -> None:
    cases = load_evals(contract).get("evals") or []
    for case in cases:
        for rel in case.get("files") or []:
            assert (PLUGIN / rel).is_file(), f"{_label(contract)} case {case.get('id')}: {rel}"
    problems = [p for p in eval_case_problems(_label(contract), cases, PLUGIN) if "fixture" in p]
    assert problems == []


@pytest.mark.parametrize("contract", CONTRACTS, ids=_label)
def test_trigger_prompts_carry_no_literal_placeholder(contract: Path) -> None:
    triggers = load_evals(contract).get("triggers") or {}
    prompts = list(triggers.get("should_trigger") or [])
    prompts += list(triggers.get("should_not_trigger") or [])
    assert [p for p in prompts if re.search(r"\bX\b", p)] == []


def test_tree_fixtures_seed_the_layout_the_prompts_describe(tmp_path: Path) -> None:
    """A stack pack's case 1 lands as a real crate (`src/lib.rs`, not `lib.rs`) and the
    skill-factory skeleton as `plugin/agents/...` — the `tree/` marker on the real contracts."""
    rust = load_evals(PLUGIN / "skills" / "rust-patterns" / "evals" / "evals.json")["evals"][0]
    wd = tmp_path / "rust"
    wd.mkdir()
    materialize_fixtures(PLUGIN, rust["files"], wd)
    assert (wd / "Cargo.toml").is_file() and (wd / "src" / "lib.rs").is_file()
    assert (wd / "tests" / "parse.rs").is_file()

    factory = load_evals(PLUGIN / "skills" / "skill-factory" / "evals" / "evals.json")["evals"]
    wd = tmp_path / "factory"
    wd.mkdir()
    for case in factory:
        materialize_fixtures(PLUGIN, case["files"], wd)
    assert (wd / "plugin" / "agents" / "example-agent.md").is_file()
    assert (wd / "plugin" / "skills" / "example-skill" / "evals" / "evals.json").is_file()
    assert (wd / "tests" / "test_example.py").is_file()
    # the real schema, seeded by name — no copy that could drift from plugin/schemas/
    assert (wd / "evals.schema.json").read_text(encoding="utf-8") == (
        PLUGIN / "schemas" / "evals.schema.json"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("pack", PACKS)
def test_seeded_stack_fixtures_carry_a_test_to_weaken(pack: str) -> None:
    """"No existing test is weakened" was vacuous on `files: []`; every pack now seeds a manifest,
    a source file and an existing test."""
    case = load_evals(PLUGIN / "skills" / f"{pack}-patterns" / "evals" / "evals.json")["evals"][0]
    dests = [fixture_dest(rel) for rel in case["files"]]
    assert len(dests) >= 3, dests
    assert any(re.search(r"test|spec", d, re.IGNORECASE) for d in dests), dests
