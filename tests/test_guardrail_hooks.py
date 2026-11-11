from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
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

from agentic_forge import gate_scope, guardrails, observability  # noqa: E402

HOOKS = _REPO / "plugin" / "hooks" / "scripts"


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


def test_budget_soft_cap_warning_reaches_operator_and_model(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """The soft-cap warning went to stderr with exit 0 — debug-log only — so the first thing anyone
    saw was the hard block. It is JSON on stdout now, for both audiences."""
    monkeypatch.setattr(budget.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("AGENTIC_FORGE_SUBAGENT_SOFT", "0")
    monkeypatch.setenv("AGENTIC_FORGE_SUBAGENT_HARD", "100")
    _stdin(monkeypatch, {"tool_name": "Task", "session_id": "soft", "cwd": str(tmp_path)})
    assert budget.main() == 0  # warns, never blocks
    captured = capsys.readouterr()
    assert captured.err == ""
    out = json.loads(captured.out)
    assert "budget hook warning: 1 subagents" in out["systemMessage"]
    assert out["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse", "additionalContext": out["systemMessage"]
    }


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
        "pre_router.py", "role_scope.py",
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
    # ADR 0106: every tool but the three read tools, MCP tools and future tools included.
    role_matcher = "^(?!(?:Read|Grep|Glob)$).*"
    assert scripts_for("PreToolUse", role_matcher) == {"role_scope.py"}
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


def test_commit_gate_timeout_records_which_test_hung(monkeypatch, tmp_path: Path, capsys) -> None:
    """`TimeoutExpired` carries the partial output as BYTES (POSIX, even in text mode); only
    `str(exc)` was recorded, so nothing said which test hung."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIC_FORGE_SKIP_TEST_GATE", raising=False)
    monkeypatch.setenv("AGENTIC_FORGE_DIAGNOSTICS", "1")

    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd, 110, output=b"x" * 600 + b"\ntests/test_slow.py::test_hangs ", stderr=b"warn"
        )

    monkeypatch.setattr(commit_gate.subprocess, "run", hang)
    payload = {
        "tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
        "cwd": str(tmp_path), "session_id": "s-hang",
    }
    assert commit_gate.gate_decision(payload) == guardrails.ALLOW
    capsys.readouterr()
    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    event = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert "TimeoutExpired" in event["message"]
    assert event["context"]["stdout"].endswith("tests/test_slow.py::test_hangs")
    assert len(event["context"]["stdout"]) == 400  # the last 400 chars, decoded
    assert event["context"]["stderr"] == "warn"


def test_commit_gate_tail_decodes_bytes_and_caps() -> None:
    assert commit_gate._tail(None) == "" and commit_gate._tail("") == ""
    assert commit_gate._tail(b"  caf\xc3\xa9 \n") == "café"
    assert commit_gate._tail("a" * 1000) == "a" * 400


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


# --- a hook crash is recorded WITHOUT the diagnostics toggle, and announced once (A5) ---------


@pytest.mark.parametrize(
    ("module", "entry", "component"),
    [
        (security, "decide", "security-hook"),
        (budget, "decide", "budget-hook"),
        (commit_gate, "gate_decision", "commit-gate"),
        (audit_log, "write_audit", "audit-hook"),
    ],
)
def test_hook_crash_is_recorded_and_announced_once_per_session(
    monkeypatch, tmp_path: Path, capsys, module, entry: str, component: str
) -> None:
    """Every hook fails open on its own error and "records the crash" — gated on
    `diagnostics.enabled`, off by default, so a default install had no record and no message."""
    monkeypatch.delenv("AGENTIC_FORGE_DIAGNOSTICS", raising=False)

    def boom(*_a, **_k):
        raise RuntimeError("guardrail exploded")

    monkeypatch.setattr(module, entry, boom)
    payload = {
        "tool_name": "Bash", "tool_input": {"command": "ls"},
        "cwd": str(tmp_path), "session_id": "s-crash",
    }
    _stdin(monkeypatch, payload)
    assert module.main() == 0  # fail open
    first = json.loads(capsys.readouterr().out)
    name = component[: -len("-hook")] if component.endswith("-hook") else component
    assert f"agentic-forge {name} hook crashed: RuntimeError: guardrail exploded" in (
        first["systemMessage"]
    )
    assert "failing open" in first["systemMessage"]

    _stdin(monkeypatch, payload)
    assert module.main() == 0
    assert capsys.readouterr().out == ""  # said once per session

    log = diagnostics.state_root(tmp_path) / diagnostics.DIAGNOSTICS_FILE
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    crashes = [e for e in events if e["component"] == component]
    assert len(crashes) == 2 and all(e["kind"] == "error" for e in crashes)  # BOTH recorded


# --- commit_gate: narrowed to what a simple command changes (ADR 0101) -------------------------
# A real git monorepo, the real hook as a process, and real ruff behind a wrapper that records each
# run. The root has no manifest, `svc/` has a pyproject and a committed file with an old finding,
# `gosvc/` has a go.mod (with a fake `go`: go is not assumed), `infra/` has no stack.

_BAD = "import os\n"  # F401
_GOOD = "x = 1\n"

_RECORDING_TOOL = """#!{python}
import json, os, sys
with open(os.environ["TOOL_LOG"], "a", encoding="utf-8", errors="surrogateescape") as log:
    log.write(json.dumps({{"tool": os.path.basename(sys.argv[0]), "cwd": os.getcwd(),
                          "argv": sys.argv[1:]}}) + "\\n")
real = {real!r}
if real:
    os.execv(real, [real, *sys.argv[1:]])
sys.exit(int(os.environ.get("FAKE_TOOL_RC", "0")))
"""


def _real_ruff() -> str:
    beside = Path(sys.executable).parent / "ruff"
    found = str(beside) if beside.is_file() else shutil.which("ruff")
    if not found:
        pytest.skip("ruff is not installed")
    return found


class Mono:
    """The fixture repo, a bare `origin`, the real hook, and the record of which tools ran."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.root = base / "repo"
        self.origin = base / "origin.git"
        self.log = base / "tools.jsonl"
        self.bin = base / "bin"
        self.bin.mkdir()
        for name, real in (("ruff", _real_ruff()), ("go", ""), ("npm", "")):
            tool = self.bin / name
            tool.write_text(_RECORDING_TOOL.format(python=sys.executable, real=real))
            tool.chmod(0o755)
        self.env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(base / "home"),
            "AGENTIC_FORGE_STATE_HOME": str(base / "state"),
            "TOOL_LOG": str(self.log),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        (base / "home").mkdir()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        done = subprocess.run(
            ["git", *args], cwd=cwd or self.root, env=self.env, check=True, capture_output=True
        )
        return done.stdout.decode("utf-8", "replace")

    def write(self, rel: str, content: str = _GOOD) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def stage(self, rel: str, content: str = _GOOD) -> None:
        self.write(rel, content)
        self.git("add", "--", rel)

    def commit(self, rel: str, content: str = _GOOD, message: str = "m") -> None:
        self.stage(rel, content)
        self.git("commit", "-qm", message)

    def sh(self, script: str) -> None:
        """A scenario's setup, from the repo root, with `$BASE` beside it."""
        env = {**self.env, "BASE": str(self.base)}
        subprocess.run(["bash", "-ec", script], cwd=self.root, env=env, check=True,
                       capture_output=True)

    def hook(
        self, command: str, cwd: str = "svc", env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        """The real hook, as Claude Code runs it, on a clean record of what ran."""
        self.log.unlink(missing_ok=True)
        payload = {
            "tool_name": "Bash", "tool_input": {"command": command},
            "cwd": str(self.root / cwd), "session_id": "s",
        }
        return subprocess.run(
            [sys.executable, str(HOOKS / "commit_gate.py")],
            input=json.dumps(payload), env={**self.env, **(env or {})},
            capture_output=True, text=True, errors="replace", timeout=120,
        )

    def ran(self) -> list[dict]:
        if not self.log.exists():
            return []
        text = self.log.read_text(encoding="utf-8", errors="surrogateescape")
        return [json.loads(line) for line in text.splitlines()]

    def argvs(self) -> list[list[str]]:
        return [[entry["tool"], *entry["argv"]] for entry in self.ran()]


WHOLE_RUFF = ["ruff", "check", "."]


def _narrowed(*files: str) -> list[str]:
    return ["ruff", "check", *files]


@pytest.fixture
def mono(tmp_path: Path) -> Mono:
    repo = Mono(tmp_path.resolve())
    repo.root.mkdir()
    repo.git("init", "-q", "-b", "main", ".")
    repo.git("init", "-q", "--bare", str(repo.origin))
    repo.git("remote", "add", "origin", str(repo.origin))
    repo.write("README.md", "root\n")
    repo.write("svc/pyproject.toml", "[project]\nname = 'svc'\nversion = '0'\n")
    repo.write("svc/good.py")
    repo.write("svc/legacy_bad.py", _BAD)  # the old finding that blocked everything
    repo.write("gosvc/go.mod", "module x\n")
    repo.write("gosvc/main.go", "package main\n")
    repo.write("infra/main.tf", "# tf\n")
    repo.write("infra/script.py", _BAD)
    repo.write(".gitignore", ".ruff_cache/\n")
    repo.git("add", ".")
    repo.git("commit", "-qm", "init")
    repo.git("push", "-q", "-u", "origin", "main")
    return repo


EMPTY = "git commit --allow-empty -m empty"


@pytest.mark.parametrize(
    ("cwd", "gate"),
    [(".", None), ("svc", WHOLE_RUFF), ("gosvc", ["go", "vet", "./..."]), ("infra", None)],
)
def test_field_table_an_empty_commit_passes_everywhere(mono: Mono, cwd: str, gate) -> None:
    """The field report's table: the same empty commit, from each directory."""
    assert guardrails.choose_gate(mono.root / cwd) == gate  # the choice itself is untouched
    done = mono.hook(EMPTY, cwd)
    assert done.returncode == 0, done.stderr
    assert mono.ran() == []


def test_field_table_holds_in_a_linked_worktree(mono: Mono) -> None:
    linked = mono.base / "linked"
    mono.git("worktree", "add", "-q", "-b", "wt", str(linked))
    payload = {
        "tool_name": "Bash", "tool_input": {"command": EMPTY}, "cwd": str(linked / "svc"),
    }
    done = subprocess.run(
        [sys.executable, str(HOOKS / "commit_gate.py")], input=json.dumps(payload), env=mono.env,
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    assert mono.ran() == []
    (linked / "svc" / "new.py").write_text(_BAD)
    mono.git("add", "svc/new.py", cwd=linked)
    done = subprocess.run(
        [sys.executable, str(HOOKS / "commit_gate.py")],
        input=json.dumps({**payload, "tool_input": {"command": "git commit -m x"}}), env=mono.env,
        capture_output=True, text=True,
    )
    assert done.returncode == 2 and "./new.py" in done.stderr


def test_a_root_commit_stays_ungated(mono: Mono) -> None:
    """The limit we keep: rule 1, nothing runs that master would not."""
    mono.stage("svc/new_bad.py", _BAD)
    assert mono.hook("git commit -m x", ".").returncode == 0
    assert mono.ran() == []


def test_an_unrelated_change_does_not_block(mono: Mono) -> None:
    mono.stage("infra/other.tf", "# x\n")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []  # changed files only outside cwd: ruff is skipped
    mono.stage("infra/other.py", _BAD)  # outside this cwd's gate, whatever it holds
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


def test_a_clean_file_in_the_commit_passes_past_old_findings(mono: Mono) -> None:
    mono.stage("svc/new.py")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.argvs() == [_narrowed("./new.py")]


def test_a_bad_file_in_the_commit_blocks(mono: Mono) -> None:
    mono.stage("svc/new_bad.py", _BAD)
    done = mono.hook("git commit -m x")
    assert done.returncode == 2
    assert "F401" in done.stderr and "new_bad.py" in done.stderr
    assert mono.argvs()[0] == _narrowed("./new_bad.py")
    assert mono.argvs()[1] == WHOLE_RUFF  # the block is confirmed with what master runs


def test_touching_a_file_with_old_findings_blocks_per_file_not_per_line(mono: Mono) -> None:
    mono.stage("svc/legacy_bad.py", _BAD + "y = 2\n")
    assert mono.hook("git commit -m x").returncode == 2


def test_a_bad_file_not_in_the_commit_does_not_block(mono: Mono) -> None:
    mono.stage("svc/new.py")
    mono.write("svc/untracked_bad.py", _BAD)
    mono.write("svc/good.py", _BAD)  # tracked and dirty, but not staged
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.argvs() == [_narrowed("./new.py")]


def test_a_docs_only_commit_skips_ruff(mono: Mono) -> None:
    mono.stage("svc/README.md", "# docs\n")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


def test_a_deletion_is_not_linted(mono: Mono) -> None:
    mono.git("rm", "-q", "svc/legacy_bad.py")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


def test_a_staged_file_gone_from_the_tree_is_not_a_finding(mono: Mono) -> None:
    """`ruff check ./gone.py` is E902, exit 1: a block `ruff check .` would not give."""
    mono.stage("svc/gone.py", _BAD)
    (mono.root / "svc/gone.py").unlink()
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


@pytest.mark.parametrize(
    ("command", "blocks", "files"),
    [
        ("git add good2.py && git commit -m x", False, ["./good2.py"]),
        ("git add -- good2.py && git commit -m x", False, ["./good2.py"]),
        ("git add bad2.py && git commit -m x", True, ["./bad2.py"]),  # not staged yet, still seen
        ("git add -A && git commit -m x", True, ["./bad2.py", "./good2.py"]),
        ("git add --all && git commit -m x", True, ["./bad2.py", "./good2.py"]),
        ("git add . && git commit -m x", True, ["./bad2.py", "./good2.py"]),
    ],
)
def test_git_add_then_commit_reads_what_the_add_covers(
    mono: Mono, command: str, blocks: bool, files: list[str]
) -> None:
    mono.write("svc/good2.py")
    mono.write("svc/bad2.py", _BAD)
    done = mono.hook(command)
    assert done.returncode == (2 if blocks else 0), done.stderr
    assert mono.argvs()[0] == _narrowed(*files)


def test_git_add_of_a_tracked_change_counts(mono: Mono) -> None:
    mono.write("svc/good.py", _BAD)
    assert mono.hook("git add good.py && git commit -m x").returncode == 2
    assert mono.argvs()[0] == _narrowed("./good.py")


def test_git_add_dot_covers_only_this_directory(mono: Mono) -> None:
    mono.write("infra/other.py", _BAD)
    mono.write("svc/notes.md", "x\n")
    assert mono.hook("git add . && git commit -m x").returncode == 0
    assert mono.ran() == []


def test_git_add_of_nothing_real_reads_as_nothing_and_git_refuses_it(mono: Mono) -> None:
    assert mono.hook("git add missing.py && git commit -m x").returncode == 0
    assert mono.ran() == []


@pytest.mark.parametrize("command", ["git commit -am x", "git commit -a -m x", "git commit --all"])
def test_commit_a_reads_tracked_changes_and_not_untracked(mono: Mono, command: str) -> None:
    mono.write("svc/untracked_bad.py", _BAD)
    assert mono.hook(command).returncode == 0
    assert mono.ran() == []  # nothing tracked changed, and -a cannot take the untracked file
    mono.write("svc/good.py", _BAD)
    assert mono.hook(command).returncode == 2
    assert mono.argvs()[0] == _narrowed("./good.py")


def test_a_heredoc_message_is_recognised(mono: Mono) -> None:
    command = "git commit -m \"$(cat <<'EOF'\nfix(x): y; `z` $w\n\nbody\nEOF\n)\""
    assert mono.hook(command).returncode == 0
    assert mono.ran() == []
    assert mono.hook("git add x.py && " + command).returncode == 0


def test_push_with_an_upstream_reads_only_unpushed_files(mono: Mono) -> None:
    assert mono.hook("git push").returncode == 0  # nothing new on `origin`
    assert mono.ran() == []
    mono.commit("svc/new.py")
    assert mono.hook("git push").returncode == 0
    assert mono.argvs() == [_narrowed("./new.py")]
    mono.commit("svc/new_bad.py", _BAD)
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./new.py", "./new_bad.py")
    mono.git("push", "-q")
    assert mono.hook("git push").returncode == 0
    assert mono.ran() == []


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin feature/x",
        "git push --set-upstream origin feature/x",
        "git push origin feature/x",
        "git push -u origin HEAD",
    ],
)
def test_push_of_a_new_branch_reads_what_the_remote_lacks(mono: Mono, command: str) -> None:
    mono.git("switch", "-q", "-c", "feature/x")
    assert mono.hook(command).returncode == 0
    assert mono.ran() == []  # it holds only what `origin` has
    mono.commit("svc/f_bad.py", _BAD)
    assert mono.hook(command).returncode == 2
    assert mono.argvs()[0] == _narrowed("./f_bad.py")


def test_push_of_a_branch_other_than_head_runs_whole(mono: Mono) -> None:
    mono.git("switch", "-q", "-c", "other")
    mono.commit("svc/other.py")
    mono.git("switch", "-q", "main")
    assert mono.hook("git push origin other").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]
    assert mono.hook("git push origin main").returncode == 0


def test_push_after_a_merge_from_main_reads_what_main_brought(mono: Mono) -> None:
    """Those commits are news to `origin/feature`, which is what the push compares with: reading
    every remote ref instead would also hide a branch fast-forwarded onto main. So main's own bad
    file blocks here: a stated limit, and master blocked this push as well."""
    mono.git("switch", "-q", "-c", "feature")
    mono.commit("svc/f.py")
    mono.git("push", "-q", "-u", "origin", "feature")
    mono.git("switch", "-q", "main")
    mono.commit("svc/from_main_bad.py", _BAD)
    mono.git("push", "-q")
    mono.git("switch", "-q", "feature")
    mono.git("merge", "-q", "--no-edit", "main")
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./from_main_bad.py")


def test_push_after_a_merge_of_clean_main_ignores_old_findings_elsewhere(mono: Mono) -> None:
    mono.git("switch", "-q", "-c", "feature")
    mono.commit("svc/f.py")
    mono.git("push", "-q", "-u", "origin", "feature")
    mono.git("switch", "-q", "main")
    mono.commit("svc/from_main.py")
    mono.git("push", "-q")
    mono.git("switch", "-q", "feature")
    mono.git("merge", "-q", "--no-edit", "main")
    assert mono.hook("git push").returncode == 0
    assert mono.argvs() == [_narrowed("./from_main.py")]


def test_push_fast_forwarding_onto_a_branch_with_a_tracking_ref_is_news(mono: Mono) -> None:
    """A commit on `origin/wip` lands on `main` by this push, and `--remotes=origin` hid it."""
    mono.git("switch", "-q", "-c", "wip")
    mono.commit("svc/wip_bad.py", _BAD)
    mono.git("push", "-q", "-u", "origin", "wip")
    mono.git("switch", "-q", "main")
    mono.git("merge", "-q", "--ff-only", "wip")
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./wip_bad.py")


def test_landing_on_a_branch_with_no_tracking_ref_is_not_gated(mono: Mono) -> None:
    """The stated limit: no ref says what that branch lacks, so `--remotes=` is all there is."""
    mono.git("switch", "-q", "-c", "wip")
    mono.commit("svc/wip_bad.py", _BAD)
    mono.git("push", "-q", "-u", "origin", "wip")
    mono.git("switch", "-q", "-c", "release")
    assert mono.hook("git push -u origin release").returncode == 0
    assert mono.ran() == []


def test_a_slash_named_remote_is_not_misread(mono: Mono) -> None:
    """`refs/remotes/team/fork/main` is `team/fork`, not `team`, whose siblings are not sent."""
    other = mono.base / "team.git"
    mono.git("init", "-q", "--bare", str(other))
    mono.git("remote", "add", "team/fork", str(other))
    mono.git("push", "-q", "-u", "team/fork", "main")
    mono.commit("svc/new_bad.py", _BAD)
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./new_bad.py")
    mono.git("push", "-q")
    assert mono.hook("git push").returncode == 0
    assert mono.ran() == []


def test_an_upstream_of_another_name_or_an_unknown_remote_runs_whole(mono: Mono) -> None:
    assert mono.hook(f"git push {mono.origin.name} main").returncode == 2  # a path, not a remote
    assert mono.argvs() == [WHOLE_RUFF]
    mono.git("switch", "-q", "-c", "topic", "--track", "origin/main")
    mono.git("config", "push.default", "upstream")
    assert mono.hook("git push").returncode == 2  # `@{push}` is origin/main, and this is `topic`
    assert mono.argvs() == [WHOLE_RUFF]


def test_a_remote_git_does_not_confirm_is_not_read(mono: Mono) -> None:
    """A full-history read of it usually runs whole anyway, because history holds a ruff config, so
    only the read itself can show this."""
    cwd, deadline = str(mono.root), time.monotonic() + 5
    unknown = gate_scope.Simple("push", remote="nowhere", branch="main")
    with pytest.raises(gate_scope._GitFailed):
        gate_scope._pushed(unknown, cwd, deadline)
    other = mono.base / "plus.git"
    mono.git("init", "-q", "--bare", str(other))
    mono.git("remote", "add", "a+b", str(other))  # real, and not safe inside a config pattern
    mono.git("push", "-q", "-u", "a+b", "main")
    with pytest.raises(gate_scope._GitFailed):
        gate_scope._pushed(gate_scope.Simple("push"), cwd, deadline)


def test_push_lists_a_rename_on_both_sides(mono: Mono) -> None:
    mono.git("mv", "gosvc/main.go", "infra/main.go")
    mono.git("commit", "-qm", "move")
    assert mono.hook("git push", "gosvc").returncode == 0
    assert mono.argvs() == [["go", "vet", "./..."]]


def test_a_root_commit_counts_whatever_log_showroot_says(mono: Mono) -> None:
    fresh = mono.root / "svc" / "fresh"
    fresh.mkdir()
    mono.git("init", "-q", "-b", "main", ".", cwd=fresh)
    other = mono.base / "fresh.git"
    mono.git("init", "-q", "--bare", str(other))
    mono.git("remote", "add", "origin", str(other), cwd=fresh)
    mono.git("config", "log.showRoot", "false", cwd=fresh)
    (fresh / "pyproject.toml").write_text("[project]\nname='f'\nversion='0'\n")
    (fresh / "bad.py").write_text(_BAD)
    mono.git("add", ".", cwd=fresh)
    mono.git("commit", "-qm", "root", cwd=fresh)
    assert mono.hook("git push -u origin main", "svc/fresh").returncode == 2


def test_a_replace_ref_does_not_hide_a_commit(mono: Mono) -> None:
    mono.commit("svc/new_bad.py", _BAD)
    mono.git("replace", "HEAD", "HEAD~1")
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./new_bad.py")


def test_a_dirty_submodule_is_not_entered(mono: Mono) -> None:
    """Its own config is not this repo's, and asking whether it is dirty ran its fsmonitor."""
    lib = mono.base / "lib"
    lib.mkdir()
    mono.git("init", "-q", "-b", "main", ".", cwd=lib)
    (lib / "f.txt").write_text("x\n")
    mono.git("add", ".", cwd=lib)
    mono.git("commit", "-qm", "lib", cwd=lib)
    mono.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "svc/lib")
    mono.git("commit", "-qm", "sub")
    marker = mono.base / "ran"
    script = mono.base / "sub-filter.sh"
    script.write_text(f'#!/bin/sh\ntouch "{marker}"\ncat\n')
    script.chmod(0o755)
    sub = mono.root / "svc" / "lib"
    (sub / ".gitattributes").write_text("*.txt filter=mark\n")
    mono.git("config", "filter.mark.clean", str(script), cwd=sub)
    (sub / "f.txt").write_text("y\n")
    assert mono.hook("git commit -am x").returncode == 0
    assert not marker.exists()
    assert mono.ran() == []  # a dirty submodule is not something `-a` commits


