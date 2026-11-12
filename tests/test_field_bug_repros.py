"""The four field bugs of ADR 0109, replayed as the field ran them: each shipped entry point as a
subprocess (``python3 -E`` on ``af.py`` / ``external_review.py``, a hook fed its JSON payload), on a
repository laid out like the report's repro. The library-level tests sit beside each module's own
tests; these prove the wiring a session actually goes through.

Hermetic: every repo, HOME, state and scratch directory is under ``tmp_path``; ``codex`` and the
JS package managers are stand-in programs on a PATH the test builds, so no real reviewer, registry
or network is ever reached."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_forge import external_review

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
_AF = _PLUGIN / "bin" / "af.py"
_REVIEW_CLI = _PLUGIN / "bin" / "external_review.py"
_COMMIT_GATE = _PLUGIN / "hooks" / "scripts" / "commit_gate.py"
_SESSION_START = _PLUGIN / "hooks" / "scripts" / "session_start.py"
_EXIT_FAILED = 3


def _clean_env(tmp_path: Path, path: str, **extra: str) -> dict[str, str]:
    """An environment built from nothing: no AGENTIC_FORGE_* override, no GIT_* steering, no
    PYTHONPATH, and HOME / state / TMPDIR inside the test's own directory."""
    home, state, scratch = tmp_path / "home", tmp_path / "state", tmp_path / "tmpdir"
    for directory in (home, state, scratch):
        directory.mkdir(exist_ok=True)
    env = {
        "PATH": path,
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "AGENTIC_FORGE_STATE_HOME": str(state),
        "CLAUDE_PLUGIN_ROOT": str(_PLUGIN),
        "LANG": "C.UTF-8",
    }
    env.update(extra)
    return env


def _af(cwd: Path, *args: str, base: Path | None = None) -> subprocess.CompletedProcess[str]:
    """``af.py`` as a skill runs it; HOME, state and TMPDIR go in ``base`` (default: the parent)."""
    env = _clean_env(base or cwd.parent, os.environ.get("PATH", ""))
    return subprocess.run(
        [sys.executable, "-E", str(_AF), *args], cwd=cwd, capture_output=True, text=True,
        check=False, timeout=60, env=env,
    )


def _af_json(cwd: Path, *args: str, base: Path | None = None) -> Any:
    done = _af(cwd, *args, base=base)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _files(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content, encoding="utf-8")
    return root


def _outside_git(path: Path) -> bool:
    here = path.resolve()
    return not any((d / ".git").exists() for d in (here, *here.parents))


# --- 2. a foldered vault (af.py vault-* and the SessionStart hook) ------------------------------


def _foldered_vault(repo: Path) -> Path:
    return _files(repo, {
        "docs/knowledge/MOC.md": "---\ntitle: Root\ntype: moc\n---\n- [[a-decision]]\n",
        "docs/knowledge/decisions/a-decision.md":
            "---\ntitle: A decision\ntype: decision\n---\nThe gateway uses retries.\n",
    })


def test_vault_cli_on_the_foldered_repro_validates_and_recalls_the_folder_note(
    tmp_path: Path,
) -> None:
    repo = _foldered_vault(tmp_path / "repo")
    checked = _af(repo, "vault-validate", "--repo", ".")
    assert checked.returncode == 0, checked.stdout
    assert json.loads(checked.stdout) == {"ok": True, "exists": True, "problems": []}
    notes = _af_json(repo, "vault-recall", "--repo", ".", "--query", "a decision")["notes"]
    assert [n["name"] for n in notes][:1] == ["a-decision"]


def test_vault_cli_from_a_subdirectory_with_repo_reads_the_same_vault(tmp_path: Path) -> None:
    repo = _foldered_vault(tmp_path / "repo")
    below = repo / "src"
    below.mkdir()
    assert _af(below, "vault-validate", "--repo", "..", base=tmp_path).returncode == 0
    notes = _af_json(
        below, "vault-recall", "--repo", "..", "--query", "gateway retries", base=tmp_path
    )["notes"]
    assert notes and notes[0]["name"] == "a-decision"


def test_the_session_start_hook_maps_a_note_kept_in_a_folder(tmp_path: Path) -> None:
    """The field saw a one-line summary: the hook read only the vault's top level."""
    repo = _foldered_vault(tmp_path / "repo")
    done = subprocess.run(
        [sys.executable, str(_SESSION_START)],
        input=json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                          "cwd": str(repo), "session_id": "field-repro"}),
        cwd=repo, capture_output=True, text=True, check=False, timeout=60,
        env=_clean_env(tmp_path, os.environ.get("PATH", "")),
    )
    assert done.returncode == 0, done.stderr
    injected = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "[[a-decision]]" in injected


