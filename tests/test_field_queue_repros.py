"""The field queue's items 7 to 15 (ADR 0110), replayed as the field ran them: each shipped entry
point as a real process (a hook fed its JSON payload, ``python3 -E`` on ``af.py``), on a repository
laid out like the report's repro. The library and in-process tests sit beside each module; these
prove the wiring a session goes through, in the places the existing end-to-end tests do not reach:

- the merge gate inside a real checkout (a commit, a feature branch, an ``origin`` on github.com and
  its ``origin/HEAD``), so the local preflight runs after the gate as it does in the field;
- ``artifact-home`` on the full field layout, with every ``.shell`` it prints run through bash;
- ``pr-review`` with mentions in the evidence's code, and its printed post command run as printed;
- the SessionStart note's new wording, through the hook;
- ``stack-detect`` with ``.tflint.hcl``, and the commit gate on that repository.

Hermetic: every repo, HOME, state and scratch directory is under ``tmp_path``; ``gh``, ``codex``,
``tflint`` and ``terraform`` are stand-in programs on a PATH the test builds, which holds no other
program than ``git`` and ``python3``, so nothing reaches the network or a real tool."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
_AF = _PLUGIN / "bin" / "af.py"
_HOOKS = _PLUGIN / "hooks" / "scripts"
_MERGE_PREFLIGHT = _HOOKS / "merge_preflight.py"
_SESSION_START = _HOOKS / "session_start.py"
_COMMIT_GATE = _HOOKS / "commit_gate.py"
_ZW = "\u200b"
_HEAD = "b" * 40
_IDENTITY = ["-c", "user.name=qa", "-c", "user.email=qa@example.invalid"]
_NOTICE = "agentic-forge merge gate not applied, the merge is allowed: "


def _which(name: str) -> str:
    found = shutil.which(name)
    assert found is not None, f"these repros need {name}, as the rest of the suite does"
    return found


def _git_bin() -> str:
    return _which("git")


def _tools_dir(tmp_path: Path) -> Path:
    """A directory holding only ``git`` and ``python3`` (links to the real ones): with the stub
    directory before it, it is the whole PATH, so no installed ``codex``, ``terraform`` or ``gh``
    can ever be found."""
    tools = tmp_path / "tools"
    if not tools.exists():
        tools.mkdir()
        (tools / "git").symlink_to(_git_bin())
        (tools / "python3").symlink_to(_which("python3"))
    return tools


def _env(tmp_path: Path, stubs: Path | None = None, **extra: str) -> dict[str, str]:
    """An environment built from nothing: no AGENTIC_FORGE_* override, no GIT_* or GH_* steering,
    no PYTHONPATH, and HOME / state / TMPDIR inside the test's own directory."""
    home, state, scratch = tmp_path / "home", tmp_path / "state", tmp_path / "tmpdir"
    for directory in (home, state, scratch):
        directory.mkdir(exist_ok=True)
    path = [str(_tools_dir(tmp_path))]
    if stubs is not None:
        path.insert(0, str(stubs))
    env = {
        "PATH": os.pathsep.join(path),
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "AGENTIC_FORGE_STATE_HOME": str(state),
        "CLAUDE_PLUGIN_ROOT": str(_PLUGIN),
        "LANG": "C.UTF-8",
    }
    env.update(extra)
    return env


def _stub(bin_dir: Path, name: str, body: str) -> None:
    """A stand-in program: ``body`` is Python run with ``LOG`` (a JSON-lines file) defined."""
    bin_dir.mkdir(exist_ok=True)
    log = bin_dir.parent / f"{name}.calls.jsonl"
    program = bin_dir / name
    program.write_text(
        f"#!{sys.executable} -S\nimport json, os, sys\nLOG = {str(log)!r}\n"
        "with open(LOG, 'a', encoding='utf-8') as fh:\n"
        "    fh.write(json.dumps({'argv0': sys.argv[0], 'argv': sys.argv[1:],"
        " 'cwd': os.getcwd()}) + '\\n')\n" + body,
        encoding="utf-8",
    )
    program.chmod(0o755)