def test_push_of_a_merge_includes_the_merges_own_changes(mono: Mono) -> None:
    """A conflict resolution lives only in the merge commit: plain `git log` lists none of it."""
    mono.git("switch", "-q", "-c", "feature")
    mono.commit("svc/both.py", "a = 1\n")
    mono.git("push", "-q", "-u", "origin", "feature")
    mono.git("switch", "-q", "main")
    mono.commit("svc/both.py", "a = 2\n")
    mono.git("push", "-q")
    mono.git("switch", "-q", "feature")
    with pytest.raises(subprocess.CalledProcessError):
        mono.git("merge", "-q", "--no-edit", "main")
    mono.stage("svc/both.py", _BAD)
    mono.git("commit", "-qm", "merge")
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./both.py")


def test_push_of_a_merge_of_unpushed_main_reads_main_too(mono: Mono) -> None:
    mono.git("switch", "-q", "-c", "feature")
    mono.commit("svc/f.py")
    mono.git("push", "-q", "-u", "origin", "feature")
    mono.git("switch", "-q", "main")
    mono.commit("svc/local_main_bad.py", _BAD)
    mono.git("switch", "-q", "feature")
    mono.commit("svc/f2.py")
    mono.git("merge", "-q", "--no-edit", "main")
    assert mono.hook("git push").returncode == 2
    assert mono.argvs()[0] == _narrowed("./f2.py", "./local_main_bad.py")