# --- 3. readiness (af.py handoff-load --type plan) ----------------------------------------------


_PLAN = (
    "---\ntype: plan\nfeature: search\nstatus: in-progress\n{decision}"
    "tasks:\n  - {{id: T1, title: Build indexer}}\n  - {{id: T2, deps: [T1], title: Build API}}\n"
    "---\n# Plan\n"
)


@pytest.mark.parametrize(
    ("decision", "ready", "ready_from"),
    [
        ("review_decision: proceed\n", True, "review_decision"),  # the field report
        ("", False, "status"),  # in-progress alone is a repo's lifecycle word, not readiness
        ("review_decision: revise\n", False, "review_decision"),
        ("review_decision: escalate\n", False, "review_decision"),
    ],
)
def test_handoff_load_on_an_in_progress_plan(
    tmp_path: Path, decision: str, ready: bool, ready_from: str
) -> None:
    repo = tmp_path / "repo"
    plan = repo / "docs" / "sdlc" / "search" / "plan.md"
    plan.parent.mkdir(parents=True)
    text = _PLAN.format(decision=decision)
    plan.write_text(text, encoding="utf-8")
    result = _af_json(repo, "handoff-load", "--path", "docs/sdlc/search/plan.md", "--type", "plan")
    assert (result["ready"], result["ready_from"]) == (ready, ready_from)
    assert result["type"] == "plan"
    assert result["header"]["status"] == "in-progress"
    assert plan.read_text(encoding="utf-8") == text  # readiness is read, never written back


# --- 4. stack-detect -----------------------------------------------------------------------------


def test_stack_detect_finds_a_lone_service_below_a_manifest_less_root(tmp_path: Path) -> None:
    """The exact repro: `mkdir -p r/svc && touch r/svc/pom.xml` was `unknown`."""
    root = _files(tmp_path / "r", {"svc/pom.xml": ""})
    result = _af_json(root, "stack-detect", "--repo", ".")
    assert [(p["stack_id"], p["dir"]) for p in result["profiles"]] == [("jvm", "svc")]
    assert result["primary"]["stack_id"] == "jvm" and result["primary"]["dir"] == "svc"
    assert result["primary"]["toolchain"]["test"] in ("mvn verify", "./mvnw verify")
    assert result["pack_paths"][-1].endswith("jvm-patterns/SKILL.md")
    assert result["toolchain_role"] == "fallback"


def test_stack_detect_on_a_yarn_4_next_package_names_yarn_and_only_its_scripts(
    tmp_path: Path,
) -> None:
    pkg = {
        "packageManager": "yarn@4.12.0",
        "scripts": {"dev": "next dev", "build": "next build", "lint": "next lint", "test": "jest"},
        "dependencies": {"next": "15", "react": "19"},
    }
    root = _files(tmp_path / "web", {"package.json": json.dumps(pkg), "yarn.lock": ""})
    result = _af_json(root, "stack-detect", "--repo", ".")
    toolchain = result["primary"]["toolchain"]
    assert toolchain == {
        "test": "yarn run test", "lint": "yarn run lint", "typecheck": None, "format": None,
    }
    assert "npm" not in result["summary"]
    assert "package.json" in result["declared_gate_sources"]


def test_stack_detect_on_a_test_only_package_names_nothing_else(tmp_path: Path) -> None:
    root = _files(tmp_path / "e2e", {"package.json": '{"scripts": {"test": "playwright test"}}'})
    toolchain = _af_json(root, "stack-detect", "--repo", ".")["primary"]["toolchain"]
    assert toolchain == {"test": "npm run test", "lint": None, "typecheck": None, "format": None}


# --- 1. the external reviewer CLI as a process ---------------------------------------------------

# A stand-in `codex`: logs argv / cwd / stdin, refuses like codex outside a git repo without
# --skip-git-repo-check, then replies as the spec file says.
_CODEX = """\
import hashlib, json, os, pathlib, sys
spec = json.loads(pathlib.Path(SPEC).read_text(encoding="utf-8"))
stdin = sys.stdin.buffer.read()
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin_len": len(stdin),
                          "stdin_sha256": hashlib.sha256(stdin).hexdigest()}) + "\\n")
here = pathlib.Path.cwd().resolve()
if "--skip-git-repo-check" not in sys.argv and not any(
        (d / ".git").exists() for d in (here, *here.parents)):
    sys.stderr.write("Not inside a trusted directory and --skip-git-repo-check was not "
                     "specified.\\n")
    sys.exit(1)
sys.stdout.write(spec["stdout"])
sys.stderr.write(spec["stderr"])
sys.exit(spec["exit"])
"""
_APPROVE = '{"verdict":"approve","findings":[]}'
_CHANGES = '{"verdict":"changes","findings":[{"severity":"major","issue":"real bug"}]}'
_MARKER = "TARGET-MARKER-END"


