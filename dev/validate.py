#!/usr/bin/env python3
"""Tier-0 gate CLI: validate the agentic-forge plugin.

Usage:
    python dev/validate.py            # validate ./plugin
    python dev/validate.py <path>     # validate a specific plugin directory

Exit code 0 if there are no errors, 1 otherwise. Warnings never fail the gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge.validation import validate_plugin  # noqa: E402


def main(argv: list[str]) -> int:
    plugin_dir = Path(argv[1]).resolve() if len(argv) > 1 else _REPO_ROOT / "plugin"
    if not plugin_dir.is_dir():
        print(f"error: plugin directory not found: {plugin_dir}", file=sys.stderr)
        return 1
    report = validate_plugin(plugin_dir)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