def _calls(bin_dir: Path, name: str) -> list[dict[str, Any]]:
    log = bin_dir.parent / f"{name}.calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [_git_bin(), "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _files(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")
    return root


def _commit_all(repo: Path, message: str = "init") -> None:
    _git(repo, "add", "-A")
    _git(repo, *_IDENTITY, "commit", "-qm", message)


# --- 8. the merge gate, in a real checkout ------------------------------------------------------

_GH = """\
with open(os.environ["GH_STUB_CONFIG"], encoding="utf-8") as fh:
    config = json.load(fh)
kind = {("pr", "view"): "view", ("api", "graphql"): "graphql"}.get(tuple(sys.argv[1:3]), "other")
answer = config.get(kind, {"exit": 1, "stderr": "unexpected call"})
sys.stdout.write(answer.get("stdout", ""))
sys.stderr.write(answer.get("stderr", ""))
sys.exit(answer.get("exit", 0))
"""


def _pr(*, merge_state: str, checks: str | None, open_threads: int = 0) -> dict[str, Any]:
    """What `gh` answers, `gh pr view` and the watcher's GraphQL query, for acme/infra#7."""
    thread = {"id": "T", "isResolved": False, "comments": {"nodes": [
        {"body": "this breaks prod", "path": "main.tf", "line": 1, "authorAssociation": "MEMBER",
         "author": {"login": "alice", "__typename": "User"}}]}}
    return {
        "view": {"stdout": json.dumps({"number": 7, "mergeStateStatus": merge_state,
                                       "url": "https://github.com/acme/infra/pull/7"})},
        "graphql": {"stdout": json.dumps({"data": {"repository": {"pullRequest": {
            "number": 7, "isDraft": False, "state": "OPEN", "mergeable": "MERGEABLE",
            "headRefName": "feat/x", "headRefOid": "a" * 40, "baseRefName": "master",
            "isCrossRepository": False,
            "reviewThreads": {"pageInfo": {"hasNextPage": False},
                              "nodes": [thread] * open_threads},
            "commits": {"nodes": [{"commit": {
                "statusCheckRollup": None if checks is None else {"state": checks}}}]},
        }}}})},
    }


_UNSTABLE = _pr(merge_state="UNSTABLE", checks="FAILURE", open_threads=1)  # the field's PR
_CLEAN = _pr(merge_state="CLEAN", checks="SUCCESS")
_NO_CI = _pr(merge_state="CLEAN", checks=None)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """The session's checkout: a commit on master, ``origin`` on github.com with its ``origin/HEAD``
    (so the local preflight has a base to compare), and a feature branch checked out."""
    repo = _files(tmp_path / "infra", {"main.tf": 'resource "null_resource" "x" {}\n'})
    _git(repo, "init", "-q", "-b", "master")
    _commit_all(repo)
    _git(repo, "remote", "add", "origin", "https://github.com/acme/infra.git")
    _git(repo, "update-ref", "refs/remotes/origin/master", "HEAD")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    return repo


def _merge_hook(
    tmp_path: Path, repo: Path, command: str, answers: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    stubs = tmp_path / "stubs"
    if not (stubs / "gh").exists():
        _stub(stubs, "gh", _GH)
    config = tmp_path / "gh-config.json"
    config.write_text(json.dumps(answers), encoding="utf-8")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(repo),
               "session_id": "field-queue", "tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(_MERGE_PREFLIGHT)], input=json.dumps(payload), cwd=repo,
        env=_env(tmp_path, stubs, GH_STUB_CONFIG=str(config)),
        capture_output=True, text=True, check=False, timeout=60,
    )


def _gh_argv(tmp_path: Path) -> list[list[str]]:
    return [call["argv"] for call in _calls(tmp_path / "stubs", "gh")]


def test_the_field_merge_is_held_with_its_reasons(tmp_path: Path, checkout: Path) -> None:
    """f993da46: UNSTABLE (the red check is not required), so GitHub merges it; the watcher would
    not. The `2>&1` is the shell's, not a PR argument."""
    done = _merge_hook(tmp_path, checkout, "gh pr merge 7 --squash 2>&1", _UNSTABLE)
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert done.stdout == ""
    assert "#7: merge held: checks: FAILURE; 1 unresolved review thread(s)." in done.stderr
    assert "mergeStateStatus UNSTABLE" in done.stderr
    assert "this breaks prod" not in done.stderr and "alice" not in done.stderr
    calls = _calls(tmp_path / "stubs", "gh")
    assert [c["argv0"] for c in calls] == [str(tmp_path / "stubs" / "gh")] * 2  # absolute path
    view, graphql = (c["argv"] for c in calls)
    assert view == ["pr", "view", "7", "--json", "number,url,mergeStateStatus"]
    assert graphql[:4] == ["api", "graphql", "--hostname", "github.com"]
    assert {"owner=acme", "name=infra", "number=7"} <= set(graphql)
    assert {c["cwd"] for c in calls} == {str(checkout)}


def test_the_same_merge_of_a_clean_pr_goes_through_silently(
    tmp_path: Path, checkout: Path
) -> None:
    done = _merge_hook(tmp_path, checkout, "gh pr merge 7 --squash 2>&1", _CLEAN)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert len(_gh_argv(tmp_path)) == 2


def test_watching_the_checks_before_the_merge_fails_open_without_asking_gh(
    tmp_path: Path, checkout: Path
) -> None:
    """The PR changes state while `--watch` runs, so its state now says nothing about the merge."""
    done = _merge_hook(tmp_path, checkout, "gh pr checks 7 --watch && gh pr merge 7", _UNSTABLE)
    assert done.returncode == 0, done.stderr
    notice = done.stderr.strip()
    assert notice.startswith(_NOTICE)
    assert "`gh pr checks` runs before the merge" in notice
    assert json.loads(done.stdout)["systemMessage"] == notice  # what reaches the operator
    assert _gh_argv(tmp_path) == []


def test_a_pr_with_no_checks_merges_with_the_no_ci_notice(
    tmp_path: Path, checkout: Path
) -> None:
    done = _merge_hook(tmp_path, checkout, "gh pr merge 7 --squash 2>&1", _NO_CI)
    assert done.returncode == 0, done.stderr
    notice = (
        "agentic-forge merge gate: #7 has no checks at all, so it merges without a CI signal "
        "(the PR watcher would hold it)"
    )
    assert done.stderr.strip() == notice
    said = json.loads(done.stdout)
    assert said["systemMessage"] == notice
    assert said["hookSpecificOutput"]["additionalContext"] == notice


def test_the_no_ci_notice_and_the_local_preflight_warning_both_reach_the_operator(
    tmp_path: Path, checkout: Path
) -> None:
    """After the gate lets a PR through the local preflight still runs; one message says both."""
    _git(checkout, "checkout", "-q", "master")
    (checkout / "local.tf").write_text("# not pushed\n", encoding="utf-8")
    _commit_all(checkout, "local only")
    _git(checkout, "checkout", "-q", "feat/x")
    done = _merge_hook(tmp_path, checkout, "gh pr merge 7", _NO_CI)
    assert done.returncode == 0, done.stderr
    message = json.loads(done.stdout)["systemMessage"]
    first, second = message.split("\n")
    assert first.startswith("agentic-forge merge gate: #7 has no checks at all")
    assert second.startswith("pre-merge: local 'master' is ahead of its upstream by 1")


def test_a_merge_of_a_pr_on_a_foreign_host_never_contacts_it(
    tmp_path: Path, checkout: Path
) -> None:
    done = _merge_hook(
        tmp_path, checkout, "gh pr merge https://attacker.example/o/r/pull/1", _UNSTABLE
    )
    assert done.returncode == 0, done.stderr
    notice = done.stderr.strip()
    assert notice.startswith(_NOTICE)
    assert "neither github.com nor this checkout's origin" in notice
    assert "attacker" not in notice
    assert json.loads(done.stdout)["systemMessage"] == notice
    assert _gh_argv(tmp_path) == []


# --- 10. artifact-home on the field's monorepo -------------------------------------------------

_HOSTILE = "$(touch PWNED)"


def _field_monorepo(repo: Path) -> Path:
    """The report's layout: features in lifecycle folders, a PRD that opens with a metadata table,
    adr-001..066 and ADR-G01..G14 side by side under features/architecture, a feature-local adr/,
    and a parent folder whose name is a command substitution, holding a feature of the same slug."""
    files = {
        "features/in-progress/export/prd.md":
            "# Export\n\n| Field | Value |\n| --- | --- |\n| **Status** | Draft |\n"
            "| **Owner** | platform |\n\n## Goals\n\n- export\n",
        "features/implemented/old/prd.md": "# Old\n",
        "features/implemented/old/adr/adr-001-old.md": "# ADR\n",
        f"features/{_HOSTILE}/export/prd.md": "# Hostile\n",
        f"features/{_HOSTILE}/export/adr/adr-099-hostile.md": "# ADR\n",
    }
    files.update({f"features/architecture/adr/adr-{n:03d}-record.md": "# ADR\n"
                  for n in range(1, 67)})
    files.update({f"features/architecture/global/ADR-G{n:02d}-global.md": "# ADR\n"
                  for n in range(1, 15)})
    _files(repo, files)
    _git(repo, "init", "-q")
    _commit_all(repo)
    return repo


def _artifact_home(tmp_path: Path, repo: Path, kind: str) -> dict[str, Any]:
    done = subprocess.run(
        [sys.executable, "-E", str(_AF), "artifact-home", "--repo", str(repo), "--slug", "export",
         "--kind", kind],
        cwd=tmp_path, env=_env(tmp_path), capture_output=True, text=True, check=False, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def _shells(node: Any) -> list[str]:
    """Every ``shell`` string anywhere in the output, in document order."""
    if isinstance(node, dict):
        found = [node["shell"]] if isinstance(node.get("shell"), str) else []
        for key, value in node.items():
            if key != "shell":
                found += _shells(value)
        return found
    if isinstance(node, list):
        return [shell for item in node for shell in _shells(item)]
    return []


def test_artifact_home_on_the_field_monorepo_finds_the_folder_and_the_series(
    tmp_path: Path,
) -> None:
    repo = _field_monorepo(tmp_path / "repo")
    result = _artifact_home(tmp_path, repo, "adr")
    assert result["feature_dir"] == "features/in-progress/export" and result["detected"] is True
    assert result["feature_candidates"] == ["features/in-progress/export"]
    assert result["existing"] == ["prd.md"]
    assert result["documents"]["prd"]["format"] == "foreign"  # the markdown-table PRD
    adr = result["adr"]
    assert (adr["dir"], adr["scope"]) == ("features/architecture/adr", "shared")
    assert (adr["highest"], adr["next_id"]) == ("adr-066", "adr-067")
    assert result["artifact"]["path"] == "features/architecture/adr/adr-067-<title>.md"
    series = {s["dir"]: s for s in adr["series"]}
    assert series["features/architecture/global"]["highest"] == "ADR-G14"
    assert series["features/architecture/global"]["next_id"] == "ADR-G15"
    assert series["features/architecture/global"]["count"] == 14
    assert series["features/architecture/adr"]["count"] == 66
    assert series["features/implemented/old/adr"]["scope"] == "feature"
    assert adr["series_count"] == 3  # the hostile folder's series is not one of them
    assert result["ambiguous"] is True
    why = result["ambiguities"]
    assert any(w.startswith(f"skipped a feature folder 'features/{_HOSTILE}/export'") for w in why)
    assert any("2 ADR series are equally near" in w and "ADR-GNN-<title>.md" in w for w in why)
    assert any("feature-local ADR folders both exist" in w for w in why)


def test_every_printed_command_runs_through_bash_and_nothing_else_runs(tmp_path: Path) -> None:
    """The skills run the `.shell` strings verbatim: from a root whose path has a space and a quote,
    with a sibling folder named to run a command, every one of them must run only what it says."""
    repo = _field_monorepo(tmp_path / "the infra's repo")
    (repo / "features/in-progress/export/prd.md").write_text("# Edited\n", encoding="utf-8")
    stubs = tmp_path / "stubs"
    _stub(stubs, "codex", "sys.stdin.read()\nsys.exit(1)\n")
    shells: list[str] = []
    for kind in ("research", "prd", "design", "plan", "ux", "adr"):
        result = _artifact_home(tmp_path, repo, kind)
        shells += [s for s in _shells(result) if s not in shells]
    assert len(shells) >= 30  # five documents' commands, at least
    assert not any("PWNED" in shell for shell in shells)  # the hostile path is never proposed
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for shell in shells:
        done = subprocess.run(
            [_which("bash"), "-c", shell], cwd=elsewhere, env=_env(tmp_path, stubs),
            capture_output=True, text=True, check=False, timeout=120,
        )
        assert done.returncode not in (2, 126, 127), (shell, done.stderr)  # a shell usage error
        assert "Traceback" not in done.stderr, (shell, done.stderr)
        assert "syntax error" not in done.stderr, (shell, done.stderr)
    assert sorted(p.name for p in tmp_path.rglob("PWNED")) == []
    assert _calls(stubs, "codex")  # the external-review command did run, against the stub


# --- 9/11. pr-review: mentions in the evidence's code, and the post command as printed ----------

_DIFF = """\
diff --git a/main.tf b/main.tf
index 1111111..2222222 100644
--- a/main.tf
+++ b/main.tf
@@ -1,2 +1,3 @@
 a
+b
 c
"""

_PR_GH = f"""\
if sys.argv[1:3] == ["pr", "diff"]:
    sys.stdout.write({_DIFF!r})
    sys.exit(0)
if sys.argv[1:3] == ["api", "-X"]:
    sys.exit(0)  # the post: recorded, nothing sent
print(json.dumps({{"data": {{"viewer": {{"login": "rev"}}, "repository": {{"pullRequest": {{
    "number": 7, "state": "OPEN", "headRefOid": {_HEAD!r}, "author": {{"login": "ann"}}}}}}}}}}))
"""

_MENTIONS = ("alice", "bob", "carol", "dave", "erin", "org/team")

_EVIDENCE_FINDINGS = {
    "verdict": "changes",
    "findings": [
        {"severity": "major", "location": "main.tf:2", "issue": "b breaks the plan",
         "suggestion": "Drop b.",
         "evidence": "`@alice` wrote ``x @bob y`` and\n```\n@carol\n```\n<code>@dave</code>"},
        {"severity": "minor", "location": "variables.tf:1", "issue": "Not in the diff.",
         "suggestion": "Look.", "evidence": "see `@erin` and `@org/team`"},
    ],
}


def _pr_scene(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/infra.git")
    stubs = tmp_path / "stubs"
    _stub(stubs, "gh", _PR_GH)
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps(_EVIDENCE_FINDINGS), encoding="utf-8")
    return repo, findings, _env(tmp_path, stubs)


def _pr_review(
    cwd: Path, repo: Path, findings: Path, out: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-E", str(_AF), "pr-review", "--repo", str(repo), "--pr", "7",
         "--head", _HEAD, "--findings-json", str(findings), "--out", out],
        cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=60,
    )


def test_a_mention_in_the_evidences_code_is_neutralised_in_the_payload(tmp_path: Path) -> None:
    repo, findings, env = _pr_scene(tmp_path)
    out = tmp_path / "tmpdir" / "review.json"  # --out goes under the repo or TMPDIR
    done = _pr_review(tmp_path, repo, findings, str(out), env)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert (result["inline"], result["in_body"]) == (1, 1)
    payload = json.loads(out.read_text(encoding="utf-8"))
    [comment] = payload["comments"]
    texts = {"inline": comment["body"], "body": payload["body"]}
    for where, text in texts.items():
        for login in _MENTIONS:
            assert f"@{login}" not in text, (where, login)
    assert f"`@{_ZW}alice`" in comment["body"] and f"``x @{_ZW}bob y``" in comment["body"]
    assert f"```\n@{_ZW}carol\n```" in comment["body"] and f"@{_ZW}dave" in comment["body"]
    assert f"`@{_ZW}erin`" in payload["body"] and f"`@{_ZW}org/team`" in payload["body"]


def test_the_printed_post_command_runs_as_printed(tmp_path: Path) -> None:
    repo, findings, env = _pr_scene(tmp_path)
    out = tmp_path / "tmpdir" / "review.json"  # --out goes under the repo or TMPDIR
    result = json.loads(_pr_review(tmp_path, repo, findings, str(out), env).stdout)
    assert [c["argv"][:2] for c in _calls(tmp_path / "stubs", "gh")] == [
        ["api", "graphql"], ["pr", "diff"], ["api", "graphql"]
    ]  # it posted nothing itself
    post = result["post"]
    assert post["argv"] == [
        "gh", "api", "-X", "POST", "repos/acme/infra/pulls/7/reviews", "--input", str(out)
    ]
    done = subprocess.run([_which("bash"), "-c", post["shell"]], cwd=tmp_path / "home", env=env,
                          capture_output=True, text=True, check=False, timeout=60)
    assert done.returncode == 0, done.stderr
    assert _calls(tmp_path / "stubs", "gh")[-1]["argv"] == post["argv"][1:]


@pytest.mark.parametrize("existing", [True, False])
def test_a_relative_out_into_the_git_hooks_is_refused_before_gh_is_asked(
    tmp_path: Path, existing: bool
) -> None:
    """The field form: `--out .git/hooks/pre-commit`, run from inside the checkout."""
    repo, findings, env = _pr_scene(tmp_path)
    hook = repo / ".git" / "hooks" / "pre-commit"
    if existing:
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)
    else:
        hook.unlink(missing_ok=True)
    done = _pr_review(repo, repo, findings, ".git/hooks/pre-commit", env)
    assert done.returncode == 1, (done.stdout, done.stderr)
    assert done.stdout == "" and "Traceback" not in done.stderr
    assert done.stderr.startswith("af.py: pr-review: ")
    if existing:
        assert hook.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"
    else:
        assert not hook.exists()
    assert _calls(tmp_path / "stubs", "gh") == []