class _Reviewer:
    def __init__(self, tmp_path: Path, *, stdout: str = _APPROVE, stderr: str = "", code: int = 0):
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.log = tmp_path / "codex-calls.jsonl"
        spec = tmp_path / "codex-spec.json"
        spec.write_text(json.dumps({"stdout": stdout, "stderr": stderr, "exit": code}), "utf-8")
        stub = self.bin / "codex"
        stub.write_text(
            f"#!{sys.executable}\nSPEC = {str(spec)!r}\nLOG = {str(self.log)!r}\n{_CODEX}",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        self.env = _clean_env(tmp_path, str(self.bin))  # PATH holds the stub and nothing else
        self.repo = tmp_path / "repo"  # the reviewed repo: a plain directory, no .git
        self.repo.mkdir()
        self.scratch = tmp_path / "scratch"  # where develop writes the diff and runs from
        self.scratch.mkdir()
        self.target = self.scratch / "diff.txt"
        self.content = "+line of a large diff\n" * 10_000 + _MARKER + "\n"  # ~215 KiB
        self.target.write_text(self.content, encoding="utf-8")

    def run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-E", str(_REVIEW_CLI), "--target", str(self.target), "--kind",
             "code", *extra],
            cwd=self.scratch, env=self.env, capture_output=True, text=True, check=False,
            timeout=120,
        )

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(ln) for ln in self.log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(("reply", "code", "verdict"), [(_APPROVE, 0, "approve"),
                                                         (_CHANGES, 1, "changes")])
def test_a_large_target_from_a_non_git_cwd_is_reviewed_through_stdin(
    tmp_path: Path, reply: str, code: int, verdict: str
) -> None:
    scene = _Reviewer(tmp_path, stdout=reply)
    assert _outside_git(scene.scratch) and _outside_git(scene.repo)
    assert len(scene.content.encode("utf-8")) > 200 * 1024  # past one argv element's 128 KiB
    done = scene.run("--repo", str(scene.repo))
    assert done.returncode == code, done.stderr
    assert f"verdict: {verdict}" in done.stdout
    (call,) = scene.calls()
    assert call["argv"] == ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"]
    assert not any(_MARKER in arg for arg in call["argv"])  # the prompt is not in argv
    prompt = external_review.build_prompt(scene.content, "code").encode("utf-8")
    assert (call["stdin_len"], call["stdin_sha256"]) == (
        len(prompt), hashlib.sha256(prompt).hexdigest()
    )
    assert call["cwd"] == str(scene.repo.resolve())


def test_a_reviewer_that_fails_exits_3_and_is_no_verdict(tmp_path: Path) -> None:
    scene = _Reviewer(tmp_path, stdout="", stderr="auth expired", code=2)
    done = scene.run("--repo", str(scene.repo))
    assert done.returncode == _EXIT_FAILED
    assert "failed (process-failure)" in done.stderr
    assert "not a skip" in done.stderr
    assert "verdict:" not in done.stdout
    assert _MARKER not in done.stderr
    assert len(scene.calls()) == 1


def test_a_reply_with_no_verdict_exits_3(tmp_path: Path) -> None:
    scene = _Reviewer(tmp_path, stdout="Looks fine to me.")
    done = scene.run("--repo", str(scene.repo))
    assert done.returncode == _EXIT_FAILED
    assert "failed (invalid-output)" in done.stderr and "verdict:" not in done.stdout


def test_a_repo_opt_out_holds_from_a_scratch_cwd_and_codex_never_runs(tmp_path: Path) -> None:
    scene = _Reviewer(tmp_path)
    _files(scene.repo, {".agentic-forge/config.json": '{"external_reviewer": {"enabled": false}}'})
    done = scene.run("--repo", str(scene.repo))
    assert done.returncode == 0, done.stderr
    assert "disabled by this repo's config" in done.stdout
    assert scene.calls() == []
    assert not scene.log.exists()


