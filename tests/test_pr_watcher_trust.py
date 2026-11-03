"""The PR watcher's trust boundary (ADR 0103), run as the processes an operator's clock runs.

Each scenario is a real ``run_scheduled.py`` (and its real ``pr_watch.py`` child) over a real git
repository whose ``origin`` is a real bare repository, reached through a fake ``ssh``, with a fake
``gh`` and a fake ``claude`` on PATH that log their argv. Nothing touches a network. What is
asserted is what would have reached GitHub, what reached the bare origin, and that the operator's
tree is as it was. GitHub's own behaviour is not what these measure: see the runbook's list of what
has not been run against it.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
_SCHEDULED = _PLUGIN / "bin" / "run_scheduled.py"
_WATCH = _PLUGIN / "bin" / "pr_watch.py"
_MIGRATE = _PLUGIN / "bin" / "state_migrate.py"
_PR_CREATED = _PLUGIN / "hooks" / "scripts" / "pr_created.py"
_SESSION_START = _PLUGIN / "hooks" / "scripts" / "session_start.py"

_JSONSCHEMA = pytest.mark.parametrize("bare", [False, True], ids=["schema", "bare"])
_ECHO = "ECHO-MARK"  # a value that must not reach a warning

_FAKE_GH = """#!{python}
import json, os, subprocess, sys
args = sys.argv[1:]
log = os.environ["GH_LOG"]
with open(log, "a") as handle:
    handle.write(json.dumps(args) + "\\n")
if args[:1] == ["api"] and args[1].endswith("/permission"):
    print(json.dumps({{"permission": os.environ.get("GH_PERMISSION", "write")}}))
    sys.exit(0)
if args[:2] == ["pr", "list"]:
    print(os.environ.get("GH_PR_LIST", "7"))
    sys.exit(0)
if args[:2] == ["run", "list"]:
    print("[]")
    sys.exit(0)
if args[:2] == ["api", "graphql"]:
    if any("mutation" in arg for arg in args):
        print("{{}}")
        sys.exit(0)
    calls = [json.loads(line) for line in open(log)]
    reads = [c for c in calls if c[:2] == ["api", "graphql"]]
    reads = [c for c in reads if not any("mutation" in a for a in c)]
    if len(reads) > int(os.environ.get("GH_GRAPHQL_FAILS_AFTER", "1000")):
        sys.exit(1)
    number = [a for a in args if a.startswith("number=")][0].split("=")[1]
    read = subprocess.run(
        ["git", "--git-dir", os.environ["GH_BARE"], "rev-parse", "--verify", "-q",
         "refs/pull/" + number + "/head"], capture_output=True, text=True,
    )
    oid = os.environ.get("GH_HEAD_OID") or read.stdout.strip() or "a" * 40
    if not any(a.startswith("query=") and "headRefOid" in a for a in args):
        oid = None  # as GraphQL answers: only what the query asked for
    threads = []
    if os.environ.get("GH_THREADS"):
        author = {{"login": os.environ.get("GH_THREAD_AUTHOR", "alice"),
                  "__typename": os.environ.get("GH_THREAD_AUTHOR_TYPE", "User")}}
        comment = {{"author": author, "body": "fix", "path": "README", "line": 1}}
        association = os.environ.get("GH_THREAD_ASSOCIATION", "MEMBER")
        if association != "absent":
            comment["authorAssociation"] = association
        threads = [{{"id": "T1", "isResolved": False, "comments": {{"nodes": [comment]}}}}]
    print(json.dumps({{"data": {{"repository": {{"pullRequest": {{
        "number": int(number), "isDraft": False,
        "mergeable": os.environ.get("GH_MERGEABLE", "MERGEABLE"),
        "createdAt": "2026-01-01T00:00:00Z", "headRefName": "pr-" + number, "headRefOid": oid,
        "baseRefName": "main", "state": os.environ.get("GH_PR_STATE", "OPEN"),
        "isCrossRepository": number in os.environ.get("GH_FORKS", "").split(),
        "reviewThreads": {{"pageInfo": {{"hasNextPage": False}}, "nodes": threads}},
        "reviews": {{"nodes": []}},
        "latestOpinionatedReviews": json.loads(os.environ.get(
            "GH_LATEST_REVIEWS", '{{"pageInfo": {{"hasNextPage": false}}, "nodes": []}}'
        )),
        "commits": {{"nodes": [{{"commit": {{"statusCheckRollup": {{"state": "SUCCESS"}}}}}}]}},
    }}}}}}}}))
    sys.exit(0)
if args[:2] == ["pr", "merge"]:
    sys.exit(0)
if args[:2] == ["pr", "view"]:
    calls = [json.loads(line) for line in open(log)]
    merged = any(call[:3] == ["pr", "merge", args[2]] for call in calls)
    print(json.dumps({{"state": os.environ.get(
        "GH_VIEW_STATE", "MERGED" if merged else "OPEN"
    )}}))
    sys.exit(0)
sys.exit(1)
"""

_FAKE_CLAUDE = """#!{python}
import json, os, subprocess, sys, time
with open(os.environ["CLAUDE_LOG"], "a") as handle:
    handle.write(json.dumps({{"cwd": os.getcwd(), "argv": sys.argv[1:]}}) + "\\n")
touch = os.environ.get("CLAUDE_OPERATOR_EDITS")
if touch:
    # The operator, working in their own tree while the pass runs.
    open(os.path.join(touch, "README"), "a").write("edited during the pass\\n")
    open(os.path.join(touch, "during-the-pass"), "w").write("created during the pass\\n")
time.sleep(float(os.environ.get("CLAUDE_SLEEP", "0")))
if os.environ.get("CLAUDE_NEVER_RUNS"):
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": True,
                      "result": "Not logged in", "num_turns": 0}}))
    sys.exit(1)
written = os.environ.get("CLAUDE_WRITES", "fix.txt")
os.makedirs(os.path.dirname(written) or ".", exist_ok=True)
open(written, "w").write("the fixer's edit\\n")
denials = [{{"tool_name": "Read"}}] if os.environ.get("CLAUDE_DENIED") else []
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                  "result": "No change made", "num_turns": 2, "permission_denials": denials}}))
"""

_FAKE_SSH = """#!{python}
import os, sys
service = sys.argv[-1].split()[0]  # git-upload-pack 'me/mine.git', whichever host was asked for
os.execvp("git", ["git", service[len("git-"):], os.environ["GH_BARE"]])
"""


class Stand:
    """A clone of ``me/mine`` on ``main``, its bare origin, an operator's home, and the fakes."""

    def __init__(self, base: Path, *, bare: bool = False) -> None:
        self.base = base
        self.home = base / "home"
        self.home.mkdir()
        self.repo = base / "repo"
        self.repo.mkdir()
        self.log = base / "gh.log"
        self.claude_log = base / "claude.log"
        self.origin = base / "origin.git"
        bin_dir = base / "bin"
        bin_dir.mkdir()
        for name, text in (("gh", _FAKE_GH), ("claude", _FAKE_CLAUDE), ("fake-ssh", _FAKE_SSH)):
            fake = bin_dir / name
            fake.write_text(text.format(python=sys.executable), encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        git = shutil.which("git")
        assert git is not None
        self.env: dict[str, str] = {
            "HOME": str(self.home),
            "PATH": f"{bin_dir}{os.pathsep}{Path(git).parent}",
            "GH_LOG": str(self.log),
            "GH_BARE": str(self.origin),
            "CLAUDE_LOG": str(self.claude_log),
            "GIT_SSH_COMMAND": str(bin_dir / "fake-ssh"),
            "GIT_CONFIG_GLOBAL": str(base / "no-global"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if bare:
            shim = base / "shim"
            shim.mkdir()
            (shim / "jsonschema.py").write_text("raise ImportError('blocked')\n", encoding="utf-8")
            self.env["PYTHONPATH"] = str(shim)
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.origin)],
            check=True, env=self.env,
        )
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "git@github.com:me/mine.git")
        (self.repo / "README").write_text("x\n", encoding="utf-8")
        self.commit()
        self.git("push", "-q", "origin", "main")

    def git(self, *args: str, cwd: Path | None = None) -> str:
        done = subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args],
            capture_output=True, text=True, env=self.env, check=True,
        )
        return done.stdout.strip()

    def in_origin(self, *args: str) -> str:
        return self.git("--git-dir", str(self.origin), *args, cwd=self.base)

    def commit(self) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", "c")

    def operator(self, section: dict[str, Any], **other: Any) -> None:
        """The user-level file's ``pr_watcher``, and any other section."""
        path = self.home / ".agentic-forge" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pr_watcher": section, **other}), encoding="utf-8")

    def committed(self, relative: str, content: Any) -> None:
        """A file the repo commits to the branch it is on."""
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else json.dumps(content)
        path.write_text(text, encoding="utf-8")
        self.commit()

    def pull_request(self, number: int, config: Any = None) -> str:
        """A same-repo PR: branch ``pr-<number>`` and GitHub's ``refs/pull/<number>/head`` on the
        origin, carrying ``config``, and nothing of it left in the operator's clone but the remote
        tracking ref. Returns its head commit."""
        self.git("checkout", "-qb", f"pr-{number}", "main")
        (self.repo / f"change-{number}").write_text("x\n", encoding="utf-8")
        if config is not None:
            self.committed(".agentic-forge/config.json", config)
        else:
            self.commit()
        self.git("push", "-q", "origin", f"pr-{number}", f"pr-{number}:refs/pull/{number}/head")
        oid = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        self.git("branch", "-qD", f"pr-{number}")
        return oid

    def _from_lib(self, expr: str, *args: str) -> str:
        done = self.python("-c", (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from agentic_forge import diagnostics as d;"
            f"print({expr})"
        ), str(_PLUGIN / "lib"), *args)
        assert done.returncode == 0, done.stderr
        return str(done.stdout.strip())

    def state(self, repo: Path | None = None) -> Path:
        return Path(self._from_lib("d.state_root(sys.argv[2])", str(repo or self.repo)))

    def passes(self) -> Path:
        root = self._from_lib("d.user_state_root(sys.argv[2])", str(self.repo))
        return Path(root) / "pr-watch-passes"

    def queue(self, *numbers: int, owner: str = "me", name: str = "mine") -> None:
        """Entries at the state root, where only the hook puts them."""
        path = self.state() / "pr-watch-queue.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = [{"owner": owner, "name": name, "number": n} for n in numbers]
        path.write_text(json.dumps(entries), encoding="utf-8")

    def python(self, *argv: str, stdin: str = "", **extra: str) -> Any:
        return subprocess.run(
            [sys.executable, *argv], capture_output=True, text=True, input=stdin,
            env={**self.env, **extra}, cwd=str(self.repo), check=False, timeout=180,
        )

    def tick(self, *, repo: Path | None = None, **extra: str) -> Any:
        """One poll of the operator's clock. ``--force``: the cadence is not under test here."""
        done = self.python(str(_SCHEDULED), "--repo", str(repo or self.repo), "--force", **extra)
        assert "Traceback" not in done.stderr, done.stderr
        return done

    def gh(self, *prefix: str) -> list[str]:
        """The logged calls starting with ``prefix``, or every call that acts on a PR."""
        if not self.log.exists():
            return []
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        acting = (["pr", "checkout"], ["pr", "merge"], ["pr", "list"])
        if prefix:
            calls = [call for call in calls if call[: len(prefix)] == list(prefix)]
        else:
            calls = [call for call in calls if call[:2] in acting]
        return [" ".join(call) for call in calls]

    def claude(self) -> list[dict[str, Any]]:
        if not self.claude_log.exists():
            return []
        return [json.loads(line) for line in self.claude_log.read_text().splitlines()]

    def head(self, repo: Path | None = None) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)

    def diagnostics(self) -> str:
        path = self.state() / "diagnostics.jsonl"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def snapshot(self) -> tuple[str, str, str]:
        """What a pass must leave as it found: the branch, its commit and the status of the tree."""
        return (
            self.head(), self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain", "--untracked-files=all"),
        )


