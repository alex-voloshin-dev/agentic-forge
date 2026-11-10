#!/usr/bin/env python3
"""Tier-0 gate CLI: validate the agentic-forge plugin.

Usage:
    python dev/validate.py            # validate ./plugin
    python dev/validate.py <path>     # validate a specific plugin directory

Beside the plugin, it validates the repository's maintainer skills, ``<plugin>/../.claude/skills/*``
(ADR 0105), with the same per-skill checks; they are not counted in the listing budget.

Exit code 0 if there are no errors, 1 otherwise. Warnings never fail the gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import validation  # noqa: E402
from agentic_forge.validation import validate_docs, validate_plugin  # noqa: E402


def main(argv: list[str]) -> int:
    plugin_dir = Path(argv[1]).resolve() if len(argv) > 1 else _REPO_ROOT / "plugin"
    if not plugin_dir.is_dir():
        print(f"error: plugin directory not found: {plugin_dir}", file=sys.stderr)
        return 1
    report = validate_plugin(plugin_dir)
    # Doc-sync checks need the repo root (docs/ lives a level above plugin/). Run them when the
    # plugin sits in a repo with the docs tree — skipped when validating a standalone plugin dir.
    repo_root = plugin_dir.parent
    if (repo_root / validation.REPO_MARKER).is_file():
        report.extend(validate_docs(repo_root))
    # Maintainer skills (`<repo>/.claude/skills/*`, ADR 0105) do not ship, so they are outside
    # validate_plugin and outside the listing budget — but they are gated like any skill. Only in
    # this repository (validation.maintainer_root): never a user's personal ~/.claude/skills.
    maintainer = validation.maintainer_skill_dirs(repo_root)
    report.extend(validation.validate_maintainer_skills(repo_root, plugin_dir))
    print(report.render())
    print(validation.budget_line(plugin_dir))  # printed pass or fail: a measured guard is visible
    if maintainer:
        names = ", ".join(p.name for p in maintainer)
        print(
            f"maintainer skills: {len(maintainer)} validated, not shipped, not in the budget "
            f"({names})"
        )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
