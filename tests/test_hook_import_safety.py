"""The guardrail hooks (ADR 0019) run under whatever ``python3`` is on PATH — which may lack the
plugin's third-party deps (jsonschema, PyYAML) and may even predate ``datetime.UTC`` (Python 3.11).
A guardrail must never break the session, so the hook-reachable import path must be **stdlib-only at
import time**, with third-party deps imported lazily and degrading gracefully. These tests pin that
contract (regression guard for the "PreToolUse hook error / ImportError" crash)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


def test_hook_import_chain_imports_without_third_party_deps() -> None:
    # Block jsonschema + PyYAML, then import every module a guardrail hook reaches. None may raise.
    code = (
        "import sys\n"
        "sys.modules['jsonschema'] = None\n"
        "sys.modules['yaml'] = None\n"
        "import agentic_forge.guardrails\n"
        "import agentic_forge.settings\n"
        "import agentic_forge.diagnostics\n"
        "import agentic_forge.handoff\n"
        "import agentic_forge.frontmatter\n"
        "import agentic_forge.vault\n"
        "print('ok')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO / "plugin" / "lib")}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_frontmatter_parse_degrades_without_pyyaml(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentic_forge import frontmatter

    monkeypatch.setitem(sys.modules, "yaml", None)  # make the lazy `import yaml` fail
    with pytest.raises(frontmatter.FrontmatterError):  # a clear error, not a raw ImportError
        frontmatter.parse("---\na: 1\n---\nbody\n")


def test_handoff_validate_header_skips_without_jsonschema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentic_forge import handoff

    monkeypatch.setitem(sys.modules, "jsonschema", None)
    # An otherwise-invalid header (missing required fields) returns no errors when no validator is
    # available — degrade-open rather than crash the importing hook.
    assert handoff.validate_header({"type": "prd"}, expected_type="prd") == []
