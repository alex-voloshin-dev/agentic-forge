"""End-to-end checks for the maintainer-skill move (ADR 0105), run the way a maintainer or CI runs
them: the CLIs as real processes, on a copy of the tree, and the shipped plugin read as a user's
session would read it.

The unit tests (test_validation_more, test_dev_cli, test_eval_cli) cover each helper in process.
What only a subprocess shows: the scripts bootstrap their own imports (no PYTHONPATH), the exit
code is what CI sees, and the budget line a broken maintainer skill prints is the shipped one."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_forge.validation import budget_line

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
MAINTAINER_ROOT = REPO / ".claude" / "skills"
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache")


def _run(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a dev CLI as CI does: its own interpreter, no PYTHONPATH (it must find its imports)."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, str(REPO / "dev" / script), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=120,
    )


# --- Tier-0 on a copied mini-repo -----------------------------------------------------------


@pytest.fixture(scope="module")
def _shipped_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One copy of the shipped plugin + the repo marker; each test re-seeds `.claude/skills`."""
    repo = tmp_path_factory.mktemp("mini-repo")
    shutil.copytree(PLUGIN, repo / "plugin", ignore=_IGNORE)
    (repo / "docs" / "architecture").mkdir(parents=True)
    shutil.copy2(REPO / "docs" / "architecture" / "meta-core.md", repo / "docs" / "architecture")
    return repo


@pytest.fixture
def mini_repo(_shipped_copy: Path) -> Path:
    """The copied repo with a fresh copy of the real maintainer skills and the marker in place."""
    skills = _shipped_copy / ".claude" / "skills"
    if skills.exists():
        shutil.rmtree(skills)
    shutil.copytree(MAINTAINER_ROOT, skills, ignore=_IGNORE)
    marker = _shipped_copy / "docs" / "architecture" / "meta-core.md"
    if not marker.exists():
        shutil.copy2(REPO / "docs" / "architecture" / "meta-core.md", marker)
    return _shipped_copy


def _budget_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("listing budget: ")]


