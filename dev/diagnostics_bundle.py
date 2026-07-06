#!/usr/bin/env python3
"""Package a repo's plugin diagnostics into one redacted, structured zip (ADR 0052).

Collects the audit + diagnostics logs, a rendered ``log-summary.txt``, an ``environment.txt``
snapshot, and the plugin/config metadata slices into a consistent bundle a maintainer can analyze
or a user can share. The manifest logic is pure and tested (:mod:`agentic_forge.diag_bundle`); this
is the thin I/O wrapper. See docs/architecture/scheduling-observability.md.

    python dev/diagnostics_bundle.py                       # last 7 days -> ~/Downloads/<prefix>.zip
    python dev/diagnostics_bundle.py --days 30             # a 30-day window
    python dev/diagnostics_bundle.py --days 0              # full history (no window)
    python dev/diagnostics_bundle.py --repo X --out Y.zip  # a specific repo / output path
    python dev/diagnostics_bundle.py --home ~/other        # look up user config/settings elsewhere
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import diag_bundle  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Package plugin diagnostics into a redacted zip.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="repo to bundle (default: .)")
    parser.add_argument(
        "--days", type=int, default=diag_bundle.DEFAULT_WINDOW_DAYS,
        help="window in days (default 7; 0 = full history)",
    )
    parser.add_argument("--out", type=Path, default=None, help="output zip (default: ~/Downloads)")
    parser.add_argument("--home", type=Path, default=None, help="home dir for user config/settings")
    args = parser.parse_args(argv[1:])

    now = datetime.now(timezone.utc).isoformat()
    days = None if args.days <= 0 else args.days
    written = diag_bundle.build_bundle(
        args.repo.resolve(), args.out, home=args.home, days=days, now=now
    )
    print(f"Wrote diagnostics bundle: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
