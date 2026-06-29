#!/usr/bin/env python3
"""Run the external reviewer CLI (codex) as a subagent over a target file (ADR 0042).

Reads the plugin settings (`external_reviewer.command`; refuses unless `enabled` or `--force`),
runs the configured CLI to review a code change / plan / product or technical doc, prints the
verdict + findings, and can write a `review.md` handoff (`--out`) so a codex review feeds the
review-loop / review-scan ecosystem. Degrades gracefully (clear message, no crash) when the CLI is
absent or disabled. See docs/architecture/decisions/0042-external-reviewer.md.

    python dev/external_review.py --target diff.txt --kind code
    python dev/external_review.py --target docs/sdlc/x/plan.md --kind plan --out review.md --force

Exit 0 on approve / skipped (disabled or CLI absent); 1 on a `changes` verdict or an
unparseable review.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "lib"))

from agentic_forge import external_review, settings  # noqa: E402


def _render(result: dict[str, Any]) -> str:
    lines = [f"verdict: {result['verdict']}"]
    for f in result["findings"]:
        lines.append(f"- [{f['severity']}] {f.get('location') or '?'}: {f['issue']}")
        if f.get("suggestion"):
            lines.append(f"    fix: {f['suggestion']}")
    if not result["findings"]:
        lines.append("(no findings)")
    return "\n".join(lines)


def _write_review_md(path: Path, target: str, result: dict[str, Any], iteration: int) -> None:
    header = {
        "type": "review",
        "target": target,
        "iteration": iteration,
        "verdict": result["verdict"],
        "findings": result["findings"],  # sanitised in parse_review -> safe in the header too
    }
    fm = yaml.safe_dump(header, sort_keys=False).strip()
    body = _render(result)
    path.write_text(f"---\n{fm}\n---\n# External review ({result['verdict']})\n\n{body}\n", "utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the external reviewer CLI over a target.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--target", type=Path, required=True, help="file to review")
    parser.add_argument("--kind", choices=sorted(external_review.KINDS), default="code")
    parser.add_argument("--command", default=None, help="override the configured reviewer command")
    parser.add_argument("--out", type=Path, default=None, help="write a review.md handoff here")
    parser.add_argument("--iteration", type=int, default=1, help="iteration N for the review.md")
    parser.add_argument("--force", action="store_true", help="run even if not enabled in settings")
    args = parser.parse_args(argv[1:])

    if not args.target.is_file():  # graceful: never crash on a bad path (even with codex installed)
        print(f"target not found: {args.target}", file=sys.stderr)
        return 1

    repo = args.repo.resolve()
    resolved = settings.resolve(repo)
    command = args.command or resolved.external_reviewer_command
    if not (resolved.external_reviewer_enabled or args.force):
        print("external reviewer disabled (set external_reviewer.enabled, or pass --force)")
        return 0
    if not external_review.is_available(command):
        print(f"external reviewer {command!r} not found on PATH — skipping")
        return 0

    result = external_review.review(
        args.target.read_text(encoding="utf-8"), args.kind, command=command, workdir=repo
    )
    if result is None:
        print(f"external reviewer {command!r} produced no parseable review", file=sys.stderr)
        return 1
    print(_render(result))
    if args.out:
        _write_review_md(args.out, str(args.target), result, args.iteration)
        print(f"wrote {args.out}")
    return 0 if result["verdict"] == "approve" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