def test_push_compares_with_the_remote_it_goes_to(mono: Mono) -> None:
    """Commits on `origin` are still news to `fork`. No tracking ref there: all history counts."""
    fork = mono.base / "fork.git"
    mono.git("init", "-q", "--bare", str(fork))
    mono.git("remote", "add", "fork", str(fork))
    assert mono.hook("git push origin main").returncode == 0
    assert mono.ran() == []
    assert mono.hook("git push fork main").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]  # all of history, and that holds a ruff config
    mono.git("config", "remote.pushDefault", "fork")
    assert mono.hook("git push").returncode == 2


@pytest.mark.parametrize(
    ("key", "value"),
    [("push.default", "matching"), ("remote.origin.push", "refs/heads/*:refs/heads/*"),
     ("remote.origin.mirror", "true"), ("push.default", "nothing"), ("push.default", "upstream"),
     ("push.default", "tracking")],
)
def test_a_push_whose_config_can_send_more_than_head_runs_whole(
    mono: Mono, key: str, value: str
) -> None:
    mono.git("config", key, value)
    assert mono.hook("git push").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]
    assert mono.hook("git push origin").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]
    assert mono.hook("git push origin main").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


def test_push_default_current_still_narrows(mono: Mono) -> None:
    mono.git("config", "push.default", "current")
    mono.commit("svc/new.py")
    assert mono.hook("git push").returncode == 0
    assert mono.argvs() == [_narrowed("./new.py")]


def test_push_on_a_detached_head_or_with_no_upstream_runs_whole(mono: Mono) -> None:
    mono.git("switch", "-q", "-c", "no-upstream")
    assert mono.hook("git push").returncode == 2  # git names no remote for it
    assert mono.argvs() == [WHOLE_RUFF]
    mono.git("switch", "-q", "--detach")
    assert mono.hook("git push").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


