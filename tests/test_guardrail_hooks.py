from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest

from agentic_forge import diagnostics

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "plugin" / "hooks" / "scripts"))

import audit_log  # noqa: E402
import budget  # noqa: E402
import commit_gate  # noqa: E402
import security  # noqa: E402

from agentic_forge import guardrails, observability  # noqa: E402


def _stdin(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))


# --- security ----------------------------------------------------------------


def test_security_blocks_dangerous(monkeypatch, capsys) -> None:
    _stdin(monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert security.main() == 2
    assert "security hook" in capsys.readouterr().err


def test_security_allows_safe(monkeypatch) -> None:
    _stdin(monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    assert security.main() == 0


def test_security_ignores_non_bash() -> None:
    payload = {"tool_name": "Write", "tool_input": {"file_path": "x"}}
    assert security.decide(payload) == guardrails.ALLOW


def test_security_bad_stdin_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert security.main() == 0  # never blocks on its own error


def test_security_block_record_names_the_rule_and_what_matched(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A logged block must be diagnosable on its own: the command is capped at 500 chars and in the
    field the matched text was usually past the cut (ADR 0081)."""
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    padding = "echo " + "x" * 700  # push the real command past the record's 500-char cap
    _stdin(
        monkeypatch,
        {
            "tool_name": "Bash",
            "tool_input": {"command": f"{padding}; rm -rf /usr/lib"},
            "cwd": str(tmp_path),
            "session_id": "s-evidence",
        },
    )
    assert security.main() == 2
    capsys.readouterr()
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    event = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert event["context"]["rule"] == "rm-system-dir"
    assert "rm -rf /usr/lib" in event["context"]["evidence"]
    assert "rm -rf /usr/lib" not in event["context"]["command"]  # …which the truncation lost


# --- commit_gate -------------------------------------------------------------


def _fake_run(returncode: int, stdout: str = "gate output", stderr: str = ""):
    def run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def test_commit_gate_blocks_on_failure(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(commit_gate.subprocess, "run", _fake_run(1))
    d = commit_gate.gate_decision(
        {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path)}
    )
    assert d.block and "gate failed" in d.message


def test_commit_gate_allows_when_gate_passes(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(commit_gate.subprocess, "run", _fake_run(0))
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(tmp_path)}
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW


def test_commit_gate_fails_open_on_infra_error(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")

    def boom(*a, **k):
        raise FileNotFoundError("ruff missing")

    monkeypatch.setattr(commit_gate.subprocess, "run", boom)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git commit"},
        "cwd": str(tmp_path),
        "session_id": "s-infra",
    }
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW
    # the fail-open must be OBSERVABLE (ADR 0039): an empty diagnostics log should mean "nothing
    # went wrong", not "the gate never actually ran".
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    events = log.read_text(encoding="utf-8")
    event = json.loads(events.strip().splitlines()[-1])
    assert event["kind"] == "anomaly" and event["component"] == "commit-gate"
    assert "fail-open" in event["message"] and "FileNotFoundError" in event["message"]
    assert event["session_id"] == "s-infra" and "gate" in event["context"]


def test_commit_gate_fails_open_when_gate_unrunnable(monkeypatch, tmp_path: Path) -> None:
    # ADR 0058: `npm run lint` with no lint script / uninstalled linter is environment breakage,
    # not a code-quality failure — it must fail OPEN (not block a commit) and record an anomaly.
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")
    monkeypatch.setattr(
        commit_gate.subprocess,
        "run",
        _fake_run(1, stdout="", stderr='npm error Missing script: "lint"'),
    )
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(tmp_path),
        "session_id": "s-unrunnable",
    }
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW
    event = json.loads(
        (diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE)
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()[-1]
    )
    assert event["kind"] == "anomaly" and event["component"] == "commit-gate"
    assert "unrunnable" in event["message"] and event["session_id"] == "s-unrunnable"


def test_commit_gate_fails_open_on_shell_not_found_exit_code(monkeypatch, tmp_path: Path) -> None:
    # ADR 0059: a shell "command/file not found" (exit 127) fails OPEN via the exit code — not via
    # an over-broad output substring. Output has no unrunnable signature; the exit code does it.
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(
        commit_gate.subprocess,
        "run",
        _fake_run(127, stdout="", stderr="bash: ruff: No such file or directory"),
    )
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW


@pytest.mark.parametrize(
    "stdout",
    [
        "src/a.ts: 3 problems (3 errors, 0 warnings)",  # real lint errors
        "ERROR foo: SKILL.md not found",  # ADR 0059: "not found" in a real gate failure must block
        "E   fixture 'db' not found",  # real pytest failure containing "not found"
    ],
)
def test_commit_gate_still_blocks_on_real_failure(monkeypatch, tmp_path: Path, stdout: str) -> None:
    # A genuine non-zero (exit 1, no unrunnable signature) must still block — even when the output
    # happens to contain "not found" (the pre-0059 over-broad match would wrongly let it through).
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(commit_gate.subprocess, "run", _fake_run(1, stdout=stdout, stderr=""))
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    d = commit_gate.gate_decision(payload)
    assert d.block and "gate failed" in d.message


def test_commit_gate_skips_non_commit_and_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    ls = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert commit_gate.gate_decision(ls) == guardrails.ALLOW
    monkeypatch.setenv("AGENTIC_FORGE_SKIP_TEST_GATE", "1")
    skipped = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    assert commit_gate.gate_decision(skipped) == guardrails.ALLOW


def test_commit_gate_main_blocks(monkeypatch, tmp_path: Path, capsys) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(commit_gate.subprocess, "run", _fake_run(1))
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    _stdin(monkeypatch, payload)
    assert commit_gate.main() == 2
    assert "test-gate" in capsys.readouterr().err


def test_commit_gate_main_allows_when_gate_passes(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(commit_gate.subprocess, "run", _fake_run(0))
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    _stdin(monkeypatch, payload)
    assert commit_gate.main() == 0


# --- budget ------------------------------------------------------------------


def test_budget_warn_then_block(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(budget.tempfile, "gettempdir", lambda: str(tmp_path))
    payload = {"tool_name": "Task", "session_id": "sess"}
    assert budget.decide(payload, soft=2, hard=4) == guardrails.ALLOW  # 1
    assert budget.decide(payload, soft=2, hard=4) == guardrails.ALLOW  # 2
    assert budget.decide(payload, soft=2, hard=4).message  # 3 -> warn (non-block)
    budget.decide(payload, soft=2, hard=4)  # 4
    assert budget.decide(payload, soft=2, hard=4).block  # 5 -> block


def test_budget_ignores_non_task() -> None:
    assert budget.decide({"tool_name": "Bash"}) == guardrails.ALLOW


def test_budget_main_blocks(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(budget.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("AGENTIC_FORGE_SUBAGENT_SOFT", "0")  # caps now come from settings (ADR 0041)
    monkeypatch.setenv("AGENTIC_FORGE_SUBAGENT_HARD", "0")
    # cwd=tmp_path keeps settings resolution hermetic (no repo-local config.json bleed-in)
    _stdin(monkeypatch, {"tool_name": "Task", "session_id": "s", "cwd": str(tmp_path)})
    assert budget.main() == 2  # first spawn already over hard cap 0
    assert "budget hook" in capsys.readouterr().err


def test_budget_main_allows_under_cap(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(budget.tempfile, "gettempdir", lambda: str(tmp_path))
    _stdin(monkeypatch, {"tool_name": "Task", "session_id": "under", "cwd": str(tmp_path)})
    assert budget.main() == 0  # first spawn, under the default caps


# --- audit_log ---------------------------------------------------------------


def test_audit_log_writes_redacted(tmp_path: Path) -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "x --token=ghp_abcdefghijklmnopqrst0123"},
    }
    log = audit_log.write_audit(payload, str(tmp_path))
    line = json.loads(log.read_text(encoding="utf-8").strip())
    assert line["tool"] == "Bash" and "ghp_" not in line["input"]


def test_audit_log_main_appends(monkeypatch, tmp_path: Path) -> None:
    payload = {"tool_name": "Read", "tool_input": {"file_path": "a"}, "cwd": str(tmp_path)}
    _stdin(monkeypatch, payload)
    assert audit_log.main() == 0
    assert (diagnostics.state_root(tmp_path) / observability.AUDIT_FILE).is_file()


def test_audit_log_bad_stdin_safe(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("nope"))
    assert audit_log.main() == 0  # observability never blocks


def test_hooks_json_registers_all_events() -> None:
    raw = (_REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8")
    hooks = json.loads(raw)["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
    _scripts = (
        "security.py", "commit_gate.py", "budget.py", "audit_log.py", "session_start.py",
        "pre_router.py",
    )

    def scripts_for(event: str, matcher: str | None) -> set[str]:
        out: set[str] = set()
        for group in hooks[event]:
            if matcher is not None and group.get("matcher") != matcher:
                continue
            for h in group["hooks"]:
                out.update(s for s in _scripts if s in h["command"])
        return out

    # assert each script is wired to the RIGHT event + matcher (not just present somewhere in the
    # blob) — a script moved to the wrong event/matcher would now fail.
    assert scripts_for("UserPromptSubmit", None) == {"pre_router.py"}  # ADR 0089
    assert scripts_for("SessionStart", None) == {"session_start.py"}
    assert scripts_for("PreToolUse", "Bash") == {"security.py", "commit_gate.py"}
    assert scripts_for("PreToolUse", "Task") == {"budget.py"}
    assert scripts_for("PostToolUse", "*") == {"audit_log.py"}


def test_write_audit_from_worktree_lands_in_main_repo(tmp_path: Path) -> None:
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s"}
    path = audit_log.write_audit(payload, str(wt))
    # the trail must survive worktree removal -> it lives in the MAIN repo (field fix)
    # Keyed by the MAIN repo, under the state root — never inside the worktree (ADR 0072).
    assert path == diagnostics.state_root(main) / observability.AUDIT_FILE
    assert not (wt / ".agentic-forge").exists()
    assert json.loads(path.read_text(encoding="utf-8").strip())["tool"] == "Bash"


def test_audit_log_respects_the_logs_gate(tmp_path: Path) -> None:
    """`logs.enabled: false` stops the audit writer — the one hook that had no off switch until
    ADR 0078, and the reason a production repo kept regrowing an in-repo log."""
    cfg = tmp_path / ".agentic-forge"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text('{"logs": {"enabled": false}}', encoding="utf-8")
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp_path)}
    assert audit_log.write_audit(payload, str(tmp_path)) is None
    assert not (diagnostics.state_root(tmp_path) / observability.AUDIT_FILE).exists()


def test_audit_log_writes_when_the_gate_is_on_by_default(tmp_path: Path) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(tmp_path)}
    path = audit_log.write_audit(payload, str(tmp_path))
    assert path is not None and path.is_file()  # default is ON: the trail must not vanish silently


# --- the fail-open must reach the OPERATOR, not only the log (ADR 0081) ------


def test_commit_gate_announces_the_fail_open_once_per_session(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)

    def boom(*a, **k):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'ruff'")

    monkeypatch.setattr(commit_gate.subprocess, "run", boom)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m x"},
        "cwd": str(tmp_path),
        "session_id": "s-1",
    }
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW
    first = json.loads(capsys.readouterr().out)
    assert "NOT gated" in first["systemMessage"] and "ruff" in first["systemMessage"]

    commit_gate.gate_decision(payload)  # same session: silent
    assert capsys.readouterr().out == ""

    payload["session_id"] = "s-2"  # a new session hears it again
    commit_gate.gate_decision(payload)
    assert "systemMessage" in json.loads(capsys.readouterr().out)


def test_commit_gate_runs_the_projects_own_linter(monkeypatch, tmp_path: Path) -> None:
    """The field host had `ruff` only inside a virtualenv, so the gate never ran for two months."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    local = tmp_path / ".venv" / "bin"
    local.mkdir(parents=True)
    (local / "ruff").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (local / "ruff").chmod(0o755)
    seen: dict[str, object] = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["path"] = kwargs["env"]["PATH"]
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(commit_gate.subprocess, "run", run)
    commit_gate.gate_decision(
        {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    )
    assert seen["cmd"] == [str(local / "ruff"), "check", "."]
    assert str(local) in str(seen["path"])  # a package script's own tools resolve too


def test_commit_gate_timeout_notice_names_the_real_remedy() -> None:
    """A slow lint is not a missing tool — "install it" is the wrong advice (ADR 0082)."""
    timeout = commit_gate.fail_open_notice(
        ["npm", "run", "lint"],
        "TimeoutExpired: Command '['npm', 'run', 'lint']' timed out after 110 seconds",
    )
    assert "timed out" in timeout and "lint-staged" in timeout
    assert "Install the tool" not in timeout
    missing = commit_gate.fail_open_notice(["ruff", "check", "."], "FileNotFoundError: 'ruff'")
    assert "Install the tool" in missing and "timed out" not in missing


def test_commit_gate_resolves_python_to_python3(monkeypatch, tmp_path: Path) -> None:
    """The plugin's own repo logged 78 fail-opens on `FileNotFoundError: 'python'` — this host has
    only `python3`, and `choose_gate` writes the validator's interpreter as `python` (ADR 0082)."""
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev" / "validate.py").write_text("", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setattr(
        guardrails.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None
    )
    seen: dict[str, object] = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(commit_gate.subprocess, "run", run)
    commit_gate.gate_decision(
        {"tool_name": "Bash", "tool_input": {"command": "git commit"}, "cwd": str(tmp_path)}
    )
    assert seen["cmd"] == ["python3", "dev/validate.py"]