def _merged(number: int, oid: str, slug: str = "me/mine", method: str = "rebase") -> str:
    return f"pr merge {number} -R {slug} --{method} --delete-branch --match-head-commit {oid}"


@pytest.fixture
def stand(tmp_path: Path) -> Stand:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    return Stand(tmp_path)


@pytest.fixture
def bare_stand(tmp_path: Path, bare: bool) -> Stand:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    return Stand(tmp_path, bare=bare)


_ALL_ON = {"enabled": True, "auto_merge": True}


# --- A: a repo's config does not control the watcher -----------------------------------------


@_JSONSCHEMA
@pytest.mark.parametrize(
    "config",
    [
        {"enabled": True, "auto_merge": True},
        {"enabled": True, "auto_merge": True, "repos": ["victim-org/prod"]},
        {"enabled": True, "repos": ["victim-org/prod"]},
        {"auto_merge": True, "repos": ["victim-org/prod"]},
    ],
    ids=["enabled+merge", "with-repos", "enabled+repos", "no-enabled"],
)
def test_a_repo_config_alone_reaches_nothing(bare_stand: Stand, config: dict[str, Any]) -> None:
    stand = bare_stand
    stand.committed(".agentic-forge/config.json", {"pr_watcher": config})
    done = stand.tick()
    assert stand.gh() == [], done.stdout + done.stderr


@_JSONSCHEMA
def test_a_repo_config_does_not_override_a_user_level_off(bare_stand: Stand) -> None:
    stand = bare_stand
    stand.operator({"enabled": False, "auto_merge": False})
    stand.committed(
        ".agentic-forge/config.json",
        {"pr_watcher": {"enabled": True, "auto_merge": True, "repos": ["victim-org/prod"]}},
    )
    done = stand.tick()
    assert stand.gh() == []
    assert "pr_watcher.enabled in a repo config is ignored" in done.stderr


@_JSONSCHEMA
def test_what_a_repo_set_is_warned_about_without_its_value(bare_stand: Stand) -> None:
    stand = bare_stand
    stand.committed(
        ".agentic-forge/config.json",
        {"pr_watcher": {
            "enabled": True, "bot": f"{_ECHO}-bot", "repos": [f"{_ECHO}/prod"], "auto_merge": True,
        }},
    )
    message = json.loads(
        stand.python(
            str(_SESSION_START),
            stdin=json.dumps({"cwd": str(stand.repo), "session_id": "s"}),
        ).stdout
    )["systemMessage"]
    for key in ("enabled", "bot", "repos", "auto_merge"):
        assert f"pr_watcher.{key} in a repo config is ignored" in message
    assert _ECHO not in message


def test_no_config_at_all_makes_no_gh_call(stand: Stand) -> None:
    stand.tick()
    assert stand.gh() == []


def test_a_manual_apply_does_not_take_auto_merge_from_the_repo(stand: Stand) -> None:
    """Without the driver the CLI reads the settings itself. A repo's file still does not count."""
    stand.operator({"enabled": True})
    stand.committed(".agentic-forge/config.json", {"pr_watcher": {"auto_merge": True}})
    done = stand.python(
        str(_WATCH), "--repo", str(stand.repo), "--owner", "me", "--name", "mine", "--pr", "7",
        "--apply",
    )
    assert done.returncode == 0, done.stderr
    assert "merged=False" in done.stdout and stand.gh("pr", "merge") == []


# --- user-level still works, end to end ------------------------------------------------------


def test_the_operators_auto_merge_merges_a_queued_pr_at_the_commit_the_gate_read(
    stand: Stand,
) -> None:
    stand.operator(_ALL_ON)
    oid = stand.pull_request(7)
    stand.queue(7)
    done = stand.tick()
    assert stand.gh() == [_merged(7, oid)], done.stdout + done.stderr


def test_without_jsonschema_the_settings_reach_the_watcher_which_cannot_start(
    tmp_path: Path,
) -> None:
    """The driver reads the operator's file with no validator, as far as the worktree. The child
    imports `agent_eval`, which needs `jsonschema`, so it exits 1: recorded, and nothing merged."""
    stand = Stand(tmp_path, bare=True)
    stand.operator(_ALL_ON)
    stand.pull_request(7)
    stand.queue(7)
    done = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--force")
    assert done.returncode == 1
    assert stand.gh() == []
    assert "watcher exited 1" in stand.diagnostics()
    assert list(stand.passes().iterdir()) == []


def test_the_operators_repos_sweep_merges(stand: Stand) -> None:
    stand.operator({**_ALL_ON, "repos": ["me/mine"], "merge_method": "squash"})
    oid = stand.pull_request(7)
    stand.tick()
    assert stand.gh() == [
        "pr list -R me/mine --state open --json number -q .[].number",
        _merged(7, oid, method="squash"),
    ]


def test_auto_merge_listing_this_repo_merges_here(stand: Stand) -> None:
    stand.operator({"enabled": True, "auto_merge": ["ME/mine"]})  # slugs are case-insensitive
    oid = stand.pull_request(7)
    stand.queue(7)
    stand.tick()
    assert _merged(7, oid) in stand.gh()


def test_auto_merge_listing_another_repo_only_watches_here(stand: Stand) -> None:
    stand.operator({"enabled": True, "auto_merge": ["me/other"]})
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick()
    assert stand.gh() == [], done.stdout + done.stderr
    assert done.returncode == 0


# --- a repo may turn it off ------------------------------------------------------------------


@_JSONSCHEMA
def test_a_repo_can_turn_the_watcher_off_and_says_so(bare_stand: Stand) -> None:
    stand = bare_stand
    stand.operator({**_ALL_ON, "repos": ["me/mine"]})
    stand.committed(".agentic-forge/config.json", {"pr_watcher": {"enabled": False}})
    stand.queue(7)
    done = stand.tick()
    assert stand.gh() == []
    assert "pr_watcher.enabled is false in this repo's config" in done.stderr


@_JSONSCHEMA
@pytest.mark.parametrize(
    "text",
    ['{"pr_watcher": {"enabled": false', '{"pr_watcher": {"enabled": false}, "stray": 1,}'],
    ids=["truncated", "trailing-comma"],
)
def test_a_broken_repo_file_keeps_its_off(bare_stand: Stand, text: str) -> None:
    stand = bare_stand
    stand.operator({**_ALL_ON, "repos": ["me/mine"]})
    stand.committed(".agentic-forge/config.json", text)
    stand.queue(7)
    done = stand.tick()
    assert stand.gh() == []
    assert "ignoring unreadable" in done.stderr
    assert "enabled: false it clearly states" in done.stderr


