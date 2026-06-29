#!/usr/bin/env python3
"""Sync each subagent's ``model:`` frontmatter to the committed runtime tier policy (ADR 0046).

The agent ``model`` frontmatter is what Claude Code reads when a skill delegates via ``Task``. This
keeps it equal to ``models.VALIDATED_TIERS`` (resolved through ``models.frontmatter_model``) so live
delegation runs each role at its gate-validated tier. ``--check`` (default) reports drift and exits
non-zero (Tier-0 enforces the same invariant); ``--apply`` rewrites the lines.

    python dev/sync_models.py            # check (CI-friendly): exit 1 on drift
    python dev/sync_models.py --apply    # rewrite the model: lines from the policy
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import models  # noqa: E402
from agentic_forge.frontmatter import FrontmatterError, parse  # noqa: E402


@dataclass(frozen=True)
class Drift:
    """A role's current vs policy-expected ``model:`` frontmatter value."""

    role: str
    path: Path
    current: str | None  # None = no model: line at all
    expected: str

    @property
    def changed(self) -> bool:
        return self.current != self.expected


def plan_sync(agents_dir: Path) -> list[Drift]:
    """Per agent ``*.md``, the (role, current model, expected model) — pure over the dir listing."""
    out: list[Drift] = []
    for agent_md in sorted(agents_dir.glob("*.md")):
        role = agent_md.stem
        try:
            fm, _ = parse(agent_md.read_text(encoding="utf-8"))
        except FrontmatterError:
            continue  # not a valid agent file; Tier-0's validate_agent reports it
        current = fm.get("model")
        out.append(
            Drift(role, agent_md, None if current is None else str(current),
                  models.frontmatter_model(role))
        )
    return out


def main(argv: list[str], *, agents_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync agent model: frontmatter to the policy.")
    parser.add_argument("--apply", action="store_true", help="rewrite model: lines (else check)")
    args = parser.parse_args(argv[1:])

    adir = agents_dir or (_REPO_ROOT / "plugin" / "agents")
    drifts = [d for d in plan_sync(adir) if d.changed]
    if not drifts:
        print("models: all agents match the validated tier policy")
        return 0

    failed = False
    for d in drifts:
        if not args.apply:
            print(f"  drift {d.role}: {d.current} != {d.expected} (run --apply)", file=sys.stderr)
            continue
        try:
            new = models.set_frontmatter_model(d.path.read_text(encoding="utf-8"), d.expected)
        except ValueError:  # no frontmatter model: line — can't sync; flag and keep going
            print(f"  ! {d.role}: no 'model:' line — add 'model: {d.expected}'", file=sys.stderr)
            failed = True
            continue
        d.path.write_text(new, encoding="utf-8")
        print(f"  synced {d.role}: {d.current} -> {d.expected}")
    if not args.apply:
        return 1  # drift found in check mode
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