# --- 7. the SessionStart note, through the hook -------------------------------------------------


def _session_start(
    tmp_path: Path, repo: Path, source: str
) -> subprocess.CompletedProcess[str]:
    payload = {"hook_event_name": "SessionStart", "source": source, "cwd": str(repo),
               "session_id": "field-queue"}
    return subprocess.run(
        [sys.executable, str(_SESSION_START)], input=json.dumps(payload), cwd=repo,
        env=_env(tmp_path), capture_output=True, text=True, check=False, timeout=60,
    )


@pytest.mark.parametrize("source", ["startup", "resume", "compact"])
def test_the_injected_note_scales_the_process_and_no_longer_says_especially(
    tmp_path: Path, source: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    done = _session_start(tmp_path, repo, source)
    assert done.returncode == 0, done.stderr
    injected = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "scales its process" in injected
    assert "especially" not in injected.lower()
    assert "straightforward" not in injected.lower()
    assert "invoke that skill" in injected


def test_the_documented_off_switch_silences_the_note_through_the_hook(tmp_path: Path) -> None:
    repo = _files(tmp_path / "repo", {
        ".agentic-forge/config.json": json.dumps({"routing_note": {"enabled": False}}),
    })
    done = _session_start(tmp_path, repo, "startup")
    assert done.returncode == 0, done.stderr
    assert "scales its process" not in done.stdout


# --- 14. Terraform: stack-detect and the commit gate --------------------------------------------


def _terraform_root(repo: Path, *, tflint: bool) -> Path:
    files = {
        "main.tf": 'resource "null_resource" "x" {}\n',
        "tests/plan.tftest.hcl": 'run "x" {}\n',
    }
    if tflint:
        files[".tflint.hcl"] = 'plugin "terraform" { enabled = true }\n'
    return _files(repo, files)


def _stack_detect(tmp_path: Path, repo: Path) -> dict[str, Any]:
    done = subprocess.run(
        [sys.executable, "-E", str(_AF), "stack-detect", "--repo", "."], cwd=repo,
        env=_env(tmp_path), capture_output=True, text=True, check=False, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


@pytest.mark.parametrize(("tflint", "lint"), [(True, "tflint --recursive"), (False, None)])
def test_stack_detect_on_a_terraform_root(tmp_path: Path, tflint: bool, lint: str | None) -> None:
    repo = _terraform_root(tmp_path / "repo", tflint=tflint)
    result = _stack_detect(tmp_path, repo)
    pack = _PLUGIN / "skills" / "terraform-patterns" / "SKILL.md"
    assert str(pack) in result["pack_paths"] and pack.is_file()
    primary = result["primary"]
    assert (primary["stack_id"], primary["pack"]) == ("terraform", "terraform-patterns")
    assert primary["toolchain"]["lint"] == lint
    assert primary["toolchain"]["test"] == "terraform test"
    assert result["toolchain_role"] == "fallback"


_FAILING_TOOL = 'sys.stdout.write("main.tf:1:1: Error: would block\\n")\nsys.exit(1)\n'


def test_the_commit_gate_on_a_tflint_repo_never_runs_tflint(tmp_path: Path) -> None:
    """ADR 0101: the commit gate only narrows; tflint may need `tflint --init` and a download
    before it runs at all. The stand-ins fail, so a run would have blocked the commit."""
    repo = _terraform_root(tmp_path / "repo", tflint=True)
    _git(repo, "init", "-q")
    _commit_all(repo)
    (repo / "main.tf").write_text('resource "null_resource" "y" {}\n', encoding="utf-8")
    _git(repo, "add", "main.tf")
    stubs = tmp_path / "stubs"
    for tool in ("tflint", "terraform"):
        _stub(stubs, tool, _FAILING_TOOL)
    assert _stack_detect(tmp_path, repo)["primary"]["toolchain"]["lint"] == "tflint --recursive"
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(repo),
               "session_id": "field-queue", "tool_input": {"command": "git commit -m change"}}
    done = subprocess.run(
        [sys.executable, str(_COMMIT_GATE)], input=json.dumps(payload), cwd=repo,
        env=_env(tmp_path, stubs), capture_output=True, text=True, check=False, timeout=120,
    )
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert done.stdout.strip() == ""  # no fail-open notice either: there was no gate to run
    assert _calls(stubs, "tflint") == [] and _calls(stubs, "terraform") == []
