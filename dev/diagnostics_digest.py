#!/usr/bin/env python3
"""Print a digest of the self-diagnostics log (ADR 0039).

Reads ``.agentic-forge/diagnostics.jsonl`` (written by the guardrail hooks + eval runners when
``AGENTIC_FORGE_DIAGNOSTICS`` is set) and prints the
:func:`agentic_forge.diagnostics.digest` "top problems" summary. The digest logic is pure and
tested; this is the thin I/O wrapper. See docs/architecture/scheduling-observability.md.

    python dev/diagnostics_digest.py            # digest ./.agentic-forge/diagnostics.jsonl
    python dev/diagnostics_digest.py --repo X    # digest a specific project dir
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import diagnostics  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Digest the self-diagnostics log.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv[1:])
    lines = diagnostics.load(args.repo.resolve())
    print(diagnostics.render(diagnostics.digest(lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
