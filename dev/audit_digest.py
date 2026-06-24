#!/usr/bin/env python3
"""Print a digest of the guardrail audit log (Stage 7 observability).

Reads ``.agentic-forge/audit.jsonl`` (written by the logging guardrail hook) and prints the
:func:`agentic_forge.observability.digest` summary. The digest logic is pure and tested; this is
the thin I/O wrapper. See docs/architecture/scheduling-observability.md.

    python dev/audit_digest.py            # digest ./.agentic-forge/audit.jsonl
    python dev/audit_digest.py --repo X   # digest a specific project dir
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import observability  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Digest the guardrail audit log.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv[1:])
    lines = observability.load_audit(args.repo.resolve())
    print(observability.render(observability.digest(lines)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