# Every shape here must behave exactly as master: read as uncertain, the old finding blocks even
# though nothing is staged, where a narrowed read of the same state would have skipped the gate.
UNCERTAIN = [
    "git commit \\\n  -m x",
    "git commit -m x # note",
    "git commit -m x #note",
    'git commit -m "$(date)"',
    "git commit -m `date`",
    'git commit -m "`date`"',
    'git commit -m "$X"',
    'git commit -m "a\\"b"',
    'git commit -m "line one\nline two"',
    "git commit -m x; echo done",
    "git commit -m x | cat",
    "git commit -m x > out.txt",
    "git commit -m x < in.txt",
    "git commit -m x & wait",
    "git commit -m x || true",
    "git commit -m x\n",
    "git commit -m x && git push",
    "git -C . commit -m x",
    "git -c a.b=c commit -m x",
    "git --git-dir=.git commit -m x",
    "git commit --git-dir=.git -m x",
    "cd . && git commit -m x",
    "( cd . && git commit -m x )",
    "(true); git commit -m x",
    "GIT_DIR=.git git commit -m x",
    "git commit --amend -m x",
    "git commit --amend --no-edit",
    "git commit good.py -m x",
    "git commit -- good.py",
    "git commit -F msg.txt",
    "git commit --mess x",
    "git commit -m",
    "git commit --message=x",
    "git commit -qqm x",
    "git commit =python -m x",
    "git add ''=x && git commit -m y",
    'git add ""=x && git commit -m y',
    "git commit -m '=quoted'",
    "git push -q",
    "git push --quiet origin main",
    "git add =python && git commit -m x",
    "git commit -F -",
    "git commit -F - <<EOF\nbody\nEOF\n",
    "git commit -F - <<'EOF'\nbody\nEOF\nrm x\n",
    "git commit -F - <<'EOF'\nbody\nEOF\nmore\nEOF",
    "git commit -F - <<'EOF' && git push\nbody\nEOF\n",
    "git add 'a b' && git commit -F - <<'EOF'\nbody\nEOF",
    "git add x.py && git add y.py && git commit -m x",
    "git add *.py && git commit -m x",
    "git add '*.py' && git commit -m x",
    "git add ':/x' && git commit -m x",
    "git add -f x.py && git commit -m x",
    "git add -u && git commit -m x",
    "git add -A x.py && git commit -m x",
    "git add && git commit -m x",
    "git add '' && git commit -m x",
    "git add --all . && git commit -m x",
    "git add ~/x && git commit -m x",
    "git add x.py && git status && git commit -m x",
    "git status && git commit -m x",
    "git add x.py&&git commit -m x",
    "git push --all",
    "git push --tags",
    "git push --mirror",
    "git push --follow-tags",
    "git push --force origin main",
    "git push -d origin x",
    "git push origin a b",
    "git push origin a:b",
    "git push origin +main",
    "git push origin a..b",
    "git push https://example.invalid/x.git main",
    "git add x.py && git push",
    # A heredoc that is not the one strict shape:
    'git commit -m "$(cat <<EOF\nbody $(date)\nEOF\n)"',
    "git commit -m \"$(cat <<-'EOF'\nbody\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nbody\nEOF\nrm -rf x\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nbody\nEOF\n)\" --no-verify; rm x",
    "git add 'a b' && git commit -m \"$(cat <<'EOF'\nbody\nEOF\n)\"",
    "git commit -m 'x -m \"$(cat <<'E'\nbody\nE\n)\"'",
    "git commit -F- <<'EOF'\nbody\nEOF\n",
]
# Not a trigger on master either, so nothing runs: subshells among them.
NOT_TRIGGERS = [
    "(git commit -m x)",
    "echo git commit -m x",
    "git status",
]


@pytest.mark.parametrize("command", UNCERTAIN)
def test_an_uncertain_shape_behaves_exactly_as_master(mono: Mono, command: str) -> None:
    assert guardrails.is_commit_or_push(command), "not a trigger: this test would prove nothing"
    assert gate_scope.parse_simple(command) is None
    done = mono.hook(command)
    assert done.returncode == 2, done.stderr
    assert mono.argvs() == [WHOLE_RUFF]
    assert "legacy_bad.py" in done.stderr


@pytest.mark.parametrize("command", NOT_TRIGGERS)
def test_a_subshell_is_not_a_trigger_as_on_master(mono: Mono, command: str) -> None:
    assert not guardrails.is_commit_or_push(command)
    assert mono.hook(command).returncode == 0
    assert mono.ran() == []


SIMPLE = [
    "git commit",
    "git commit -m x",
    "  git commit   -m x  ",
    "git commit -m 'fix(a): b; c | d > e #1'",
    'git commit -m "fix(a): b; c | d > e #1"',
    "git commit -m x -m y --no-verify -s -q",
    "git commit --message x -n --signoff --quiet --allow-empty",
    "git commit -am x",
    "git commit --all -m x",
    "git add x.py && git commit -m x",
    "git add 'a b.py' c.py && git commit -m x",
    "git add -- -x.py && git commit -m x",
    "git add -A && git commit -am x",
    "git add @x.py && git commit -m '&&'",
    "git add . && git commit -m \"$(cat <<'EOF'\nbody\nEOF\n)\"",
    "git commit -am \"$(cat <<'MSG'\nEOF\nbody\nMSG\n)\"",
    "git commit -qm x",
    "git commit -F - <<'EOF'\nbody\nEOF",
    "git commit -q -a -F - <<'EOF'\nbody\nEOF\n",
    "git add x.py && git commit -F - <<'EOF'\nfix(x): `y` $z\nEOF\n",
    "git commit -m a=b",
    "git push",
    "git push origin",
    "git push -u origin main",
    "git push -u origin feature/x.y",
    "git push origin HEAD",
]


def test_the_matcher_reads_what_a_simple_command_says() -> None:
    parse = gate_scope.parse_simple
    assert parse("git commit -m x") == gate_scope.Simple("commit")
    assert parse("git commit -am x") == gate_scope.Simple("commit", tracked=True)
    assert parse("git add a 'b c' && git commit") == gate_scope.Simple("commit", add=("a", "b c"))
    assert parse("git add -A && git commit") == gate_scope.Simple("commit", add=(":/",))
    assert parse("git add -- -x && git commit") == gate_scope.Simple("commit", add=("-x",))
    assert parse("git add -x && git commit") is None
    assert parse("git commit -a -F - <<'E'\nb\nE") == gate_scope.Simple("commit", tracked=True)
    assert parse("git push") == gate_scope.Simple("push")
    assert parse("git push -u o b/c") == gate_scope.Simple("push", remote="o", branch="b/c")
    for command in SIMPLE:
        assert parse(command) is not None, command


def test_the_matcher_is_not_quadratic_on_a_hostile_command() -> None:
    started = time.monotonic()
    assert gate_scope.parse_simple("git commit -m " + "a" * 500_000 + "!") is None
    assert gate_scope.parse_simple("git commit -m " + "a '" * 100_000) is None
    assert time.monotonic() - started < 5


def _clean_svc(mono: Mono, ruff_config: str = "") -> None:
    (mono.root / "svc/legacy_bad.py").unlink()
    mono.write("svc/pyproject.toml", f"[project]\nname='s'\nversion='0'\n{ruff_config}")
    mono.git("add", "-A", "svc")
    mono.git("commit", "-qm", "clean")


def test_ruff_exclude_is_honoured_by_the_whole_gate_deciding(mono: Mono) -> None:
    _clean_svc(mono, "[tool.ruff]\nexclude = ['generated_*.py']\n")
    mono.stage("svc/generated_x.py", _BAD)
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.argvs() == [_narrowed("./generated_x.py"), WHOLE_RUFF]


@pytest.mark.parametrize(
    "name", ["dist", "venv", ".venv", "_build", "node_modules", "site-packages"]
)
def test_a_directory_named_like_a_default_exclude_is_still_linted(mono: Mono, name: str) -> None:
    """`--force-exclude` tests the cwd's own name too, so this linted nothing and said nothing."""
    mono.write(f"{name}/pyproject.toml", "[project]\nname='s'\nversion='0'\n")
    mono.git("add", "-f", name)
    mono.git("commit", "-qm", "package")
    mono.write(f"{name}/new_bad.py", _BAD)
    mono.git("add", "-f", name)
    assert mono.hook("git commit -m x", name).returncode == 2
    assert mono.argvs() == [_narrowed("./new_bad.py"), WHOLE_RUFF]


def test_a_gitignored_file_the_whole_gate_would_not_lint_never_blocks(mono: Mono) -> None:
    """An explicit path bypasses `.gitignore`, so a narrowed failure alone would be a new block."""
    _clean_svc(mono)
    mono.write("svc/.gitignore", "ignored.py\n")
    mono.git("add", "svc/.gitignore")
    mono.git("commit", "-qm", "ignore")
    mono.write("svc/ignored.py", _BAD)
    mono.git("add", "-f", "svc/ignored.py")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.argvs() == [_narrowed("./ignored.py"), WHOLE_RUFF]


@pytest.mark.parametrize("name", ["pyproject.toml", "ruff.toml", ".ruff.toml"])
def test_a_changed_ruff_config_runs_whole(mono: Mono, name: str) -> None:
    """A broken one lints no file it does not read. Passing on the files alone would let it in, and
    it would then fail every later commit."""
    _clean_svc(mono)
    mono.stage(f"svc/{name}", "[tool.ruff\n")
    done = mono.hook("git commit -m x")
    assert done.returncode == 2, done.stderr
    assert mono.argvs() == [WHOLE_RUFF]


