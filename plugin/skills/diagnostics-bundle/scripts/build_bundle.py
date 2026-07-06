#!/usr/bin/env python3
"""Package a repo's plugin diagnostics into a redacted zip in ~/Downloads (ADR 0053).

Shipped entry point for the `diagnostics-bundle` skill: a thin wrapper over the tested
`agentic_forge.diag_bundle` lib. Windows to the last N days (default 7), writes the strict
`~/Downloads/agentic-forge-diagnostics-<ts>.zip`, and prints a one-line summary.

    python3 "${CLAUDE_PLUGIN_ROOT}/skills/diagnostics-bundle/scripts/build_bundle.py"
    python3 ".../build_bundle.py" --days 30 --repo /path/to/repo
    python3 ".../build_bundle.py" --days 0        # full history (no window)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# The shipped lib lives at <plugin>/lib; this script is at <plugin>/skills/<name>/scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from agentic_forge import diag_bundle  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Bundle plugin diagnostics into ~/Downloads.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="repo to bundle (default: .)")
    parser.add_argument(
        "--days", type=int, default=diag_bundle.DEFAULT_WINDOW_DAYS,
        help="window in days (default 7; 0 = full history)",
    )
    parser.add_argument("--home", type=Path, default=None, help="home dir (default: ~)")
    args = parser.parse_args(argv[1:])

    now = datetime.now(timezone.utc).isoformat()
    days = None if args.days <= 0 else args.days
    out = diag_bundle.build_bundle(args.repo.resolve(), None, home=args.home, days=days, now=now)
    print(f"Diagnostics bundle written to: {out}")
    print(f"Window: {diag_bundle.window_text(days=days, now=now)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