def test_no_repo_from_a_non_git_cwd_is_refused_and_codex_never_runs(tmp_path: Path) -> None:
    scene = _Reviewer(tmp_path)
    done = scene.run()
    assert done.returncode == _EXIT_FAILED
    assert "failed (refused-input)" in done.stderr and "--repo" in done.stderr
    assert scene.calls() == []


def test_the_stub_refuses_like_codex_when_run_without_the_flag(tmp_path: Path) -> None:
    """The control: the stand-in does refuse a non-git cwd, so the reviewed runs above prove the
    flag reached it."""
    scene = _Reviewer(tmp_path)
    done = subprocess.run(
        [str(scene.bin / "codex"), "exec", "-"], input="x", cwd=scene.scratch, env=scene.env,
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert done.returncode == 1 and "Not inside a trusted directory" in done.stderr


# --- 4b. the commit gate hook on a JS package ----------------------------------------------------

_MANAGER = """\
import json, os, sys
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({"tool": NAME, "argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
sys.stdout.write("src/a.js\\n  1:1  error  'x' is not defined  no-undef\\n")
sys.exit(CODE)
"""


def _gate_scene(
    tmp_path: Path, package: dict[str, Any], npm_exit: int
) -> tuple[Path, Path, dict[str, str]]:
    git = shutil.which("git")
    assert git is not None, "the commit gate repro needs git, as the rest of the suite does"
    bin_dir, log = tmp_path / "bin", tmp_path / "managers.jsonl"
    bin_dir.mkdir()
    for name in ("npm", "yarn", "pnpm", "bun", "npx", "corepack"):
        code = npm_exit if name == "npm" else 0
        (bin_dir / name).write_text(
            f"#!{sys.executable}\nLOG = {str(log)!r}\nNAME = {name!r}\nCODE = {code}\n{_MANAGER}",
            encoding="utf-8",
        )
        (bin_dir / name).chmod(0o755)
    repo = _files(tmp_path / "repo", {
        "package.json": json.dumps(package), "yarn.lock": "", "src/a.js": "x\n",
    })
    identity = ["-c", "user.name=qa", "-c", "user.email=qa@example.invalid"]
    for args in (["init", "-q"], ["add", "."], [*identity, "commit", "-qm", "init"]):
        subprocess.run([git, *args], cwd=repo, check=True, capture_output=True)
    (repo / "src" / "a.js").write_text("y\n", encoding="utf-8")
    subprocess.run([git, "add", "src/a.js"], cwd=repo, check=True, capture_output=True)
    env = _clean_env(tmp_path, os.pathsep.join([str(bin_dir), str(Path(git).parent)]))
    return repo, log, env


def _commit_gate(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(repo),
               "session_id": "field-repro", "tool_input": {"command": "git commit -m change"}}
    return subprocess.run(
        [sys.executable, str(_COMMIT_GATE)], input=json.dumps(payload), cwd=repo, env=env,
        capture_output=True, text=True, check=False, timeout=120,
    )


def _ran(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]


_YARN4 = {"packageManager": "yarn@4.12.0", "scripts": {"lint": "eslint .", "test": "jest"}}


def test_the_commit_gate_on_a_yarn_repo_blocks_through_npm_run_lint_never_yarn(
    tmp_path: Path,
) -> None:
    repo, log, env = _gate_scene(tmp_path, _YARN4, npm_exit=1)
    done = _commit_gate(repo, env)
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert "`npm run lint`" in done.stderr and "no-undef" in done.stderr
    ran = _ran(log)
    assert [(r["tool"], r["argv"]) for r in ran] == [("npm", ["run", "lint"])]
    assert ran[0]["cwd"] == str(repo.resolve())


def test_the_commit_gate_on_a_yarn_repo_allows_when_the_lint_script_passes(
    tmp_path: Path,
) -> None:
    repo, log, env = _gate_scene(tmp_path, _YARN4, npm_exit=0)
    done = _commit_gate(repo, env)
    assert done.returncode == 0, done.stderr
    assert [(r["tool"], r["argv"]) for r in _ran(log)] == [("npm", ["run", "lint"])]


@pytest.mark.parametrize(
    "package",
    [
        {"packageManager": "yarn@4.12.0", "scripts": {"test": "playwright test"}},
        {"packageManager": "yarn@4.12.0", "devDependencies": {"eslint": "9"}},
    ],
)
def test_the_commit_gate_without_a_lint_script_runs_nothing(
    tmp_path: Path, package: dict[str, Any]
) -> None:
    repo, log, env = _gate_scene(tmp_path, package, npm_exit=1)
    done = _commit_gate(repo, env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ""  # no fail-open notice either: there was no gate to run
    assert _ran(log) == []