@pytest.mark.parametrize(
    "line",
    ['include = ["*.py", "*.pyw"]', 'extend-include = ["*.pxi"]', 'extension = {pxi = "python"}',
     'extend = "../base.toml"'],
)
@pytest.mark.parametrize("where", ["pyproject", "ruff", "parent"])
def test_a_config_choosing_its_own_inputs_runs_whole(mono: Mono, line: str, where: str) -> None:
    _clean_svc(mono)
    if where == "pyproject":
        mono.write("svc/pyproject.toml", f"[project]\nname='s'\nversion='0'\n[tool.ruff]\n{line}\n")
    elif where == "ruff":
        mono.write("svc/ruff.toml", f"{line}\n")
    else:  # svc's pyproject has no [tool.ruff], so ruff goes on up, and so must this
        mono.write("ruff.toml", f"{line}\n")
    mono.git("add", "-A")
    mono.git("commit", "-qm", "config")
    mono.stage("svc/script.pyw", _GOOD)
    mono.hook("git commit -m x")
    assert mono.argvs() == [WHOLE_RUFF]
    mono.git("reset", "-q")
    mono.stage("infra/other.txt", "x\n")  # only outside cwd: nothing here can change, as ever
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


def test_a_config_that_only_tunes_rules_still_narrows(mono: Mono) -> None:
    mono.write("svc/pyproject.toml", "[project]\nname='s'\nversion='0'\n[tool.ruff.lint]\n"
               "extend-select = ['F']\n")
    mono.git("add", "-A")
    mono.git("commit", "-qm", "config")
    mono.stage("svc/new.py")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.argvs() == [_narrowed("./new.py")]


def test_an_unreadable_config_runs_whole(mono: Mono) -> None:
    mono.stage("svc/new.py")
    config = mono.root / "svc" / "ruff.toml"
    config.write_text("")
    config.chmod(0)
    try:
        assert gate_scope.narrow(WHOLE_RUFF, "git commit -m x", str(config.parent)) == WHOLE_RUFF
    finally:
        config.chmod(0o644)


def test_a_real_block_survives_the_confirmation_with_its_own_findings(mono: Mono) -> None:
    mono.stage("svc/new_bad.py", _BAD)
    done = mono.hook("git commit -m x")
    assert "new_bad.py" in done.stderr
    assert "legacy_bad.py" not in done.stderr  # the message is about the change, not the old debt


NAMES = [b"a b.py", b"-dash.py", b"@x.py", b"caf\xe9.py", b"caf\xc3\xa9.py", b"new\nline.py",
         b"esc\x1b[31m.py", b"--force-exclude.py"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(("content", "code"), [(_BAD, 2), (_GOOD, 0)])
def test_any_filename_reaches_ruff_as_one_path(
    mono: Mono, name: bytes, content: str, code: int
) -> None:
    if name == b"caf\xe9.py":  # ruff exits 2 on this name, whatever it holds, and so did master
        code = 2
    with open(os.fsencode(mono.root / "svc") + b"/" + name, "wb") as handle:
        handle.write(content.encode())
    mono.git("add", "--", os.fsdecode(b"svc/" + name))
    done = mono.hook("git commit -m x")
    assert done.returncode == code, done.stderr
    assert mono.ran()[0]["argv"][-1] == os.fsdecode(b"./" + name)
    assert "\x1b" not in done.stderr


def test_literal_awkward_names_in_git_add(mono: Mono) -> None:
    mono.write("svc/a b.py", _BAD)
    assert mono.hook("git add 'a b.py' && git commit -m x").returncode == 2
    assert mono.argvs()[0] == _narrowed("./a b.py")
    mono.write("svc/-dash.py", _BAD)
    assert mono.hook("git add -- -dash.py && git commit -m x").returncode == 2
    assert mono.argvs()[0] == _narrowed("./-dash.py")
    mono.write("svc/@x.py", _BAD)
    assert mono.hook('git add "@x.py" && git commit -m x').returncode == 2
    assert mono.argvs()[0] == _narrowed("./@x.py")


def test_the_block_message_escapes_says_what_ran_and_gives_the_step_that_works(mono: Mono) -> None:
    with open(os.fsencode(mono.root / "svc") + b"/esc\x07\xff.py", "wb") as handle:
        handle.write(_BAD.encode())
    mono.git("add", "--", os.fsdecode(b"svc/esc\x07\xff.py"))
    done = mono.hook("git commit -m x")
    assert done.returncode == 2
    assert "ruff check " in done.stderr and "changed files only" in done.stderr
    assert str(mono.root / "svc") in done.stderr
    assert "\\x07" in done.stderr and "\x07" not in done.stderr
    # The model is told to fix it or ask, and not how to turn the guardrail off.
    assert "Fix the findings, or ask the user." in done.stderr
    assert "test_gate" not in done.stderr and "config.json" not in done.stderr
    operator = json.loads(done.stdout)["systemMessage"]
    assert f"{mono.root / 'svc'}/.agentic-forge/config.json" in operator
    assert "test_gate.skip" in operator and "separate call" in operator
    # The step it gives, taken literally, works.
    mono.write("svc/.agentic-forge/config.json", '{"test_gate": {"skip": true}}\n')
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


def test_a_long_commit_does_not_print_a_thousand_files() -> None:
    gate = ["ruff", "check", *[f"./{i}.py" for i in range(1000)]]
    message = commit_gate.block_message(gate, "/x", scoped=True, tail="t")
    assert "./5.py" in message and "./999.py" not in message and "..." in message


def test_the_whole_gate_message_says_it_ran_whole(mono: Mono) -> None:
    done = mono.hook('git commit -m "$(date)"')
    assert "(`ruff check .`) run whole" in done.stderr


def test_a_broken_config_blocks_as_on_master_whatever_the_narrowed_run_said(mono: Mono) -> None:
    mono.write("svc/pyproject.toml", "[tool.ruff\n")  # dirty, and not in the commit
    mono.stage("svc/new.py")
    done = mono.hook("git commit -m x")
    assert done.returncode == 2, done.stderr
    assert mono.argvs() == [_narrowed("./new.py"), WHOLE_RUFF]
    assert "pyproject.toml" in done.stderr
    assert mono.hook('git commit -m "$(date)"').returncode == 2


def test_a_finding_quoting_an_unrunnable_signature_fails_open_as_on_master(mono: Mono) -> None:
    """Master's classification decides. Its text match reads this as a tool that could not run, and
    the narrowed run must not block where master allowed."""
    source = "try:\n    import os\nexcept ModuleNotFoundError:\n    pass\n"
    mono.write("svc/legacy_bad.py", "x = 1\n")
    mono.git("commit", "-qam", "clean")
    mono.stage("svc/new_bad.py", source)
    assert guardrails.gate_unrunnable(source)
    done = mono.hook("git commit -m x")
    assert done.returncode == 0, done.stderr
    assert "could not run" in json.loads(done.stdout)["systemMessage"]
    assert mono.argvs() == [_narrowed("./new_bad.py"), WHOLE_RUFF]


def test_a_tool_that_cannot_run_narrowed_fails_open_through_master(mono: Mono) -> None:
    (mono.bin / "ruff").write_text("#!/bin/sh\nexit 127\n")
    mono.stage("svc/new.py")
    done = mono.hook("git commit -m x")
    assert done.returncode == 0, done.stderr
    assert "could not run" in json.loads(done.stdout)["systemMessage"]


@pytest.mark.parametrize(
    ("command", "cwd", "stage", "hinted"),
    [
        ("git commit -m x && git push", "svc", "", True),
        ('git commit -m "$(date)"', "svc", "", True),
        ("git add -A && git commit -m x && git push", "gosvc", "gosvc/x.go", True),
        ("git commit -m x", "svc", "svc/new_bad.py", False),  # it was narrowed
    ],
)
def test_a_block_on_a_fallback_shape_says_how_to_get_the_narrowing(
    mono: Mono, command: str, cwd: str, stage: str, hinted: bool
) -> None:
    if stage:
        mono.stage(stage, _BAD)
    done = mono.hook(command, cwd, env={"FAKE_TOOL_RC": "1"})
    assert done.returncode == 2
    assert ("as its own call gates only what changed" in done.stderr) is hinted


def test_no_narrowing_hint_where_a_separate_call_would_not_narrow(mono: Mono) -> None:
    _fake_git(mono, "exit 128")  # the shape was fine: git failed
    assert "as its own call" not in mono.hook("git commit -m x").stderr
    (mono.bin / "git").unlink()
    mono.write("dev/validate.py", "import sys\nsys.exit(1)\n")  # not a gate narrowing can touch
    done = mono.hook("git commit -m x && git push", ".")
    assert done.returncode == 2 and "as its own call" not in done.stderr


def test_a_block_redacts_what_the_linter_quoted(mono: Mono) -> None:
    mono.stage("svc/new_bad.py", 'password = "hunter2hunter2"\nimport os\n')
    done = mono.hook("git commit -m x")
    assert done.returncode == 2
    assert "hunter2" not in done.stderr


def test_a_gates_argv_and_detail_stay_on_one_line() -> None:
    gate = ["ruff", "check", "./a\nb\tc.py"]
    first = commit_gate.block_message(gate, "/x", scoped=True, tail="t").splitlines()[0]
    assert "./a\\nb\\tc.py" in first
    notice = commit_gate.fail_open_notice(gate, "boom\x1b[31m")
    assert "./a\\nb\\tc.py" in notice and "\x1b" not in notice and "\\x1b" in notice


def _fake_git(mono: Mono, body: str) -> None:
    tool = mono.bin / "git"
    tool.write_text(f"#!/bin/sh\n{body}\n")
    tool.chmod(0o755)


@pytest.mark.parametrize("body", ["exit 128", "exit 1", "echo garbage; exit 129"])
def test_a_git_failure_falls_back_to_the_whole_gate(mono: Mono, body: str) -> None:
    mono.stage("svc/new.py")
    _fake_git(mono, body)
    assert mono.hook("git commit -m x").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


def test_a_directory_outside_any_repo_runs_the_whole_gate(mono: Mono) -> None:
    (mono.root / ".git").rename(mono.root / "not-git")
    assert mono.hook("git commit -m x").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


def test_a_repo_shaped_directory_is_not_read(mono: Mono) -> None:
    """Git would read a bare repo here, and its `core.fsmonitor` is a program. Not even a read."""
    marker = mono.base / "ran"
    for sub in ("objects", "refs"):
        (mono.root / "svc" / sub).mkdir()
    (mono.root / "svc" / "HEAD").write_text("ref: refs/heads/main\n")
    script = mono.base / "fsmonitor.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    (mono.root / "svc" / "config").write_text(
        f"[core]\n\tbare = false\n\tworktree = .\n\tfsmonitor = {script}\n"
    )
    assert mono.hook("git commit -am x").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]
    assert not marker.exists()


