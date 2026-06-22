from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "dev"))

import run_agent_evals  # noqa: E402
import run_spine_e2e  # noqa: E402
import validate as validate_cli  # noqa: E402


def test_validate_cli_main_ok() -> None:
    # The real plugin passes Tier-0.
    assert validate_cli.main(["validate"]) == 0


def test_validate_cli_missing_dir() -> None:
    assert validate_cli.main(["validate", "/no/such/plugin/dir"]) == 1


def test_run_agent_evals_dry_ok() -> None:
    assert run_agent_evals.main(["run", "--runner", "dry"]) == 0


def test_run_spine_e2e_dry_ok() -> None:
    assert run_spine_e2e.main(["run", "--runner", "dry"]) == 0


def test_build_runners_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown runner"):
        run_agent_evals._build_runners("bogus", "reviewer", _REPO / "plugin", "m")
