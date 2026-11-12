"""``af.py pr-review``, run as a skill runs it: ``python3 -E``, a real process, a ``gh`` stub on
PATH that answers from a script and logs its argv, and no network."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_forge import pr_review

_REPO = Path(__file__).resolve().parents[1]
_PLUGIN = _REPO / "plugin"
_AF = _PLUGIN / "bin" / "af.py"
_HEAD = "b" * 40
_ZW = "\u200b"

_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+y = 3
 z = 4
"""


def _python3() -> str:
    found = shutil.which("python3")
    assert found, "no python3 on PATH"
    return found


def _answer(**pr: Any) -> dict[str, Any]:
    node = {"number": 7, "state": "OPEN", "headRefOid": _HEAD, "author": {"login": "ann"}}
    node.update(pr)
    return {"data": {"viewer": {"login": "rev"}, "repository": {"pullRequest": node}}}


def _stub_gh(
    tmp_path: Path, *, heads: list[Any] | None = None, diff: str = _DIFF, head_code: int = 0,
    diff_code: int = 0,
) -> dict[str, str]:
    """A ``gh`` that answers the head query from ``heads`` in order (the last one repeats), and
    ``gh pr diff`` with ``diff``; each with its own exit code. Every call is logged."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = {
        "heads": [_answer()] if heads is None else heads, "diff": diff,
        "head_code": head_code, "diff_code": diff_code,
        "log": str(tmp_path / "gh.log"), "count": str(tmp_path / "gh.count"),
    }
    (tmp_path / "gh.json").write_text(json.dumps(script), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        f"#!{_python3()} -S\nimport json, os, sys\n"
        f"s = json.load(open({str(tmp_path / 'gh.json')!r}))\n"
        "open(s['log'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['pr', 'diff']:\n"
        "    sys.stdout.write(s['diff'])\n"
        "    if s['diff_code']: sys.stderr.write('diff failed')\n"
        "    sys.exit(s['diff_code'])\n"
        "n = int(open(s['count']).read()) if os.path.exists(s['count']) else 0\n"
        "open(s['count'], 'w').write(str(n + 1))\n"
        "if s['head_code']:\n"
        "    sys.stderr.write('HTTP 502: bad gateway')\n"
        "    sys.exit(s['head_code'])\n"
        "print(json.dumps(s['heads'][min(n, len(s['heads']) - 1)]))\n",
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def _gh_calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "gh.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _checkout(tmp_path: Path, origin: str = "https://github.com/o/n.git") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", origin], check=True)
    return repo


def _findings(tmp_path: Path, data: Any) -> Path:
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


_FINDINGS = [
    {"severity": "major", "location": "src/app.py:3", "issue": "y is unused, ask @alice",
     "suggestion": "Remove y."},
    {"severity": "minor", "location": "README.md:1", "issue": "Stale.", "suggestion": "Update."},
]


def _run(
    tmp_path: Path, env: dict[str, str], *extra: str, findings: Any = None, head: str = _HEAD,
    repo: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    repo = repo or _checkout(tmp_path)
    source = _findings(tmp_path, _FINDINGS if findings is None else findings)
    args = ["pr-review", "--repo", str(repo), "--pr", "7", "--head", head,
            "--findings-json", str(source), "--out", str(tmp_path / "out" / "review.json"), *extra]
    return subprocess.run(
        [_python3(), "-E", str(_AF), *args], cwd=tmp_path, capture_output=True, text=True,
        env=env, check=False, timeout=60,
    )


def _refused(done: subprocess.CompletedProcess[str]) -> str:
    assert done.returncode == 1, (done.stdout, done.stderr)
    assert done.stdout == ""
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith("af.py: pr-review: ")
    return done.stderr


def test_it_builds_the_payload_and_prints_the_post_command(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path)
    done = _run(tmp_path, env)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    out = tmp_path / "out" / "review.json"
    assert result["payload"] == str(out)
    assert result["post"]["argv"] == [
        "gh", "api", "-X", "POST", "repos/o/n/pulls/7/reviews", "--input", str(out)
    ]
    assert shlex.split(result["post"]["shell"]) == result["post"]["argv"]
    assert (result["repo"], result["number"], result["head"]) == ("o/n", 7, _HEAD)
    assert (result["verdict"], result["event"]) == ("changes", "REQUEST_CHANGES")
    assert (result["inline"], result["in_body"], result["omitted"]) == (1, 1, 0)
    assert result["placements"][1] == {
        "location": "README.md:1", "inline": False, "reason": "the file is not in the diff"
    }

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["commit_id"] == _HEAD
    assert payload["event"] == "REQUEST_CHANGES"
    [comment] = payload["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("src/app.py", 3, "RIGHT")
    assert f"@{_ZW}alice" in comment["body"] and "@alice" not in comment["body"]
    assert "README.md:1" in payload["body"]


def test_it_reads_the_head_before_and_after_the_diff_and_posts_nothing(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path)
    assert _run(tmp_path, env).returncode == 0
    calls = _gh_calls(tmp_path)
    assert [c[:2] for c in calls] == [["api", "graphql"], ["pr", "diff"], ["api", "graphql"]]
    assert calls[1] == ["pr", "diff", "7", "-R", "o/n", "--color", "never"]
    assert not any("POST" in call for call in calls)  # posting is the session's, not this command's


def test_findings_can_come_from_stdin(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path)
    repo = _checkout(tmp_path)
    done = subprocess.run(
        [_python3(), "-E", str(_AF), "pr-review", "--repo", str(repo), "--pr", "7", "--head",
         _HEAD, "--findings-json", "-", "--out", str(tmp_path / "p.json")],
        cwd=tmp_path, capture_output=True, text=True, env=env, check=False, timeout=60,
        input=json.dumps({"verdict": "approve", "findings": []}),
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["event"] == "COMMENT"


@pytest.mark.parametrize(
    ("extra", "findings", "event", "says"),
    [
        ((), [], "COMMENT", "branch protection"),
        (("--event", "comment"), _FINDINGS, "COMMENT", "--event comment"),
        (("--event", "approve"), [], "APPROVE", "--event approve"),
        (("--event", "request-changes"), _FINDINGS, "REQUEST_CHANGES", "requests changes"),
    ],
)
def test_event_mapping(
    tmp_path: Path, extra: tuple[str, ...], findings: Any, event: str, says: str
) -> None:
    done = _run(tmp_path, _stub_gh(tmp_path), *extra, findings=findings)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["event"] == event and says in result["event_reason"]
    payload = json.loads((tmp_path / "out" / "review.json").read_text(encoding="utf-8"))
    assert payload["event"] == event


def test_on_your_own_pr_it_is_a_comment_that_says_why(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path, heads=[_answer(author={"login": "REV"})])
    result = json.loads(_run(tmp_path, env).stdout)
    assert result["event"] == "COMMENT"
    assert "your own pull request" in result["event_reason"]


def test_approve_on_a_changes_verdict_is_refused(tmp_path: Path) -> None:
    says = _refused(_run(tmp_path, _stub_gh(tmp_path), "--event", "approve"))
    assert "cannot approve" in says
    assert _gh_calls(tmp_path) == []


def test_a_head_that_moved_before_the_review_is_refused(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path, heads=[_answer(headRefOid="c" * 40)])
    says = _refused(_run(tmp_path, env))
    assert "a push came in after the review" in says
    assert not (tmp_path / "out" / "review.json").exists()
    assert [c[:2] for c in _gh_calls(tmp_path)] == [["api", "graphql"]]  # no diff was read


def test_a_head_that_moved_while_the_diff_was_read_is_refused(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path, heads=[_answer(), _answer(headRefOid="c" * 40)])
    assert "a push came in" in _refused(_run(tmp_path, env))
    assert not (tmp_path / "out" / "review.json").exists()


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_a_closed_or_merged_pr_is_refused(tmp_path: Path, state: str) -> None:
    says = _refused(_run(tmp_path, _stub_gh(tmp_path, heads=[_answer(state=state)])))
    assert state in says and "nothing to review" in says


def test_a_failing_gh_is_refused(tmp_path: Path) -> None:
    says = _refused(_run(tmp_path, _stub_gh(tmp_path, head_code=1)))
    assert "gh exited 1" in says and "502" in says


def test_a_failing_diff_is_refused(tmp_path: Path) -> None:
    says = _refused(_run(tmp_path, _stub_gh(tmp_path, diff_code=1)))
    assert "gh exited 1" in says and "diff failed" in says


def test_an_answer_that_is_not_json_is_refused(tmp_path: Path) -> None:
    _refused(_run(tmp_path, _stub_gh(tmp_path, heads=["<html>"])))


def test_no_gh_is_refused(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    git = shutil.which("git")
    assert git
    os.symlink(git, empty / "git")
    env["PATH"] = str(empty)
    assert "gh is not on PATH" in _refused(_run(tmp_path, env))


def test_a_checkout_without_a_github_origin_is_refused(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path)
    repo = _checkout(tmp_path, origin="https://gitlab.com/o/n.git")
    assert "not a GitHub repository" in _refused(_run(tmp_path, env, repo=repo))
    assert _gh_calls(tmp_path) == []


@pytest.mark.parametrize(
    ("findings", "says"),
    [
        ("{not json", "not JSON"),
        ({"finding": []}, "no 'findings' key"),
        ([{"severity": "fatal", "location": "a:1", "issue": "i", "suggestion": "s"}], "severity"),
        ({"verdict": "approve", "findings": [_FINDINGS[0]]}, "that is changes"),
    ],
)
def test_malformed_findings_are_refused_before_gh_is_asked(
    tmp_path: Path, findings: Any, says: str
) -> None:
    env = _stub_gh(tmp_path)
    assert says in _refused(_run(tmp_path, env, findings=findings))
    assert _gh_calls(tmp_path) == []


@pytest.mark.parametrize("head", ["abc123", "B" * 39, "x" * 40, "b" * 41])
def test_a_head_that_is_not_a_full_commit_id_is_refused(tmp_path: Path, head: str) -> None:
    env = _stub_gh(tmp_path)
    assert "--head" in _refused(_run(tmp_path, env, head=head))
    assert _gh_calls(tmp_path) == []


def test_an_uppercase_head_is_the_same_commit(tmp_path: Path) -> None:
    done = _run(tmp_path, _stub_gh(tmp_path), head=_HEAD.upper())
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["head"] == _HEAD


def test_the_payload_is_not_written_through_a_link(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path)
    target = tmp_path / "elsewhere.json"
    target.write_text("keep", encoding="utf-8")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "review.json").symlink_to(target)
    _refused(_run(tmp_path, env))
    assert target.read_text(encoding="utf-8") == "keep"


def test_an_out_that_is_a_directory_is_refused(tmp_path: Path) -> None:
    env = _stub_gh(tmp_path)
    (tmp_path / "out" / "review.json").mkdir(parents=True)
    assert "is a directory" in _refused(_run(tmp_path, env))


def _load_af() -> Any:
    spec = importlib.util.spec_from_file_location("_af_pr_review", _AF)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def test_a_diff_past_the_cap_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """In-process, with the 16 MB cap lowered: a real process is not fed that much here."""
    env = _stub_gh(tmp_path)
    for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
        monkeypatch.setenv(key, "")  # main() adds its git setting; this puts them back after
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setattr(pr_review, "MAX_DIFF_CHARS", len(_DIFF) - 1)
    repo = _checkout(tmp_path)
    source = _findings(tmp_path, _FINDINGS)
    code = _load_af().main([
        "pr-review", "--repo", str(repo), "--pr", "7", "--head", _HEAD, "--findings-json",
        str(source), "--out", str(tmp_path / "p.json"),
    ])
    assert code == 1
    assert f"the diff is over {len(_DIFF) - 1} characters" in capsys.readouterr().err
    assert not (tmp_path / "p.json").exists()


def test_the_event_choices_are_the_librarys() -> None:
    parser = _load_af().build_parser()
    commands = next(a for a in parser._actions if a.dest == "command").choices
    event = next(a for a in commands["pr-review"]._actions if a.dest == "event")
    assert tuple(event.choices) == pr_review.EVENTS
    assert event.default == "request-changes"