def test_the_reads_refuse_a_directory_merely_shaped_like_a_repo(mono: Mono) -> None:
    """Asked from inside it, git takes this for a bare repo, whose config chooses filters."""
    shaped = mono.root / "svc" / "fixture"
    for sub in ("objects", "refs"):
        (shaped / sub).mkdir(parents=True)
    (shaped / "HEAD").write_text("ref: refs/heads/main\n")
    (shaped / "config").write_text("[core]\n\tbare = true\n")
    assert mono.git("rev-parse", "--git-dir", cwd=shaped).strip() == "."  # plain git does
    with pytest.raises(gate_scope._GitFailed):
        gate_scope._git(str(shaped), time.monotonic() + 5, "rev-parse", "--git-dir")


def test_a_diff_relative_config_does_not_hide_a_change(mono: Mono) -> None:
    """With it, `git diff` from `svc/` prints paths without the prefix and drops all outside."""
    mono.git("config", "diff.relative", "true")
    mono.stage("svc/new_bad.py", _BAD)
    assert mono.hook("git commit -m x").returncode == 2
    assert mono.argvs()[0] == _narrowed("./new_bad.py")


@pytest.mark.parametrize(
    "name",
    ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"],
)
def test_a_git_environment_that_points_elsewhere_runs_the_whole_gate(mono: Mono, name: str) -> None:
    value = "0" if name == "GIT_CONFIG_COUNT" else str(mono.root / ".git")
    if name == "GIT_CONFIG_PARAMETERS":
        value = "'push.default=matching'"
    done = mono.hook(EMPTY, env={name: value})
    assert done.returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


