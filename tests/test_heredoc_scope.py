"""Heredoc bodies are data, not command text (ADR 0079).

Field case: a maintainer writing a *document about* the environment-dump rule with
`cat >> report.md <<EOF` was blocked by that very rule, because the classifier scanned the whole
command string and the document quoted the commands it documents. Reproduced here on the way in —
the reproduction script itself could not be written with a heredoc.

The security question this file answers: stripping bodies must NOT open a bypass. A body whose
receiver *executes* it (an interpreter, or a remote shell) is a program and stays in scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "lib"))

from agentic_forge import guardrails  # noqa: E402

DUMP = "kubectl exec pod -- printenv"
RM = "rm -rf /"


def _doc(command_word: str, payload: str) -> str:
    return f"{command_word} <<'EOF'\n{payload}\nEOF"


@pytest.mark.parametrize(
    "command",
    [
        _doc("cat >> report.md", f"| `{DUMP}` | blocked |"),  # the exact field case
        _doc("cat > notes.md", DUMP),
        _doc("tee -a runbook.md", DUMP),
        _doc("cat > adr.md", f"We block `{RM}` because it deletes everything."),
    ],
)
def test_documentation_heredoc_is_not_a_command(command: str) -> None:
    assert not guardrails.classify_command(command).block


@pytest.mark.parametrize(
    "command",
    [
        _doc("bash", DUMP),  # the body IS the program
        _doc("sh -s", DUMP),
        _doc("ssh deploy@host", RM),  # a remote shell runs it too
        f"cat <<'EOF' | bash\n{DUMP}\nEOF",  # piped into an interpreter on the OPENING line
    ],
)
def test_an_executed_body_stays_in_scope(command: str) -> None:
    """Any body its receiver will RUN must still be classified — no bypass."""
    assert guardrails.classify_command(command).block


@pytest.mark.parametrize("receiver", ["bash", "sh -s", "python3", "node", "/usr/bin/perl"])
def test_an_interpreter_body_is_never_stripped(receiver: str) -> None:
    """The scope decision, asserted directly: whether the deny-list ultimately blocks a given
    payload is a separate question (a quoted string inside a Python script is data, by design —
    ADR 0054), but the body must never be hidden from it."""
    assert DUMP in guardrails.strip_heredoc_bodies(_doc(receiver, DUMP))


def test_a_real_invocation_is_untouched() -> None:
    assert guardrails.classify_command(DUMP).block
    assert guardrails.classify_command(f"{RM}").block


def test_strip_keeps_structure_and_terminators() -> None:
    stripped = guardrails.strip_heredoc_bodies(_doc("cat > f.md", "secret payload"))
    assert "secret payload" not in stripped
    assert stripped.startswith("cat > f.md <<'EOF'") and stripped.endswith("EOF")


def test_unterminated_heredoc_does_not_hang_or_leak() -> None:
    """A body with no terminator (truncated input) must end the scan, not loop."""
    stripped = guardrails.strip_heredoc_bodies("cat > f.md <<'EOF'\nkubectl exec pod -- printenv")
    assert "printenv" not in stripped


def test_command_after_a_heredoc_is_still_classified() -> None:
    """Text following the terminator is command text again, not part of the body."""
    command = _doc("cat > f.md", "harmless") + f"\n{DUMP}"
    assert guardrails.classify_command(command).block


def test_block_message_names_the_file_write_workaround() -> None:
    """The field report worked around this blind; the message must not make anyone else guess."""
    message = guardrails.classify_command(DUMP).message
    assert "file-write tool" in message and "heredoc" in message