def test_validate_script_passes_the_copied_repo_and_counts_only_shipped_skills(
    mini_repo: Path,
) -> None:
    done = _run("validate.py", str(mini_repo / "plugin"), cwd=mini_repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (
        "maintainer skills: 1 validated, not shipped, not in the budget (skill-factory)"
        in done.stdout
    )
    # the copy prints the shipped plugin's own budget line, byte for byte: no maintainer skill in it
    assert _budget_lines(done.stdout) == [budget_line(PLUGIN)]
    assert "16 on-listing skills)" in done.stdout


def test_validate_script_fails_on_a_broken_maintainer_skill(mini_repo: Path) -> None:
    """A dangling reference in the maintainer skill fails the CLI (exit 1) at a repo-relative
    location — and the budget line does not move: the skill is gated, not counted."""
    (mini_repo / ".claude" / "skills" / "skill-factory" / "references" / "eval-loop.md").unlink()
    done = _run("validate.py", str(mini_repo / "plugin"), cwd=mini_repo)
    assert done.returncode == 1, done.stdout
    assert (
        ".claude/skills/skill-factory/SKILL.md: referenced file does not exist: "
        "references/eval-loop.md"
    ) in done.stdout
    assert _budget_lines(done.stdout) == [budget_line(PLUGIN)]


def test_validate_script_fails_on_a_maintainer_skill_missing_its_eval_contract(
    mini_repo: Path,
) -> None:
    (mini_repo / ".claude" / "skills" / "skill-factory" / "evals" / "evals.json").unlink()
    done = _run("validate.py", str(mini_repo / "plugin"), cwd=mini_repo)
    assert done.returncode == 1, done.stdout
    assert ".claude/skills/skill-factory/evals/evals.json: missing required eval contract" in (
        done.stdout
    )


def test_validate_script_fails_on_a_maintainer_skill_that_shadows_a_shipped_one(
    mini_repo: Path,
) -> None:
    """A valid skill copied from the plugin into `.claude/skills`: clean by itself, but the Tier-2
    resolver would read the plugin's copy, so Tier-0 refuses the namesake."""
    shutil.copytree(
        PLUGIN / "skills" / "plan", mini_repo / ".claude" / "skills" / "plan", ignore=_IGNORE
    )
    done = _run("validate.py", str(mini_repo / "plugin"), cwd=mini_repo)
    assert done.returncode == 1, done.stdout
    assert "maintainer skill 'plan' shares its name with a shipped skill" in done.stdout
    assert "maintainer skills: 2 validated" in done.stdout
    assert _budget_lines(done.stdout) == [budget_line(PLUGIN)]


def test_validate_script_ignores_claude_skills_outside_this_repository(mini_repo: Path) -> None:
    """Without the repo marker, `.claude/skills` beside the plugin is a user's own dir: even a
    broken skill there must not fail (or even be read by) the validator."""
    (mini_repo / ".claude" / "skills" / "skill-factory" / "references" / "eval-loop.md").unlink()
    (mini_repo / "docs" / "architecture" / "meta-core.md").unlink()
    done = _run("validate.py", str(mini_repo / "plugin"), cwd=mini_repo)
    assert done.returncode == 0, done.stdout
    assert "maintainer skills:" not in done.stdout
    assert ".claude/skills" not in done.stdout


# --- eval CLIs, dry, as real processes on this repository -----------------------------------


def test_tier1_dry_script_lists_the_maintainer_skill_by_default() -> None:
    done = _run("run_tier1_evals.py", "--runner", "dry", cwd=REPO)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"listing: 16 shipped + 1 maintainer skill(s) (extra roots: {MAINTAINER_ROOT})" in (
        done.stdout
    )
    assert "Dry-run: OK" in done.stdout


def test_tier1_dry_script_knows_the_maintainer_skill_only_with_its_root() -> None:
    """`--skill skill-factory` is a known Tier-1 skill by default; with the shipped listing alone
    it is the unknown-skill warning — the same check, so neither result is vacuous."""
    done = _run("run_tier1_evals.py", "--runner", "dry", "--skill", "skill-factory", cwd=REPO)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "is not a Tier-1 skill" not in done.stderr
    assert "Dry-run: OK" in done.stdout
    shipped = _run(
        "run_tier1_evals.py", "--runner", "dry", "--skill", "skill-factory",
        "--no-maintainer-skills", cwd=REPO,
    )
    assert "warning: --skill 'skill-factory' is not a Tier-1 skill" in shipped.stderr


def test_tier2_dry_script_finds_skill_factory_in_the_maintainer_root() -> None:
    done = _run("run_skill_evals.py", "--runner", "dry", cwd=REPO)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skill-factory: ready" in done.stdout
    assert "Dry-run: OK" in done.stdout


def test_tier2_dry_script_without_the_root_does_not_find_skill_factory(tmp_path: Path) -> None:
    """An explicit, existing, empty --skill-root replaces the default: skill-factory is absent,
    the shipped skills still run."""
    done = _run("run_skill_evals.py", "--runner", "dry", "--skill-root", str(tmp_path), cwd=REPO)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skill-factory" not in done.stdout
    assert "deep-review: ready" in done.stdout


def test_activation_dry_script_checks_the_shipped_listing() -> None:
    done = _run("run_activation_evals.py", "--runner", "dry", cwd=REPO)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Dry-run: OK" in done.stdout


# --- the shipped plugin never points a user at skill-factory --------------------------------

# Eval fixtures ship as inert data (ADR 0105 keeps skill-factory's stand in the plugin); nothing in
# a user's session reads them as instructions.
_FIXTURES = PLUGIN / "eval" / "fixtures"


def _model_facing_markdown() -> list[Path]:
    """What a user's session can load as instructions: skill bodies and references, agents,
    patterns."""
    return sorted(
        p
        for root in ("skills", "agents", "patterns")
        for p in (PLUGIN / root).rglob("*.md")
    )


def test_no_shipped_instruction_names_skill_factory() -> None:
    """A skill, agent or pattern that sends the model to `skill-factory` would dangle in every
    user's session: the skill is not there (ADR 0105)."""
    files = _model_facing_markdown()
    assert len(files) > 50  # the walk found the tree, not an empty glob
    hits = [
        f"{p.relative_to(PLUGIN)}:{n}"
        for p in files
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "skill-factory" in line
    ]
    assert hits == []


def _docstring_nodes(tree: ast.AST) -> set[int]:
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def test_no_shipped_python_emits_skill_factory() -> None:
    """Hooks and the runtime CLIs ship too, and what they print reaches the session (the
    pre-router's context line, session_start's note). Comments and docstrings may explain the
    move; no string the code can emit may name the skill."""
    files = [p for p in sorted(PLUGIN.rglob("*.py")) if _FIXTURES not in p.parents]
    assert any(p.parent.name == "scripts" and p.parent.parent.name == "hooks" for p in files)
    hits: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
                and "skill-factory" in node.value
            ):
                hits.append(f"{path.relative_to(PLUGIN)}:{node.lineno}")
    assert hits == []


def test_the_plugin_readme_says_skill_factory_does_not_ship() -> None:
    """The user-facing README may name it only to say it is not in this plugin — never as an
    example route ("Build me a new skill" -> `skill-factory`, the line ADR 0105 removed)."""
    paragraphs = (PLUGIN / "README.md").read_text(encoding="utf-8").split("\n\n")
    naming = [p for p in paragraphs if "skill-factory" in p]
    assert naming, "the README should tell a user where component authoring went"
    assert all("not shipped" in " ".join(p.split()) for p in naming), naming