def test_the_git_reads_share_one_short_deadline(mono: Mono, monkeypatch) -> None:
    (mono.base / "slow").mkdir()
    tool = mono.base / "slow" / "git"
    tool.write_text("#!/bin/sh\nexec sleep 30\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tool.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(gate_scope, "_READ_BUDGET", 0.2)
    started = time.monotonic()
    assert gate_scope.narrow(WHOLE_RUFF, "git commit -m x", str(mono.root / "svc")) == WHOLE_RUFF
    assert time.monotonic() - started < 10
    monkeypatch.setattr(gate_scope, "_READ_BUDGET", 0.0)
    assert gate_scope.narrow(WHOLE_RUFF, "git commit -m x", str(mono.root / "svc")) == WHOLE_RUFF


def test_the_git_reads_get_no_secrets_and_no_steering(mono: Mono) -> None:
    seen = mono.base / "env.txt"
    _fake_git(mono, f'env >> "{seen}"; exit 128')
    assert mono.hook("git commit -m x", env={"MY_API_TOKEN": "hunter2"}).returncode == 2
    assert "hunter2" not in seen.read_text() and "GIT_NO_LAZY_FETCH=1" in seen.read_text()
    assert "TOOL_LOG" not in seen.read_text()  # an allowlist, not a list of what looks secret
    assert "HOME=" in seen.read_text()


def test_the_git_reads_leave_the_repo_as_they_found_it(mono: Mono) -> None:
    mono.stage("svc/new.py")
    mono.write("svc/good.py", "x = 2\n")
    # Stat-dirty with no content change: what makes a plain `git diff` rewrite the index.
    os.utime(mono.root / "README.md", (1, 1))
    mono.git("status", "--porcelain")
    os.utime(mono.root / "README.md", (2, 2))
    index = mono.root / ".git" / "index"
    index_mtime = index.stat().st_mtime_ns
    time.sleep(0.01)
    assert mono.hook("git add good.py && git commit -am x").returncode == 0
    assert index.stat().st_mtime_ns == index_mtime
    assert not (mono.root / ".git" / "index.lock").exists()


def test_a_repos_fsmonitor_does_not_run_in_the_reads(mono: Mono) -> None:
    marker = mono.base / "ran"
    script = mono.base / "fsmonitor.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    mono.git("config", "core.fsmonitor", str(script))
    mono.write("svc/notes.md", "x\n")
    assert mono.hook("git add notes.md && git commit -am x").returncode == 0
    assert not marker.exists()


def test_an_ignored_file_is_not_read_as_covered_by_git_add(mono: Mono) -> None:
    mono.write("svc/.gitignore", "ignored_bad.py\n")
    mono.git("add", "svc/.gitignore")
    mono.git("commit", "-qm", "ignore")
    mono.write("svc/ignored_bad.py", _BAD)
    assert mono.hook("git add -A && git commit --allow-empty -m x").returncode == 0
    assert mono.ran() == []


def test_a_rename_out_of_a_go_package_still_counts_for_it(mono: Mono) -> None:
    """With rename detection `--name-only` lists only the new path, and the package changed."""
    mono.write("gosvc/a.go", "package main\n\nfunc A() {}\n")
    mono.git("add", ".")
    mono.git("commit", "-qm", "a")
    mono.git("mv", "gosvc/a.go", "infra/a.go")
    assert mono.hook("git commit -m x", "gosvc").returncode == 0
    assert mono.argvs() == [["go", "vet", "./..."]]


def test_too_many_files_for_an_argv_run_whole(mono: Mono, monkeypatch) -> None:
    mono.stage("svc/new.py")
    monkeypatch.setattr(gate_scope, "_MAX_ARGV", 3)
    assert gate_scope.narrow(WHOLE_RUFF, "git commit -m x", str(mono.root / "svc")) == WHOLE_RUFF


@pytest.mark.parametrize(
    ("rel", "content", "rc", "ran"),
    [
        ("gosvc/x.go", "package main\n", 0, True),
        ("gosvc/pkg/y.go", "package pkg\n", 0, True),
        ("gosvc/go.mod", "module y\n", 0, True),
        ("gosvc/go.sum", "x\n", 0, True),
        ("gosvc/README.md", "x\n", 0, True),  # go has too many build inputs to list
        ("gosvc/embedded.h", "x\n", 0, True),
        ("infra/z.go", "package z\n", 0, False),  # outside this cwd
    ],
)
def test_go_vet_is_skipped_or_unchanged(
    mono: Mono, rel: str, content: str, rc: int, ran: bool
) -> None:
    mono.stage(rel, content)
    assert mono.hook("git commit -m x", "gosvc").returncode == rc
    assert mono.argvs() == ([["go", "vet", "./..."]] if ran else [])


def test_go_vet_blocks_like_master_when_it_runs(mono: Mono) -> None:
    mono.stage("gosvc/x.go", "package main\n")
    assert mono.hook("git commit -m x", "gosvc", env={"FAKE_TOOL_RC": "1"}).returncode == 2
    assert mono.hook("git commit -m x", "gosvc").returncode == 0


def test_a_validate_repo_runs_exactly_as_master_unless_nothing_changed(mono: Mono) -> None:
    mono.write("dev/validate.py", f"import os, sys\nopen({str(mono.log)!r}, 'a').write("
               "'{\"tool\": \"validate\", \"cwd\": \"\", \"argv\": []}\\n')\nsys.exit(1)\n")
    mono.git("add", ".")
    mono.git("commit", "-qm", "validator")
    mono.git("push", "-q")
    assert guardrails.choose_gate(mono.root) == ["python", "dev/validate.py"]
    mono.stage("docs.md", "x\n")  # no Python in it: that is ruff's business, not this gate's
    assert mono.hook("git commit -m x", ".").returncode == 2
    assert [entry["tool"] for entry in mono.ran()] == ["validate"]
    assert mono.hook("git push", ".").returncode == 0  # nothing new on the remote
    mono.git("reset", "-q", "--hard")
    assert mono.hook(EMPTY, ".").returncode == 0  # the one exception: an empty change set
    assert mono.ran() == []


@pytest.mark.parametrize("gate_dir", ["js"])
def test_a_whole_package_tool_runs_unchanged(mono: Mono, gate_dir: str) -> None:
    mono.write(f"{gate_dir}/package.json", '{"name": "x", "scripts": {"lint": "x"}}\n')
    mono.git("add", ".")
    mono.git("commit", "-qm", "pkg")
    assert guardrails.choose_gate(mono.root / gate_dir) == ["npm", "run", "lint"]
    mono.stage(f"{gate_dir}/README.md", "x\n")
    assert mono.hook("git commit -m x", gate_dir, env={"FAKE_TOOL_RC": "1"}).returncode == 2
    assert mono.argvs() == [["npm", "run", "lint"]]
    mono.stage("infra/other.txt", "x\n")  # outside it, and the changed set is not empty: as master
    mono.git("reset", "-q", "--", f"{gate_dir}/README.md")
    assert mono.hook("git commit -m x", gate_dir).returncode == 0
    assert mono.argvs() == [["npm", "run", "lint"]]


def test_the_first_commit_of_a_repo_has_no_head_and_reads_fine(mono: Mono) -> None:
    fresh = mono.root / "svc" / "fresh"
    fresh.mkdir()
    mono.git("init", "-q", ".", cwd=fresh)
    (fresh / "pyproject.toml").write_text("[project]\nname='f'\nversion='0'\n")
    (fresh / "bad.py").write_text(_BAD)
    (fresh / "notes.md").write_text("x\n")
    mono.git("add", "notes.md", cwd=fresh)
    assert mono.hook("git commit -m x", "svc/fresh").returncode == 0
    assert mono.ran() == []  # the one staged file is not Python, and bad.py is untracked
    mono.git("add", "bad.py", cwd=fresh)
    assert mono.hook("git commit -m x", "svc/fresh").returncode == 2
    assert mono.argvs()[0] == _narrowed("./bad.py")


def test_for_every_command_it_never_runs_or_blocks_beyond_master(mono: Mono) -> None:
    """The design in one test. Whatever the command and wherever it stands: only master's own tool,
    from master's cwd, on nothing outside that cwd, and a block only where master's gate fails."""
    mono.stage("svc/new.py")
    mono.stage("infra/new_bad.py", _BAD)
    mono.write("svc/good.py", _BAD)
    mono.write("svc/untracked.py")
    commands = [*SIMPLE, *UNCERTAIN, *NOT_TRIGGERS, EMPTY, "git add good.py && git commit -m x"]
    for cwd in (".", "svc", "gosvc", "infra"):
        master = guardrails.choose_gate(mono.root / cwd)
        master_fails = False
        sample = commands if cwd == "svc" else commands[::5]
        if master:
            master_fails = subprocess.run(
                master, cwd=mono.root / cwd, env=mono.env, capture_output=True
            ).returncode != 0
        for command in sample:
            done = mono.hook(command, cwd)
            where = f"{command!r} from {cwd}"
            if not master or not guardrails.is_commit_or_push(command):
                assert done.returncode == 0 and mono.ran() == [], where
                continue
            for entry in mono.ran():
                assert [entry["tool"], *entry["argv"]][:1] == master[:1], where
                assert entry["cwd"] == str(mono.root / cwd if cwd != "." else mono.root), where
                argv = [entry["tool"], *entry["argv"]]
                if argv != master:
                    assert master == WHOLE_RUFF, where
                    assert argv[:2] == _narrowed(), where
                    assert all(a.startswith("./") and ".." not in a for a in argv[2:]), where
                    assert all((mono.root / cwd / a).is_file() for a in argv[2:]), where
            if done.returncode == 2:
                assert master_fails, where
    # Now master's gate passes in svc, and a finding only an explicit path can reach is staged:
    # nothing may block, whichever the command, or the invariant above was vacuous.
    (mono.root / "svc/legacy_bad.py").unlink()
    mono.write("svc/good.py")
    mono.write("svc/.gitignore", "ignored_bad.py\n")
    mono.write("svc/ignored_bad.py", _BAD)
    mono.git("add", "-f", "svc/ignored_bad.py")
    for command in [*SIMPLE, *UNCERTAIN[::4], EMPTY]:
        assert mono.hook(command).returncode == 0, command


def test_the_hook_reads_settings_as_before_and_does_not_look_up_the_tree(mono: Mono) -> None:
    """Rule 4: config lookup is unchanged, so a skip at the root does not reach a package cwd."""
    mono.write(".agentic-forge/config.json", '{"test_gate": {"skip": true}}\n')
    mono.stage("svc/new_bad.py", _BAD)
    assert mono.hook("git commit -m x").returncode == 2
    assert mono.hook("git commit -m x", ".").returncode == 0


# --- narrow less: every shape where the narrowing condition had been too optimistic (round 2) ---


@pytest.mark.parametrize("staged", [True, False])
def test_a_symlink_runs_whole_since_the_whole_gate_reads_its_target(
    mono: Mono, staged: bool
) -> None:
    (mono.root / "svc" / "e.py").symlink_to(mono.root / "infra" / "script.py")
    mono.git("add", "svc/e.py")
    if not staged:  # already tracked, and this commit touches nothing under cwd
        mono.git("commit", "-qm", "link")
        mono.stage("infra/script.py", _BAD + "y = 2\n")
    assert mono.hook("git commit -m x").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


def test_a_tracked_link_with_another_kind_of_name_does_not_count(mono: Mono) -> None:
    (mono.root / "svc" / "NOTES").symlink_to(mono.root / "README.md")
    mono.git("add", "svc/NOTES")
    mono.git("commit", "-qm", "link")
    assert mono.hook(EMPTY).returncode == 0
    mono.stage("infra/other.tf", "# x\n")
    assert mono.hook("git commit -m x").returncode == 0
    assert mono.ran() == []


def test_a_path_through_a_symlink_runs_whole(mono: Mono) -> None:
    """Staged as a real directory, and since replaced on disk by a link to somewhere else."""
    mono.stage("svc/moved/new.py")
    (mono.root / "svc" / "moved" / "new.py").unlink()
    (mono.root / "svc" / "moved").rmdir()
    (mono.root / "svc" / "moved").symlink_to(mono.root / "infra")
    assert mono.hook("git commit -m x").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


def test_a_stat_dirty_file_reads_as_changed_and_the_gate_still_decides(mono: Mono) -> None:
    """The cost of not refreshing the index: a touched file is listed, so it gets linted."""
    os.utime(mono.root / "svc" / "legacy_bad.py", (1, 1))
    assert mono.hook("git commit -am x").returncode == 2
    assert mono.argvs() == [_narrowed("./legacy_bad.py"), WHOLE_RUFF]


def test_a_repos_clean_filter_does_not_run_in_the_reads(mono: Mono) -> None:
    marker = mono.base / "ran"
    script = mono.base / "clean.sh"
    script.write_text(f'#!/bin/sh\ntouch "{marker}"\ncat\n')
    script.chmod(0o755)
    mono.write(".gitattributes", "*.md filter=mark\n")
    mono.git("add", ".gitattributes")
    mono.git("commit", "-qm", "attrs")
    mono.git("config", "filter.mark.clean", str(script))
    os.utime(mono.root / "README.md", (1, 1))
    assert mono.hook("git commit -am x").returncode == 0
    assert not marker.exists()


@pytest.mark.parametrize(("place", "ran"), [("svc/ghost", [WHOLE_RUFF]), ("infra/ghost", [])])
def test_a_gitlink_under_cwd_runs_whole_even_with_nothing_on_disk(
    mono: Mono, place: str, ran: list
) -> None:
    head = mono.git("rev-parse", "HEAD").strip()
    mono.git("update-index", "--add", "--cacheinfo", f"160000,{head},{place}")
    mono.hook("git commit -m x")
    assert mono.argvs() == ran


@pytest.mark.parametrize(
    "command",
    ["git push", "git push origin", "git push origin HEAD", "git push origin main",
     "git push -u origin main", "git push --set-upstream origin HEAD"],
)
def test_a_narrowed_push_really_lands_on_that_branch_and_nowhere_else(
    mono: Mono, command: str
) -> None:
    mono.commit("svc/new.py")
    assert mono.hook(command).returncode == 0
    assert mono.argvs() == [_narrowed("./new.py")]
    subprocess.run(command, shell=True, cwd=mono.root, env=mono.env, check=True,
                   capture_output=True)
    remote = mono.git("ls-remote", str(mono.origin), "refs/heads/*").split()
    assert remote == [mono.git("rev-parse", "HEAD").strip(), "refs/heads/main"]


@pytest.mark.parametrize(
    ("setup", "command", "lands"),
    [
        ("git config push.default upstream", "git push origin", True),
        ("git config push.default upstream", "git push", True),
        ("git config remote.origin.push refs/heads/feature:refs/heads/main",
         "git push origin feature", True),
        # `HEAD` is not mapped, as it turns out. The config still says "not only this", so: whole.
        ("git config remote.origin.push refs/heads/feature:refs/heads/main",
         "git push origin HEAD", False),
    ],
)
def test_a_push_really_landing_on_another_branch_runs_whole(
    mono: Mono, setup: str, command: str, lands: bool
) -> None:
    """Each reads as a push of `feature`, whose commit is already on `origin/feature`, and lands
    that commit on main."""
    (mono.root / "svc" / "legacy_bad.py").unlink()
    mono.git("add", "-A")
    mono.git("commit", "-qm", "clean")
    mono.git("push", "-q")
    mono.git("switch", "-q", "-c", "feature")
    mono.commit("svc/landing_bad.py", _BAD)
    mono.git("push", "-q", "origin", "feature")
    mono.git("branch", "-q", "-u", "origin/main")
    mono.sh(setup)
    assert mono.hook(command).returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]
    subprocess.run(command, shell=True, cwd=mono.root, env=mono.env, check=True,
                   capture_output=True)
    landed = mono.git("ls-tree", "-r", "--name-only", "refs/heads/main", cwd=mono.origin)
    assert ("svc/landing_bad.py" in landed) is lands