def test_a_broken_repo_file_that_does_not_say_off_leaves_the_operators_settings(
    stand: Stand,
) -> None:
    stand.operator(_ALL_ON)
    stand.committed(".agentic-forge/config.json", "{not json")
    oid = stand.pull_request(7)
    stand.queue(7)
    stand.tick()
    assert _merged(7, oid) in stand.gh()


# --- B: a PR's tree decides nothing ----------------------------------------------------------


_PR_SAYS_MERGE = {"pr_watcher": {"enabled": True, "auto_merge": True, "bot": "pr-bot"}}


def test_a_fork_pr_then_a_same_repo_pr_in_one_tick(stand: Stand) -> None:
    stand.operator({"enabled": True, "auto_merge": False})
    stand.pull_request(1, _PR_SAYS_MERGE)
    stand.pull_request(2)
    stand.queue(1, 2)
    done = stand.tick(GH_FORKS="1", GH_THREADS="1")
    assert stand.gh() == [], done.stdout + done.stderr
    assert "PR #1 from a fork" in done.stdout
    assert [Path(call["cwd"]).name.split("-")[0] for call in stand.claude()] == ["pr2"]


def test_a_same_repo_pr_does_not_change_the_settings_of_the_next(stand: Stand) -> None:
    stand.operator({"enabled": True, "auto_merge": False})
    stand.pull_request(1, _PR_SAYS_MERGE)
    stand.pull_request(2)
    stand.queue(1, 2)
    stand.tick()
    assert stand.gh() == []


def test_a_pr_does_not_change_its_own_settings_on_the_next_tick(stand: Stand) -> None:
    stand.operator({"enabled": True, "auto_merge": False})
    stand.pull_request(1, _PR_SAYS_MERGE)
    stand.queue(1)
    stand.tick()
    stand.tick()
    assert stand.gh() == []


def test_a_config_in_a_prs_tree_is_never_opened(stand: Stand) -> None:
    """Every reader of a malformed config says so, so saying nothing means nothing read it."""
    stand.operator(_ALL_ON)
    oid = stand.pull_request(1, "{not json")
    stand.queue(1)
    done = stand.tick()
    assert _merged(1, oid) in stand.gh()
    assert "ignoring" not in done.stderr + done.stdout
    assert "malformed" not in done.stderr + done.stdout