def test_an_upstream_elsewhere_runs_whole_even_for_the_current_branch_by_name(mono: Mono) -> None:
    mono.git("switch", "-q", "-c", "topic")
    mono.git("push", "-q", "origin", "topic")
    mono.git("branch", "-q", "-u", "origin/main")  # a tracking ref exists, and `@{push}` differs
    assert mono.hook("git push origin topic").returncode == 2
    assert mono.argvs() == [WHOLE_RUFF]


_BAD_CMD = "printf 'import os\\n' >"
_COMMIT_THEN_STAGE = "git add -A; git commit -qm c; " + _BAD_CMD + " {0}; git add {0}"
# Each adds a finding the whole gate sees, so the hook must block, where a narrowed read allowed.
_MASTER_BLOCKS = {
    "preview makes .pyw lintable": (
        "printf '[tool.ruff]\\npreview = true\\n' >> svc/pyproject.toml;"
        + _COMMIT_THEN_STAGE.format("svc/bad.pyw"), "git commit -m x"),
    "dotted under tool": (
        "printf '[tool]\\nruff.include = [\"*.py\", \"*.pxi\"]\\n' >> svc/pyproject.toml;"
        + _COMMIT_THEN_STAGE.format("svc/bad.pxi"), "git commit -m x"),
    "top-level dotted": (
        "printf 'tool.ruff.include = [\"*.py\", \"*.pxi\"]\\n[project]\\nname=\"s\"\\n"
        "version=\"0\"\\n' > svc/pyproject.toml;" + _COMMIT_THEN_STAGE.format("svc/bad.pxi"),
        "git commit -m x"),
    "spaced header": (
        "printf '[ tool.ruff ]\\ninclude = [\"*.py\", \"*.pxi\"]\\n' >> svc/pyproject.toml;"
        + _COMMIT_THEN_STAGE.format("svc/bad.pxi"), "git commit -m x"),
    "quoted extend": (
        "printf 'include = [\"*.py\", \"*.pxi\"]\\n' > svc/base.toml;"
        "printf '\"extend\" = \"base.toml\"\\n' > svc/ruff.toml;"
        + _COMMIT_THEN_STAGE.format("svc/bad.pxi"), "git commit -m x"),
    "descendant config": (
        "mkdir svc/sub; printf 'extend-include = [\"*.pxi\"]\\nextension = {pxi = \"python\"}\\n'"
        " > svc/sub/ruff.toml;" + _COMMIT_THEN_STAGE.format("svc/sub/bad.pxi"), "git commit -m x"),
    "user-level config": (
        "mkdir -p $HOME/.config/ruff; printf 'include = [\"*.py\", \"*.pxi\"]\\n' >"
        f" $HOME/.config/ruff/ruff.toml; {_BAD_CMD} svc/bad.pxi; git add svc/bad.pxi",
        "git commit -m x"),
    "new link to a new bad file outside": (
        f"{_BAD_CMD} infra/new_bad.py; ln -s ../infra/new_bad.py svc/link.py; git add -A",
        "git commit -m x"),
    "a tracked link's target changes outside": (
        "printf 'y = 1\\n' > infra/t.py; ln -s ../infra/t.py svc/link.py; git add -A;"
        f"git commit -qm l; {_BAD_CMD} infra/t.py; git add -A", "git commit -m x"),
    "the same, pushed": (
        "printf 'y = 1\\n' > infra/t.py; ln -s ../infra/t.py svc/link.py; git add -A;"
        f"git commit -qm l; git push -q; {_BAD_CMD} infra/t.py; git add -A; git commit -qm b",
        "git push"),
    "nested repo, add -A": (
        f"mkdir svc/nested; cd svc/nested; git init -q; {_BAD_CMD} bad.py; git add -A;"
        "git commit -qm b", "git add -A && git commit -m x"),
    "nested repo, add by name": (
        f"mkdir svc/nested; cd svc/nested; git init -q; {_BAD_CMD} bad.py; git add -A;"
        "git commit -qm b", "git add nested && git commit -m x"),
}
_TIGHTEN_ABOVE = (
    "printf 'select = [\"E\"]\\n' > ruff.toml; printf 'import os\\n' > svc/old.py; git add -A;"
    "git commit -qm c; git push -q; printf 'select = [\"E\", \"F\"]\\n' > ruff.toml; git add -A"
)
_MASTER_BLOCKS.update({
    "a config above cwd tightened": (
        _TIGHTEN_ABOVE, "git commit -m x"),
    "a config above cwd tightened, pushed": (
        _TIGHTEN_ABOVE + "; git commit -qm t", "git push"),
    "a deleted __init__.py": (
        "printf 'select = [\"INP\"]\\n' > svc/ruff.toml; mkdir svc/sub; : > svc/sub/__init__.py;"
        "printf 'x = 1\\n' > svc/sub/m.py; git add -A; git commit -qm c; git push -q;"
        "git rm -q svc/sub/__init__.py", "git commit -m x"),
})
_SUBMODULE = (
    "git init -q -b main $BASE/lib; git -C $BASE/lib commit -q --allow-empty -m i;"
    "git -c protocol.file.allow=always submodule -q add $BASE/lib svc/lib; git commit -qm s;"
    f"git push -q; cd svc/lib; {_BAD_CMD} bad.py; git add -A; git commit -qm b; cd ../..;"
)
_MASTER_BLOCKS.update({
    "submodule bump": (_SUBMODULE + "git add svc/lib", "git commit -m x"),
    "submodule bump, -am": (_SUBMODULE, "git commit -am x"),
    "submodule bump, pushed": (_SUBMODULE + "git add svc/lib; git commit -qm bump", "git push"),
})


@pytest.mark.parametrize("name", sorted(_MASTER_BLOCKS))
def test_a_narrowed_allow_implies_master_allows(mono: Mono, name: str) -> None:
    (mono.root / "svc" / "legacy_bad.py").unlink()
    mono.git("add", "-A")
    mono.git("commit", "-qm", "clean")
    mono.git("push", "-q")
    setup, command = _MASTER_BLOCKS[name]
    mono.sh(setup)
    master = subprocess.run(WHOLE_RUFF, cwd=mono.root / "svc", env=mono.env, capture_output=True)
    assert master.returncode != 0, "this scenario proves nothing unless master blocks it"
    done = mono.hook(command)
    assert done.returncode == 2, done.stderr


def test_a_heredoc_line_starting_with_its_delimiter_runs_whole(mono: Mono) -> None:
    """bash also closes a heredoc on `EOF)`, so what follows it would be commands."""
    mono.stage("svc/new.py")
    mono.hook("git commit -m \"$(cat <<'EOF'\nmsg\nEOF)\nEOF\n)\"")
    assert mono.argvs() == [WHOLE_RUFF]


def test_an_xdg_user_config_runs_whole(mono: Mono) -> None:
    config = mono.base / "xdg" / "ruff" / ".ruff.toml"
    config.parent.mkdir(parents=True)
    config.write_text("line-length = 80\n")  # any user-level config: the file, not a key in it
    mono.stage("svc/new.py")
    mono.hook("git commit -m x", env={"XDG_CONFIG_HOME": str(config.parents[1])})
    assert mono.argvs() == [WHOLE_RUFF]
    assert mono.hook("git commit -m x").returncode == 0  # and only when it is there
    assert mono.argvs() == [_narrowed("./new.py")]


def _recording_git(directory: Path, log: Path) -> dict[str, str]:
    directory.mkdir()
    tool = directory / "git"
    tool.write_text(f'#!/bin/sh\nprintf "%s\\0" "$@" >> "{log}"\nprintf "\\n" >> "{log}"\n')
    tool.chmod(0o755)
    return {"PATH": f"{directory}{os.pathsep}/usr/bin:/bin", "HOME": str(directory)}


def test_real_zsh_expands_what_the_matcher_refuses(tmp_path: Path) -> None:
    zsh = shutil.which("zsh")
    if not zsh:
        pytest.skip("zsh is not installed")
    log = tmp_path / "log"
    env = _recording_git(tmp_path / "bin", log)
    for word in ("=ls", "''=ls", '""=ls'):
        command = f"git add {word} && git commit -m x"
        assert gate_scope.parse_simple(command) is None, command
        log.unlink(missing_ok=True)
        subprocess.run([zsh, "-c", command], env=env, cwd=tmp_path, check=True)
        passed = log.read_text().split("\n")[0].split("\0")
        assert passed[0] == "add" and passed[1].endswith("/ls"), command  # not a literal


def test_every_shell_passes_the_words_the_matcher_read(tmp_path: Path) -> None:
    log = tmp_path / "log"
    env = _recording_git(tmp_path / "bin", log)
    shells = [shell for shell in map(shutil.which, ("zsh", "bash", "dash")) if shell]
    assert shells
    for command in SIMPLE:
        if "<<" in command:  # the matcher's stand-in for a heredoc is not a word the shell passes
            continue
        words = shlex.split(command)
        cut = words.index("&&") if "&&" in words else len(words)
        expected = [words[1:cut], *([words[cut + 2 :]] if cut < len(words) else [])]
        for shell in shells:
            log.unlink(missing_ok=True)
            subprocess.run([shell, "-c", command], env=env, cwd=tmp_path, check=True)
            got = [line.split("\0")[:-1] for line in log.read_text().split("\n")[:-1]]
            assert got == expected, (shell, command)