def test_a_pr_cannot_turn_the_watcher_off_for_itself(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    oid = stand.pull_request(1, {"pr_watcher": {"enabled": False}})
    stand.queue(1)
    stand.tick()
    assert _merged(1, oid) in stand.gh()


def test_a_fork_is_not_fetched_by_the_sweep_either(stand: Stand) -> None:
    stand.operator({**_ALL_ON, "repos": ["me/mine"]})
    stand.pull_request(7)
    objects_before = stand.git("count-objects", "-v")
    done = stand.tick(GH_FORKS="7", GH_THREADS="1")
    assert stand.gh("pr", "merge") == [] and stand.claude() == []
    assert "PR #7 from a fork" in done.stdout
    assert stand.git("count-objects", "-v") == objects_before
    assert not stand.passes().exists()


def test_an_answer_that_does_not_say_fork_starts_nothing(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_GRAPHQL_FAILS_AFTER="0")
    assert stand.gh() == [], done.stdout + done.stderr
    assert done.returncode == 1
    assert "could not read the PR" in stand.diagnostics()
    assert not stand.passes().exists()


# --- the operator's tree is not involved -----------------------------------------------------


@pytest.mark.parametrize("show_untracked", [None, "no"], ids=["default", "showUntrackedFiles=no"])
def test_a_pass_leaves_the_operators_work_and_head_alone(
    stand: Stand, show_untracked: str | None
) -> None:
    """Including edits made while it runs, in the tree the clock was started from."""
    if show_untracked:
        stand.git("config", "status.showUntrackedFiles", show_untracked)
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    (stand.repo / "README").write_text("the operator's own edit\n", encoding="utf-8")
    (stand.repo / "notes.txt").write_text("untracked work\n", encoding="utf-8")
    local = stand.repo / ".agentic-forge" / "local-notes"
    local.parent.mkdir()
    local.write_text("also untracked\n", encoding="utf-8")
    sha = stand.git("rev-parse", "HEAD")

    done = stand.tick(GH_THREADS="1", CLAUDE_OPERATOR_EDITS=str(stand.repo))

    assert done.returncode == 0, done.stdout + done.stderr
    assert stand.head() == "main" and stand.git("rev-parse", "HEAD") == sha
    assert (stand.repo / "README").read_text(encoding="utf-8") == (
        "the operator's own edit\nedited during the pass\n"
    )
    assert (stand.repo / "notes.txt").read_text(encoding="utf-8") == "untracked work\n"
    assert local.read_text(encoding="utf-8") == "also untracked\n"
    assert (stand.repo / "during-the-pass").is_file()
    assert not (stand.repo / "fix.txt").exists()
    # And none of it left with the fixer's commit.
    pushed = stand.in_origin("show", "--name-only", "--format=", "refs/heads/pr-7").splitlines()
    assert pushed == ["fix.txt"]


def test_the_fixer_commit_reaches_the_pr_branch_and_no_other(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    main_before = stand.in_origin("rev-parse", "refs/heads/main")
    local_main = stand.git("rev-parse", "main")
    stand.in_origin("tag", "a-tag-on-the-origin", "refs/heads/main")
    stand.git("config", "remote.origin.tagOpt", "--tags")  # as an operator may have it

    done = stand.tick(GH_THREADS="1")

    assert done.returncode == 0, done.stdout + done.stderr
    assert stand.in_origin("rev-parse", "refs/heads/pr-7~1") == oid
    assert "PR watcher: address review" in stand.in_origin("log", "-1", "--format=%s", "pr-7")
    assert stand.in_origin("rev-parse", "refs/heads/main") == main_before
    assert stand.git("rev-parse", "main") == local_main and stand.head() == "main"
    assert stand.git("branch", "--list", "pr-7") == ""  # no local branch was made for it
    assert stand.git("tag", "--list") == ""  # no tag came with the fetch
    assert not (stand.repo / ".git" / "FETCH_HEAD").exists()  # nor a FETCH_HEAD of the operator's
    # It ran in its own worktree, under the state root, which is gone again.
    (session,) = stand.claude()
    assert Path(session["cwd"]).parent == stand.passes().resolve()
    assert list(stand.passes().iterdir()) == []
    assert stand.git("worktree", "list", "--porcelain").count("worktree ") == 1


def test_a_pass_works_with_that_branch_checked_out_by_the_operator(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    stand.git("checkout", "-qb", "pr-7", "origin/pr-7")
    (stand.repo / "local-work").write_text("x\n", encoding="utf-8")
    done = stand.tick(GH_THREADS="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert stand.in_origin("rev-parse", "refs/heads/pr-7~1") == oid  # the fix landed
    assert stand.head() == "pr-7" and stand.git("rev-parse", "pr-7") == oid  # theirs did not move
    assert (stand.repo / "local-work").is_file() and not (stand.repo / "fix.txt").exists()


def test_a_clock_in_a_linked_worktree_works_and_shares_the_queue(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    linked = stand.base / "linked"
    stand.git("worktree", "add", "-q", "-b", "clock", str(linked), "main")
    clock_sha = stand.git("rev-parse", "clock")
    done = stand.tick(repo=linked, GH_THREADS="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert stand.in_origin("rev-parse", "refs/heads/pr-7~1") == oid
    assert stand.head(linked) == "clock" and stand.git("rev-parse", "clock") == clock_sha
    assert stand.head() == "main"
    assert list(stand.passes().iterdir()) == []
    assert stand.git("worktree", "list", "--porcelain").count("worktree ") == 2  # main + linked


def test_a_same_named_tag_changes_nothing(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    stand.git("tag", "main")
    stand.git("tag", "pr-7")
    done = stand.tick(GH_THREADS="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert stand.git("symbolic-ref", "HEAD") == "refs/heads/main"  # a branch, not the tag's commit
    assert stand.in_origin("rev-parse", "refs/heads/pr-7~1") == oid


def test_state_in_the_repo_does_not_reach_the_pr_or_the_worktrees_home(stand: Stand) -> None:
    """Under `state.in_repo` the queue is in the operator's tree, and a pass's tree still is not."""
    stand.operator({"enabled": True}, state={"in_repo": True})
    stand.pull_request(7)
    stand.queue(7)
    assert stand.state() == stand.repo / ".agentic-forge"
    done = stand.tick(GH_THREADS="1")
    assert done.returncode == 0, done.stdout + done.stderr
    (session,) = stand.claude()
    assert not Path(session["cwd"]).is_relative_to(stand.repo)
    assert (stand.state() / "pr-watch-queue.json").is_file()
    pushed = stand.in_origin("show", "--name-only", "--format=", "refs/heads/pr-7").splitlines()
    assert pushed == ["fix.txt"]


def test_a_committed_queue_under_state_in_repo_still_meets_the_origin_check(stand: Stand) -> None:
    """There the tree is the state root, by the operator's choice. A residual risk (ADR 0103)."""
    stand.operator(_ALL_ON, state={"in_repo": True})
    stand.committed(
        ".agentic-forge/pr-watch-queue.json",
        [{"owner": "victim-org", "name": "prod", "number": 42}],
    )
    stand.tick()
    assert stand.gh() == []


def test_a_head_that_moved_during_the_fetch_starts_nothing(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_HEAD_OID="b" * 40, GH_THREADS="1")
    assert done.returncode == 1 and stand.claude() == [] and stand.gh("pr", "merge") == []
    assert "the PR's head moved" in stand.diagnostics()


def test_a_head_that_cannot_be_fetched_fails_the_pass(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.queue(99)  # no such ref on the origin
    done = stand.tick()
    assert done.returncode == 1 and stand.gh("pr", "merge") == []
    assert "git fetch of the PR's head failed" in stand.diagnostics()


def test_a_pass_that_fails_removes_its_worktree(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(1)
    stand.queue(1)
    done = stand.tick(GH_GRAPHQL_FAILS_AFTER="1")  # the driver's read answers, the watcher's fails
    assert done.returncode == 1 and "watcher exited 1" in stand.diagnostics()
    assert list(stand.passes().iterdir()) == []
    assert stand.git("worktree", "list", "--porcelain").count("worktree ") == 1


# --- leftovers and the run lock --------------------------------------------------------------


def test_a_killed_runs_worktrees_are_removed_and_the_operators_are_not(stand: Stand) -> None:
    stand.operator({"enabled": True})
    passes = stand.passes()
    passes.mkdir(parents=True)
    stand.git("worktree", "add", "-q", "--detach", str(passes / "pr1-whole"), "HEAD")
    stand.git("worktree", "add", "-q", "--detach", str(passes / "pr2-dir-gone"), "HEAD")
    shutil.rmtree(passes / "pr2-dir-gone")
    (passes / "pr3-no-record").mkdir()
    # An operator's own worktree on a disk that is not mounted: `git worktree prune` would drop it.
    theirs = stand.base / "on-another-disk"
    stand.git("worktree", "add", "-q", "--detach", str(theirs), "HEAD")
    theirs.rename(stand.base / "unmounted")

    done = stand.tick()

    assert done.returncode == 0, done.stdout + done.stderr
    assert list(passes.iterdir()) == []
    listed = stand.git("worktree", "list", "--porcelain")
    assert "pr1-whole" not in listed and "pr2-dir-gone" not in listed
    assert "on-another-disk" in listed


def _try_lock(path: Path) -> bool:
    """True if ``path`` could be locked right now, by what is standing in for the next run."""
    handle = os.open(str(path), os.O_RDONLY)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    else:
        return True
    finally:
        os.close(handle)


def _wait_for(check: Any, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def test_a_killed_driver_leaves_the_lock_with_its_live_child(stand: Stand) -> None:
    """The child inherits the lock, so the next run neither starts nor cleans up under it."""
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    driver = subprocess.Popen(
        [sys.executable, str(_SCHEDULED), "--repo", str(stand.repo), "--force"],
        env={**stand.env, "GH_THREADS": "1", "CLAUDE_SLEEP": "4"}, cwd=str(stand.repo),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _wait_for(lambda: bool(stand.claude()))  # the fixer is running, in the child's tree
    tree = Path(stand.claude()[0]["cwd"])
    os.kill(driver.pid, signal.SIGKILL)
    driver.wait()

    assert not _try_lock(stand.repo)
    done = stand.tick()
    assert done.returncode == 0 and "Another scheduled run" in done.stdout
    assert "## " not in done.stdout
    assert tree.is_dir()  # not cleaned from under the child

    _wait_for(lambda: _try_lock(stand.repo))  # the child finished: its fix landed, the lock is free
    assert stand.in_origin("rev-parse", "refs/heads/pr-7~1") == oid
    assert stand.git("rev-parse", "main") == stand.in_origin("rev-parse", "main")
    assert tree.is_dir()  # the driver that would have removed it is dead

    done = stand.tick()
    assert "## pr-watch-queue" in done.stdout
    assert not tree.exists()


@pytest.fixture
def held_lock(stand: Stand) -> Iterator[None]:
    handle = os.open(str(stand.repo), os.O_RDONLY)
    fcntl.flock(handle, fcntl.LOCK_EX)
    yield
    os.close(handle)


def test_a_second_run_stays_out(stand: Stand, held_lock: None) -> None:
    stand.operator(_ALL_ON)
    stand.pull_request(1)
    stand.queue(1)
    done = stand.tick()
    assert done.returncode == 0 and "Another scheduled run" in done.stdout
    assert stand.gh() == [] and "## " not in done.stdout


def test_a_clock_in_a_linked_worktree_takes_the_same_lock(stand: Stand, held_lock: None) -> None:
    linked = stand.base / "linked"
    stand.git("worktree", "add", "-q", "-b", "clock", str(linked), "main")
    done = stand.tick(repo=linked)
    assert done.returncode == 0 and "Another scheduled run" in done.stdout


def test_repeated_skips_show_in_the_log_and_in_health_and_a_run_clears_them(
    stand: Stand,
) -> None:
    handle = os.open(str(stand.repo), os.O_RDONLY)
    fcntl.flock(handle, fcntl.LOCK_EX)
    for _ in range(5):
        assert stand.tick().returncode == 0
    assert "found the run lock held" not in stand.diagnostics()
    healthy = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health")
    assert "run lock" not in healthy.stdout

    assert stand.tick().returncode == 0  # the sixth: still exit 0, and now it says so
    assert "6 polls in a row found the run lock held" in stand.diagnostics()
    stalled = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health")
    assert "run lock: held for the last 6 polls" in stalled.stdout

    os.close(handle)
    assert "## " in stand.tick().stdout
    cleared = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health")
    assert "run lock" not in cleared.stdout


# --- a repo other than this checkout's origin ------------------------------------------------


def test_a_pr_in_another_repo_gets_no_fix_pass(stand: Stand) -> None:
    """The fixer pushes to `origin`, which is not that PR's repo."""
    stand.operator({"enabled": True, "repos": ["other/prod"]})
    done = stand.tick(GH_PR_LIST="5", GH_THREADS="1", GH_HEAD_OID="c" * 40)
    assert done.returncode == 1, done.stdout + done.stderr
    assert stand.claude() == [] and not stand.passes().exists()
    assert stand.gh("pr", "merge") == []
    assert "fix and push refused for other/prod#5" in stand.diagnostics()
    assert stand.in_origin("for-each-ref", "--format=%(refname)") == "refs/heads/main"


def test_a_conflict_in_another_repos_pr_is_refused_too(stand: Stand) -> None:
    stand.operator({"enabled": True, "repos": ["other/prod"]})
    done = stand.tick(GH_PR_LIST="5", GH_MERGEABLE="CONFLICTING", GH_HEAD_OID="c" * 40)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "fix and push refused for other/prod#5" in stand.diagnostics()
    assert not stand.passes().exists()


def test_a_pr_in_another_repo_may_still_merge_by_slug(stand: Stand) -> None:
    stand.operator({"enabled": True, "repos": ["other/prod"], "auto_merge": True})
    done = stand.tick(GH_PR_LIST="5", GH_HEAD_OID="c" * 40)
    assert done.returncode == 0, done.stdout + done.stderr
    assert _merged(5, "c" * 40, slug="other/prod") in stand.gh()
    assert not stand.passes().exists()


# --- a failed pass fails its job -------------------------------------------------------------


def test_a_sweep_with_a_failed_pass_fails_its_job(stand: Stand) -> None:
    stand.operator({"enabled": True, "repos": ["me/mine"]})
    stand.pull_request(7)
    done = stand.tick(GH_GRAPHQL_FAILS_AFTER="0")
    assert done.returncode == 1
    assert "1 of 1 watch pass(es) failed" in done.stdout
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    (line,) = [line for line in health.splitlines() if line.strip().startswith("pr-watch ")]
    assert "failed" in line


def test_a_sweep_with_no_failed_pass_is_ok(stand: Stand) -> None:
    stand.operator({"enabled": True, "repos": ["me/mine"]})
    stand.pull_request(7)
    done = stand.tick()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "pr-watch: watched 1 PR(s) across 1 repo(s)" in done.stdout


# --- what the fixer session is told ----------------------------------------------------------


def test_the_fixer_session_loads_no_project_settings(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1")
    (session,) = stand.claude()
    argv = session["argv"]
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--tools") + 1] == "Read,Write,Edit,Grep,Glob"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert "--allowedTools" not in argv
    assert '"autoMemoryEnabled": false' in argv[argv.index("--settings") + 1]


def _posted(stand: Stand) -> list[str]:
    """What the watcher said on a thread: replies and resolves, as argv."""
    return [c for c in stand.gh("api", "graphql") if "mutation" in c]


def test_a_stopped_pr_gets_no_push_so_a_merged_prs_branch_stays_deleted(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", GH_PR_STATE="MERGED")
    assert done.returncode == 0, done.stdout + done.stderr
    assert stand.claude() == [] and _posted(stand) == []


def _write_permission_asks(stand: Stand) -> list[str]:
    return [c for c in stand.gh("api") if c.endswith("/permission")]


@pytest.mark.parametrize(
    ("permission", "reaches"),
    [("write", True), ("maintain", True), ("admin", True), ("read", False), ("none", False),
     ("triage", False), ("", False)],
)
def test_a_person_needs_write_on_the_repo_not_just_an_association(
    stand: Stand, permission: str, reaches: bool
) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1", GH_THREAD_ASSOCIATION="COLLABORATOR", GH_PERMISSION=permission)
    assert bool(stand.claude()) is reaches
    assert _write_permission_asks(stand) == ["api repos/me/mine/collaborators/alice/permission"]


def test_a_permission_that_cannot_be_read_fails_closed(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    fake = Path(stand.env["PATH"].split(os.pathsep)[0]) / "gh"
    text = fake.read_text(encoding="utf-8")
    fake.write_text(text.replace('args[1].endswith("/permission"):', 'args[1].endswith("/x"):'))
    stand.tick(GH_THREADS="1")  # now it exits 1 for that call
    assert stand.claude() == [] and _posted(stand) == []


def test_the_association_is_checked_before_the_network(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1", GH_THREAD_ASSOCIATION="CONTRIBUTOR")
    assert _write_permission_asks(stand) == []


@pytest.mark.parametrize(
    ("kind", "listed", "reaches"),
    [
        ("Bot", ["codex"], True),
        ("Bot", ["codex[bot]"], True),
        ("Bot", ["CODEX"], True),
        ("Bot", ["other"], False),
        ("Bot", [], False),
        ("User", ["codex"], False),  # someone registered the bare login
    ],
)
def test_a_reviewer_app_needs_the_operators_list_and_to_be_a_bot(
    stand: Stand, kind: str, listed: list[str], reaches: bool
) -> None:
    stand.operator({"enabled": True, "trusted_reviewers": listed})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(
        GH_THREADS="1", GH_THREAD_AUTHOR="codex", GH_THREAD_AUTHOR_TYPE=kind,
        GH_THREAD_ASSOCIATION="NONE",
    )
    assert bool(stand.claude()) is reaches
    assert _write_permission_asks(stand) == []


def test_a_repo_cannot_add_a_trusted_reviewer(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.committed(".agentic-forge/config.json", {"pr_watcher": {"trusted_reviewers": ["codex"]}})
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(
        GH_THREADS="1", GH_THREAD_AUTHOR="codex", GH_THREAD_AUTHOR_TYPE="Bot",
        GH_THREAD_ASSOCIATION="NONE",
    )
    assert stand.claude() == []
    assert "pr_watcher.trusted_reviewers in a repo config is ignored" in done.stderr


def test_a_pr_that_ran_out_of_ticks_held_shows_in_health(stand: Stand) -> None:
    stand.operator({"enabled": True, "max_ticks": 1})
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", GH_THREAD_ASSOCIATION="NONE")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "held" in stand.diagnostics()
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    assert "1 queued PR(s) ran out of ticks with a review thread held" in health
    assert "pr_watcher.trusted_reviewers" in health


def test_a_pr_that_merged_while_held_does_not_show_as_held_out(stand: Stand) -> None:
    stand.operator({"enabled": True, "max_ticks": 1})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1", GH_THREAD_ASSOCIATION="NONE", GH_VIEW_STATE="MERGED")
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    assert "ran out of ticks" not in health


def test_a_change_request_with_no_author_or_past_the_page_shuts_the_gate(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.pull_request(7)
    stand.queue(7)
    no_author = {"pageInfo": {"hasNextPage": False},
                 "nodes": [{"state": "CHANGES_REQUESTED", "author": None}]}
    stand.tick(GH_LATEST_REVIEWS=json.dumps(no_author))
    assert stand.gh("pr", "merge") == []
    stand.queue(7)
    stand.tick(GH_LATEST_REVIEWS=json.dumps({"pageInfo": {"hasNextPage": True}, "nodes": []}))
    assert stand.gh("pr", "merge") == []


def test_a_symlink_at_a_protected_name_gets_no_session(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.git("checkout", "-qb", "pr-7", "main")
    (stand.repo / "cfg").mkdir()
    (stand.repo / "cfg" / "x").write_text("x\n", encoding="utf-8")
    (stand.repo / ".github").symlink_to("cfg")
    stand.commit()
    stand.git("push", "-q", "origin", "pr-7", "pr-7:refs/pull/7/head")
    stand.git("checkout", "-q", "main")
    stand.git("branch", "-qD", "pr-7")
    stand.queue(7)
    done = stand.tick(GH_THREADS="1")
    assert done.returncode == 1 and stand.claude() == [] and _posted(stand) == []
    assert ".github is a symlink: no session started" in stand.diagnostics()


def _pr_with_links(stand: Stand, number: int, links: dict[str, str]) -> str:
    stand.git("checkout", "-qb", f"pr-{number}", "main")
    for path, target in links.items():
        link = stand.repo / path
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    (stand.repo / "ci").mkdir()
    (stand.repo / "ci" / "ci.yml").write_text("x\n", encoding="utf-8")
    stand.commit()
    stand.git("push", "-q", "origin", f"pr-{number}", f"pr-{number}:refs/pull/{number}/head")
    oid = stand.git("rev-parse", "HEAD")
    stand.git("checkout", "-q", "main")
    stand.git("branch", "-qD", f"pr-{number}")
    return oid


@pytest.mark.parametrize(
    "links",
    [
        {".github/copilot-instructions.md": "../README"},
        {".claude/note.md": "../README"},
    ],
    ids=["github", "claude"],
)
def test_a_link_below_a_protected_directory_does_not_stop_the_session(
    stand: Stand, links: dict[str, str]
) -> None:
    stand.operator({"enabled": True})
    oid = _pr_with_links(stand, 7, links)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert len(stand.claude()) == 1
    assert stand.in_origin("rev-parse", "refs/heads/pr-7~1") == oid  # and the fix landed


def test_a_change_to_what_a_workflow_links_to_gets_no_commit(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = _pr_with_links(stand, 7, {".github/workflows/ci.yml": "../../ci/ci.yml"})
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", CLAUDE_WRITES="ci/ci.yml")
    assert done.returncode == 1
    assert len(stand.claude()) == 1  # the session ran
    assert stand.in_origin("rev-parse", "pr-7") == oid and _posted(stand) == []
    assert "the target of .github/workflows/ci.yml" in stand.diagnostics()


def test_a_manual_apply_under_in_repo_does_not_call_its_own_log_dirt(stand: Stand) -> None:
    """Each `--apply` audits to `.agentic-forge/` in this tree, and the next one has to run."""
    stand.operator({"enabled": True}, state={"in_repo": True})
    stand.pull_request(7)
    stand.git("checkout", "-qb", "pr-7", "origin/pr-7")
    argv = (
        str(_WATCH), "--repo", str(stand.repo), "--owner", "me", "--name", "mine", "--pr", "7",
        "--apply",
    )
    for _ in range(2):
        done = stand.python(*argv, GH_THREADS="1")
        assert "the checkout is not clean" not in stand.diagnostics()
    assert len(stand.claude()) == 2, done.stdout + done.stderr
    log = stand.repo / ".agentic-forge" / "diagnostics.jsonl"
    assert log.is_file()  # the discard after a session did not take it
    pushed = stand.in_origin("show", "--name-only", "--format=", "refs/heads/pr-7").splitlines()
    assert pushed == ["fix.txt"]  # and it went nowhere


def test_a_manual_apply_under_in_repo_treats_a_tracked_edit_there_as_dirt(stand: Stand) -> None:
    """Only the untracked state is ours: a refused session must not reset the user's edit."""
    stand.operator({"enabled": True}, state={"in_repo": True})
    stand.pull_request(7)
    stand.git("checkout", "-qb", "pr-7", "origin/pr-7")
    tracked = stand.repo / ".agentic-forge" / "config.json"
    tracked.parent.mkdir(exist_ok=True)
    tracked.write_text("{}\n", encoding="utf-8")
    stand.git("add", "-f", ".agentic-forge/config.json")
    stand.git("commit", "-qm", "tracked config")
    tracked.write_text('{"edited": true}\n', encoding="utf-8")
    stand.python(
        str(_WATCH), "--repo", str(stand.repo), "--owner", "me", "--name", "mine", "--pr", "7",
        "--apply", GH_THREADS="1",
    )
    assert stand.claude() == []
    assert tracked.read_text(encoding="utf-8") == '{"edited": true}\n'


def test_a_session_discarded_under_in_repo_leaves_the_state_alone(stand: Stand) -> None:
    """A session that never ran is discarded, and that must not take what is kept in this tree."""
    stand.operator({"enabled": True}, state={"in_repo": True})
    stand.pull_request(7)
    stand.git("checkout", "-qb", "pr-7", "origin/pr-7")
    kept = stand.repo / ".agentic-forge" / "kept"
    kept.parent.mkdir()
    kept.write_text("x\n", encoding="utf-8")
    done = stand.python(
        str(_WATCH), "--repo", str(stand.repo), "--owner", "me", "--name", "mine", "--pr", "7",
        "--apply", GH_THREADS="1", CLAUDE_NEVER_RUNS="1",
    )
    assert done.returncode == 1, done.stdout + done.stderr
    assert len(stand.claude()) == 1 and kept.is_file()


def test_a_scheduled_pass_takes_its_model_from_the_operator_alone(stand: Stand) -> None:
    """A clock the old driver left on a PR's branch would take `models` from that tree."""
    stand.operator({"enabled": True})
    path = stand.home / ".agentic-forge" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps({**config, "models": {"software-engineer": "operator-model"}}), encoding="utf-8"
    )
    stand.committed(
        ".agentic-forge/config.json", {"models": {"software-engineer": "repo-model"}}
    )
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1")
    (session,) = stand.claude()
    assert session["argv"][session["argv"].index("--model") + 1] == "operator-model"


@pytest.mark.parametrize(
    ("config", "said"),
    [
        (None, "off: pr_watcher.enabled is not true in ~/.agentic-forge/config.json"),
        ({"pr_watcher": {"enabled": False}}, "off, by this repo's"),
    ],
)
def test_health_says_why_the_watcher_is_off(
    stand: Stand, config: dict[str, Any] | None, said: str
) -> None:
    if config is not None:
        stand.operator({"enabled": True})
        stand.committed(".agentic-forge/config.json", config)
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    assert said in health


def test_health_says_nothing_of_the_watcher_when_it_is_on(stand: Stand) -> None:
    stand.operator({"enabled": True})
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    assert "pr-watcher:" not in health


def test_a_warning_prints_once_a_run_however_often_settings_are_read(stand: Stand) -> None:
    stand.committed(".agentic-forge/config.json", {"pr_watcher": {"bot": "x"}})
    done = stand.tick()
    assert done.stderr.count("pr_watcher.bot in a repo config is ignored") == 1


@pytest.mark.parametrize(
    ("repo_says", "merged"),
    [
        ({"auto_merge": False}, False),
        ({"auto_merge": []}, False),
        ({"enabled": False}, False),
        ({"auto_merge": True}, True),  # no effect either way: the operator's is on
        ({"auto_merge": ["other/repo"]}, True),  # a list is not an off
    ],
)
def test_a_repo_can_switch_merging_off_and_not_narrow_it_by_listing(
    stand: Stand, repo_says: dict[str, Any], merged: bool
) -> None:
    """Regression: 2026.11.2 held on a repo's `auto_merge: false`, and this must too."""
    stand.operator(_ALL_ON)
    stand.committed(".agentic-forge/config.json", {"pr_watcher": repo_says})
    oid = stand.pull_request(7)
    stand.queue(7)
    done = stand.tick()
    assert bool(stand.gh("pr", "merge")) is merged, done.stdout + done.stderr
    if merged:
        assert _merged(7, oid) in stand.gh("pr", "merge")


def test_a_repos_auto_watch_off_stops_the_hook_queueing(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.committed(".agentic-forge/config.json", {"pr_watcher": {"auto_watch": False}})
    done = stand.python(str(_PR_CREATED), stdin=json.dumps({
        "cwd": str(stand.repo),
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create --fill"},
        "tool_response": {"stdout": "https://github.com/me/mine/pull/8\n"},
    }))
    assert "queued for the scheduled watch" not in done.stdout
    assert not (stand.state() / "pr-watch-queue.json").exists()


def test_a_session_that_never_ran_posts_nothing_and_fails_the_job(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", CLAUDE_NEVER_RUNS="1")
    assert done.returncode == 1
    assert _posted(stand) == [] and stand.in_origin("rev-parse", "pr-7") == oid
    assert "undetermined" in stand.diagnostics()
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    (line,) = [line for line in health.splitlines() if line.strip().startswith("pr-watch-queue ")]
    assert "failed" in line


def test_a_denied_session_is_not_a_no_change_made(stand: Stand) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", CLAUDE_DENIED="1")
    assert done.returncode == 1
    assert _posted(stand) == []  # above all, not the canned "No change made"
    assert stand.in_origin("rev-parse", "pr-7") == oid  # what it did edit went with the worktree


@pytest.mark.parametrize("association", ["CONTRIBUTOR", "NONE", "absent", "OTHER"])
def test_a_strangers_thread_reaches_no_fixer_and_no_stranger_clears_the_gate(
    stand: Stand, association: str
) -> None:
    stand.operator(_ALL_ON)
    stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", GH_THREAD_ASSOCIATION=association)
    assert done.returncode == 0, done.stdout + done.stderr  # held, which is not a failure
    assert stand.claude() == [] and _posted(stand) == [] and stand.gh("pr", "merge") == []
    assert "held, its author is not trusted" in stand.diagnostics()


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_a_thread_from_someone_with_standing_reaches_the_fixer(
    stand: Stand, association: str
) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1", GH_THREAD_ASSOCIATION=association)
    assert len(stand.claude()) == 1


@pytest.mark.parametrize(
    "written",
    [
        ".github/workflows/x.yml",
        ".gitattributes",
        ".gitmodules",
        ".husky/x",
        ".agentic-forge/x",
        ".claude/settings.json",
        ".mcp.json",
    ],
)
def test_a_session_that_changes_a_protected_path_gets_no_commit(
    stand: Stand, written: str
) -> None:
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1", CLAUDE_WRITES=written)
    assert done.returncode == 1
    assert stand.in_origin("rev-parse", "pr-7") == oid and _posted(stand) == []
    assert "not committed, and nothing posted" in stand.diagnostics()


def test_a_refused_push_leaves_github_told_nothing(stand: Stand) -> None:
    """A real refusal, from the origin's own hook: the reply used to go first, then the fix died."""
    hook = stand.origin / "hooks" / "pre-receive"
    hook.parent.mkdir(exist_ok=True)
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    hook.write_text("#!/bin/sh\necho refused >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    stand.queue(7)
    done = stand.tick(GH_THREADS="1")
    assert done.returncode == 1
    assert stand.in_origin("rev-parse", "pr-7") == oid and _posted(stand) == []
    assert "nothing posted for its fixes" in stand.diagnostics()


def test_a_pushed_fix_is_replied_to_and_resolved_after_it_lands(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    stand.tick(GH_THREADS="1")
    posted = _posted(stand)
    assert len(posted) == 2 and "addPullRequestReviewThreadReply" in posted[0]
    assert "resolveReviewThread" in posted[1]
    assert stand.in_origin("rev-parse", "pr-7~1")


def test_a_smudge_filter_is_told_to_skip_lfs(stand: Stand) -> None:
    canary = stand.base / "smudged"
    stand.git("config", "filter.lfs.smudge", f"sh -c 'echo $GIT_LFS_SKIP_SMUDGE >> {canary}; cat'")
    stand.git("checkout", "-qb", "pr-7", "main")
    (stand.repo / ".gitattributes").write_text("*.bin filter=lfs\n", encoding="utf-8")
    (stand.repo / "a.bin").write_text("pointer\n", encoding="utf-8")
    stand.commit()
    stand.git("push", "-q", "origin", "pr-7", "pr-7:refs/pull/7/head")
    stand.git("checkout", "-q", "main")
    stand.git("branch", "-qD", "pr-7")
    canary.unlink(missing_ok=True)
    stand.operator({"enabled": True})
    stand.queue(7)
    stand.tick()
    assert canary.read_text(encoding="utf-8").split() == ["1"]


def test_a_record_a_killed_add_left_is_removed(stand: Stand) -> None:
    """`git worktree add` locks its record as `initializing`: one --force refuses, prune skips."""
    stand.operator({"enabled": True})
    passes = stand.passes()
    passes.mkdir(parents=True)
    stuck = passes / "pr1-stuck"
    stand.git("worktree", "add", "-q", "--detach", str(stuck), "HEAD")
    stand.git("worktree", "lock", "--reason", "initializing", str(stuck))
    done = stand.tick()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "pr1-stuck" not in stand.git("worktree", "list", "--porcelain")
    assert not stuck.exists()


def test_a_worktree_with_a_non_utf8_name_stops_nothing(stand: Stand) -> None:
    stand.operator({"enabled": True})
    bad = os.fsencode(stand.base) + b"/wt-\xe9"
    subprocess.run(
        [b"git", b"-C", os.fsencode(stand.repo), b"worktree", b"add", b"-q", b"--detach", bad],
        check=True, capture_output=True, env=stand.env,
    )
    done = stand.tick()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "## pr-watch-queue" in done.stdout


def _single_state_directory_on_moved_head(stand: Stand, clock: Path) -> None:
    """Every record of a pass under the clock's own state, and no directory per pass beside it."""
    state = stand.state(clock)
    stand.operator({"enabled": True})
    state.mkdir(parents=True, exist_ok=True)
    (state / "pr-watch-queue.json").write_text(
        json.dumps([{"owner": "me", "name": "mine", "number": 7}]), encoding="utf-8"
    )
    before = {p.name for p in state.parent.iterdir()}
    done = stand.tick(repo=clock, GH_THREADS="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert {p.name for p in state.parent.iterdir()} == before  # no new directory for a pass
    log = (state / "diagnostics.jsonl").read_text(encoding="utf-8")
    assert "pushed HEAD:pr-7" in log  # and the audit trail stayed with the operator


def test_a_clock_in_a_submodule_keeps_one_state_directory(stand: Stand) -> None:
    stand.pull_request(7)
    outer = stand.base / "outer"
    outer.mkdir()
    stand.git("init", "-q", "-b", "main", cwd=outer)
    (outer / "f").write_text("x\n", encoding="utf-8")
    stand.git("add", "-A", cwd=outer)
    stand.git("commit", "-qm", "c", cwd=outer)
    stand.git(
        "-c", "protocol.ext.allow=always", "submodule", "add", "-q",
        "git@github.com:me/mine.git", "sub", cwd=outer,
    )
    _single_state_directory_on_moved_head(stand, outer / "sub")


def test_a_clock_with_a_separate_git_dir_keeps_one_state_directory(stand: Stand) -> None:
    stand.pull_request(7)
    clone = stand.base / "separate"
    subprocess.run(
        ["git", "clone", "-q", "--separate-git-dir", str(stand.base / "sep.git"),
         "git@github.com:me/mine.git", str(clone)],
        check=True, capture_output=True, env=stand.env,
    )
    _single_state_directory_on_moved_head(stand, clone)


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
def test_a_prs_hook_does_not_run_in_the_real_cli_under_the_real_driver(stand: Stand) -> None:
    """End to end: the argv the driver's child builds, read by the CLI. Nothing leaves the machine:
    there are no credentials and the API address is a closed local port. The control is the CLI run
    by hand in the same tree under `project`, so a hook that stopped firing altogether cannot pass
    this."""
    real = shutil.which("claude")
    assert real is not None
    fake = Path(stand.env["PATH"].split(os.pathsep)[0]) / "claude"
    fake.unlink()
    fake.symlink_to(real)
    canary = stand.base / "canary"
    settings = {"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "sh .pwn.sh"}]},
    ]}}
    stand.git("checkout", "-qb", "pr-7", "main")
    (stand.repo / ".pwn.sh").write_text('echo ran >> "$CANARY"\n', encoding="utf-8")
    stand.committed(".claude/settings.json", settings)
    stand.git("push", "-q", "origin", "pr-7", "pr-7:refs/pull/7/head")
    control = stand.base / "control"
    stand.git("worktree", "add", "-q", "--detach", str(control), "pr-7")
    stand.git("checkout", "-q", "main")
    stand.git("branch", "-qD", "pr-7")
    stand.operator({"enabled": True})
    stand.queue(7)
    env = {"CANARY": str(canary), "ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}

    stand.tick(GH_THREADS="1", **env)
    assert not canary.exists()

    subprocess.run(
        [real, "-p", "x", "--setting-sources", "project"], cwd=control,
        env={**stand.env, **env}, capture_output=True, text=True, timeout=120, check=False,
    )
    assert canary.read_text(encoding="utf-8").startswith("ran")


# --- C: committed legacy files are not authoritative ----------------------------------------


_VICTIM_QUEUE = [{"owner": "me", "name": "mine", "number": 42}]


@_JSONSCHEMA
def test_a_committed_queue_is_not_drained(bare_stand: Stand) -> None:
    stand = bare_stand
    stand.operator(_ALL_ON)
    stand.committed(".agentic-forge/pr-watch-queue.json", _VICTIM_QUEUE)
    done = stand.tick()
    assert stand.gh() == [], done.stdout + done.stderr
    assert "pr-watch-queue: empty" in done.stdout
    assert "Not read and not imported" in done.stdout and "pr-watch-queue.json" in done.stdout


def test_a_committed_schedule_does_not_say_nothing_is_due(stand: Stand) -> None:
    far = {
        name: {"last_run": 4_000_000_000.0, "status": "ok", "runs": 1, "failures": 0}
        for name in ("pr-watch-queue", "pr-watch", "kb-maintenance", "audit-digest")
    }
    stand.committed(".agentic-forge/schedule-state.json", far)
    done = stand.python(str(_SCHEDULED), "--repo", str(stand.repo))
    assert "No jobs due" not in done.stdout
    assert "## pr-watch-queue" in done.stdout and "schedule-state.json" in done.stdout


def test_the_hook_does_not_import_a_committed_queue(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.committed(".agentic-forge/pr-watch-queue.json", _VICTIM_QUEUE)
    done = stand.python(str(_PR_CREATED), stdin=json.dumps({
        "cwd": str(stand.repo),
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create --fill"},
        "tool_response": {"stdout": "https://github.com/me/mine/pull/8\n"},
    }))
    message = json.loads(done.stdout)["systemMessage"]
    assert "queued for the scheduled watch" in message
    assert "pr-watch-queue.json under .agentic-forge/" in message
    queue = json.loads((stand.state() / "pr-watch-queue.json").read_text(encoding="utf-8"))
    assert [entry["number"] for entry in queue] == [8]


def test_the_migration_does_not_import_a_committed_queue_or_schedule(stand: Stand) -> None:
    stand.committed(".agentic-forge/pr-watch-queue.json", _VICTIM_QUEUE)
    stand.committed(
        ".agentic-forge/schedule-state.json", {"pr-watch": {"last_run": 4_000_000_000.0}}
    )
    dry = stand.python(str(_MIGRATE), "--repo", str(stand.repo))
    assert dry.stdout.count("not imported, because a repo can commit it") == 2
    done = stand.python(str(_MIGRATE), "--repo", str(stand.repo), "--apply")
    assert done.returncode == 0, done.stderr
    assert "pr-watch-queue.json: deleted (not imported" in done.stdout
    assert "schedule-state.json: deleted (not imported" in done.stdout
    assert not (stand.state() / "pr-watch-queue.json").exists()
    assert not (stand.state() / "schedule-state.json").exists()
    assert done.stdout.count("it was tracked, so it now shows as a deletion to commit") == 2
    assert "D .agentic-forge/pr-watch-queue.json" in stand.git("status", "--porcelain")


def test_the_migration_says_nothing_of_a_deletion_for_an_untracked_file(stand: Stand) -> None:
    legacy = stand.repo / ".agentic-forge" / "pr-watch-queue.json"
    legacy.parent.mkdir()
    legacy.write_text("[]", encoding="utf-8")
    done = stand.python(str(_MIGRATE), "--repo", str(stand.repo), "--apply")
    assert done.returncode == 0 and "pr-watch-queue.json: deleted" in done.stdout
    assert "shows as a deletion" not in done.stdout


def test_the_session_notice_names_what_is_dropped_and_following_it_ends_it(stand: Stand) -> None:
    stand.committed(".agentic-forge/pr-watch-queue.json", _VICTIM_QUEUE)
    payload = json.dumps({"cwd": str(stand.repo), "session_id": "s1"})
    message = json.loads(stand.python(str(_SESSION_START), stdin=payload).stdout)["systemMessage"]
    assert "Not read and not imported" in message and "pr-watch-queue.json" in message
    assert "runtime state still lives" not in message  # there is nothing here that moves
    stand.python(str(_MIGRATE), "--repo", str(stand.repo), "--apply")
    payload = json.dumps({"cwd": str(stand.repo), "session_id": "s2"})
    after = json.loads(stand.python(str(_SESSION_START), stdin=payload).stdout)
    assert "systemMessage" not in after


def test_a_renamed_repos_entry_is_dropped_and_shows_in_health(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.queue(7, owner="me", name="renamed")
    done = stand.tick()
    assert stand.gh() == [] and done.returncode == 0
    health = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health").stdout
    assert "1 queued PR(s) dropped in the last week, last me/renamed#7" in health
    assert "update the origin remote" in health


def test_an_entry_for_another_repo_is_dropped_with_a_reason(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.queue(42, owner="victim-org", name="prod")
    done = stand.tick()
    assert stand.gh() == [] and done.returncode == 0
    reason = "not this checkout's origin, and not in the user-level pr_watcher.repos"
    assert reason in done.stdout and reason in stand.diagnostics()
    assert "dropped victim-org/prod#42" in stand.diagnostics()
    assert json.loads((stand.state() / "pr-watch-queue.json").read_text(encoding="utf-8")) == []


def test_the_operators_repos_lets_another_repo_through_to_a_merge(stand: Stand) -> None:
    stand.operator({**_ALL_ON, "repos": ["victim-org/prod"]})
    stand.queue(42, owner="victim-org", name="prod")
    stand.tick(GH_PR_LIST="", GH_HEAD_OID="c" * 40)
    assert _merged(42, "c" * 40, slug="victim-org/prod") in stand.gh()


def test_a_repos_list_in_the_repo_does_not_let_another_repo_through(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.committed(".agentic-forge/config.json", {"pr_watcher": {"repos": ["victim-org/prod"]}})
    stand.queue(42, owner="victim-org", name="prod")
    stand.tick()
    assert stand.gh() == []


def test_a_checkout_with_no_origin_has_no_own_repo(stand: Stand) -> None:
    stand.operator(_ALL_ON)
    stand.git("remote", "remove", "origin")
    stand.queue(7)
    stand.tick()
    assert stand.gh() == []


def test_an_origin_the_parser_does_not_read_fails_closed(stand: Stand) -> None:
    """An SSH host alias names no repo here: its queue is dropped, and listing the repo allows a
    merge by slug but no fix, since nothing says that `origin` is that repo."""
    stand.operator(_ALL_ON)
    stand.git("remote", "set-url", "origin", "git@work-github:me/mine.git")
    oid = stand.pull_request(7)
    stand.queue(7)
    stand.tick()
    assert stand.gh() == [] and "dropped me/mine#7" in stand.diagnostics()

    stand.operator({**_ALL_ON, "repos": ["me/mine"]})
    stand.queue(7)
    done = stand.tick(GH_PR_LIST="", GH_THREADS="1")
    assert done.returncode == 1 and stand.claude() == []
    assert "fix and push refused for me/mine#7" in stand.diagnostics()
    assert _merged(7, oid) not in stand.gh()  # an open thread shuts the gate


def test_the_own_repo_matches_whatever_its_case(stand: Stand) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7, owner="ME", name="MINE")
    stand.tick(GH_THREADS="1")
    assert len(stand.claude()) == 1

    # And the other way round: `origin` is the one in capitals, and the PR still gets its fix pass.
    stand.git("remote", "set-url", "origin", "git@github.com:ME/MINE.git")
    stand.pull_request(8)
    stand.queue(8)
    stand.tick(GH_THREADS="1")
    assert len(stand.claude()) == 2


def test_a_drain_in_another_clone_says_where_the_queue_is(stand: Stand) -> None:
    """The state root is keyed by path, so a second clone has its own empty queue."""
    stand.operator({"enabled": True})
    stand.queue(7)
    clone = stand.base / "second-clone"
    clone.mkdir()
    stand.git("init", "-q", "-b", "main", cwd=clone)
    stand.git("remote", "add", "origin", "git@github.com:me/mine.git", cwd=clone)
    done = stand.tick(repo=clone)
    assert "pr-watch-queue: empty here; 1 PR(s) of me/mine are queued under another" in done.stdout
    assert stand.gh() == []
    (stand.state() / "pr-watch-queue.json").write_text("[]", encoding="utf-8")
    assert "pr-watch-queue: empty\n" in stand.tick(repo=clone).stdout


# --- the upgrade from 2026.11.2, and what normal running leaves behind ----------------------


_ALL_JOBS = (
    "pr-watch-queue", "kb-maintenance", "deploy-digest", "audit-digest", "diagnostics-digest",
    "review-scan", "pr-watch",
)


def _health(stand: Stand) -> str:
    done = stand.python(str(_SCHEDULED), "--repo", str(stand.repo), "--health")
    assert done.returncode == 0, done.stderr
    return str(done.stdout)


def test_several_normal_passes_leave_no_worktree_directory_or_ref(stand: Stand) -> None:
    """Each pass fixes a thread, pushes and goes. Nothing about the operator's clone grows by one
    per pass: not a worktree record, not a directory, not a ref, not a second state directory."""
    stand.operator({"enabled": True})
    stand.pull_request(7)
    refs_before = stand.git("for-each-ref", "--format=%(refname)")
    before = stand.snapshot()
    for pass_number in range(3):
        stand.queue(7)
        done = stand.tick(GH_THREADS="1", CLAUDE_WRITES=f"fix-{pass_number}.txt")
        assert done.returncode == 0, done.stdout + done.stderr
        stand.in_origin("update-ref", "refs/pull/7/head", "refs/heads/pr-7")  # as GitHub does
    assert stand.git("rev-list", "--count", "main..pr-7", cwd=stand.origin) == "4"  # the PR + 3
    assert stand.git("worktree", "list", "--porcelain").count("worktree ") == 1
    assert not (stand.repo / ".git" / "worktrees").exists()
    assert list(stand.passes().iterdir()) == []
    assert not (stand.repo / ".git" / "FETCH_HEAD").exists()
    assert stand.git("for-each-ref", "--format=%(refname)") == refs_before
    assert stand.snapshot() == before
    assert [path.name for path in stand.state().parent.iterdir()] == [stand.state().name]


def test_the_queue_and_job_state_under_the_state_root_carry_over(stand: Stand) -> None:
    """What the previous release left where this one reads: the clock does not start over, so only
    what was due runs, the entry keeps the ticks it has spent, and no notice says otherwise."""
    stand.operator({"enabled": True})
    stand.pull_request(7)
    root = stand.state()
    root.mkdir(parents=True)
    now = time.time()
    jobs = {name: {"last_run": now - 30, "status": "ok", "runs": 5, "failures": 0}
            for name in _ALL_JOBS}
    jobs["pr-watch-queue"]["last_run"] = now - 4000
    (root / "schedule-state.json").write_text(json.dumps(jobs), encoding="utf-8")
    entry = {"owner": "me", "name": "mine", "number": 7, "branch": "", "ticks": 3, "failures": 1}
    (root / "pr-watch-queue.json").write_text(json.dumps([entry]), encoding="utf-8")

    assert "pr-watch-queue (10min) — ok  runs=5" in _health(stand)
    done = stand.python(str(_SCHEDULED), "--repo", str(stand.repo))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "## pr-watch-queue" in done.stdout and "## kb-maintenance" not in done.stdout
    assert "Not read and not imported" not in done.stdout
    kept = json.loads((root / "pr-watch-queue.json").read_text(encoding="utf-8"))
    assert [(e["number"], e["ticks"], e["failures"]) for e in kept] == [(7, 4, 1)]
    report = _health(stand)
    assert "pr-watch-queue (10min) — ok  runs=6" in report
    assert "kb-maintenance (weekly) — ok  runs=5" in report
    again = stand.python(str(_SCHEDULED), "--repo", str(stand.repo))
    assert again.stdout.strip() == "No jobs due."


def test_an_operator_who_enabled_it_in_the_repo_gets_back_by_doing_what_it_says(
    stand: Stand,
) -> None:
    """The way back, from the output alone. The queue waits while the watcher is off, each message
    names what to do, and once the user-level file agrees with the repo's the warnings stop."""
    wanted = {"enabled": True, "auto_merge": True}
    stand.committed(".agentic-forge/config.json", {"pr_watcher": wanted})
    oid = stand.pull_request(7)
    stand.queue(7)
    queue = stand.state() / "pr-watch-queue.json"
    queued = queue.read_text(encoding="utf-8")

    off = stand.tick()
    assert off.returncode == 0
    assert "pr-watch-queue: disabled (set pr_watcher.enabled in ~/.agentic-forge/config.json)" in (
        off.stdout
    )
    assert "pr_watcher.enabled in a repo config is ignored" in off.stderr
    assert "pr_watcher.auto_merge in a repo config is ignored" in off.stderr
    assert stand.gh() == [] and queue.read_text(encoding="utf-8") == queued

    stand.operator({"enabled": True})
    only_on = stand.tick()
    assert "merged=False (held: auto_merge is off)" in only_on.stdout
    assert "pr_watcher.auto_merge in a repo config is ignored" in only_on.stderr
    assert "pr_watcher.enabled in a repo config" not in only_on.stderr
    assert stand.gh("pr", "merge") == []

    stand.operator(wanted)
    moved = stand.tick()
    assert stand.gh("pr", "merge") == [_merged(7, oid)], moved.stdout + moved.stderr
    assert "pr_watcher." not in moved.stderr
    assert "0 failing" in _health(stand)


@pytest.mark.parametrize(
    "failure",
    [
        {"GH_THREADS": "1", "CLAUDE_NEVER_RUNS": "1"},
        {"GH_BARE": "/nonexistent/origin.git"},
    ],
    ids=["session-never-ran", "fetch-failed"],
)
def test_health_shows_a_failed_pass_and_then_the_recovery(
    stand: Stand, failure: dict[str, str]
) -> None:
    stand.operator({"enabled": True})
    stand.pull_request(7)
    stand.queue(7)
    assert stand.tick(**failure).returncode == 1
    report = _health(stand)
    assert "1 failing" in report and "pr-watch-queue (10min) — failed  runs=1 failures=1" in report
    assert stand.git("worktree", "list", "--porcelain").count("worktree ") == 1

    assert stand.tick().returncode == 0
    report = _health(stand)
    assert "0 failing" in report and "pr-watch-queue (10min) — ok  runs=2 failures=0" in report


def test_a_commit_that_fails_claims_no_fix(stand: Stand) -> None:
    """A signing key the clock cannot reach, or no identity under cron. The session edited the tree
    and git refused to commit it, so there is nothing to say "Addressed in" about: the push finds
    nothing new and succeeds. Resolving the thread is what would let the next poll merge."""
    stand.operator({"enabled": True})
    oid = stand.pull_request(7)
    stand.queue(7)
    refuses = shutil.which("false")
    assert refuses is not None
    stand.git("config", "commit.gpgsign", "true")
    stand.git("config", "gpg.program", refuses)
    done = stand.tick(GH_THREADS="1")
    assert stand.in_origin("rev-parse", "pr-7") == oid  # nothing arrived, as the push had nothing
    assert [c for c in stand.gh("api", "graphql") if "mutation" in c] == []
    assert done.returncode == 1


def test_a_link_at_any_component_of_a_protected_links_path_is_protected() -> None:
    from agentic_forge import pr_watch as lib

    links = {".github/c": "../alias/c", "alias": "real"}
    targets = lib.protected_link_targets(links)
    assert set(targets) == {"alias", "alias/c", "real/c"}
    assert lib.link_targets_touched(["real/c"], targets) == [".github/c"]
    assert lib.link_targets_touched(["alias"], targets) == [".github/c"]
    assert lib.link_targets_touched(["real/other"], targets) == []


def test_a_link_loop_and_a_target_outside_the_tree_end_the_walk() -> None:
    from agentic_forge import pr_watch as lib

    assert set(lib.protected_link_targets({".github/a": "b", ".github/b": "a"})) == {
        ".github/a",
        ".github/b",
    }
    assert lib.protected_link_targets({".github/a": "../../out"}) == {}
    assert lib.protected_link_targets({".github/a": "/abs/out"}) == {}
