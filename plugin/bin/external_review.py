#!/usr/bin/env python3
"""Run the external reviewer CLI (codex) as a subagent over a target file (ADR 0042).

Reads the plugin settings (`external_reviewer.command`; refuses unless `enabled` or `--force`),
runs the configured CLI to review one deliverable — `--kind` selects the criteria, one set per
failure mode (`external_review.KINDS`: code change, marketing deliverable, plan, product spec,
research brief, technical design, UX spec) — prints the verdict + findings, and can write a
`review.md` handoff (`--out`) so a codex review feeds the review-loop / review-scan ecosystem.
Degrades gracefully (clear message, no crash) when the CLI is absent or disabled, and when a review
is skipped it prints the actual reason and detail, and writes no `review.md`. See ADR 0042 (seam),
0057 (on by default), 0060 / 0061 / 0062 (auto-wired into every workflow that writes a reviewable
deliverable), 0100 (skip reasons + opt-in isolation) under docs/architecture/decisions/.

    python plugin/bin/external_review.py --target diff.txt --kind code
    python plugin/bin/external_review.py --target docs/sdlc/x/plan.md --kind plan --out review.md
    python plugin/bin/external_review.py --target docs/sdlc/x/ux-spec.md --kind ux

Exit 0 on approve / disabled / CLI absent; 1 on a `changes` verdict, any other skip (timeout,
process failure, invalid output, isolation unsupported), a `--target` / `--out` that is a symlink or
goes through a symlinked directory inside the repo, which are refused rather than followed, or a
`--target` that cannot be read as UTF-8 text.
"""

from __future__ import annotations

import argparse
import errno
import os
import stat
import sys
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]  # plugin/ — this ships to users
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))

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
    import yaml  # here, not at the top: only --out needs it, and a plugin-only install may lack it

    header = {
        "type": "review",
        "target": target,
        "iteration": iteration,
        "verdict": result["verdict"],
        "findings": result["findings"],  # sanitised in parse_review -> safe in the header too
    }
    fm = yaml.safe_dump(header, sort_keys=False).strip()
    body = _render(result)
    # O_NOFOLLOW, not only the check in main: the review can run for minutes after that check.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o666), "w", encoding="utf-8") as handle:
        handle.write(f"---\n{fm}\n---\n# External review ({result['verdict']})\n\n{body}\n")


def _symlink_below_repo(path: Path, repo: Path) -> Path | None:
    """The first symlinked parent directory of ``path`` that lies inside ``repo`` (a resolved path),
    or ``None``. Walked one component at a time as the OS does, so ``link/..`` cannot hide a link.
    A link above the repo root or outside it is left alone: /tmp and home directories are often
    links, and a target outside the repo is allowed."""
    parts = (Path.cwd() / path).parts
    real = Path(parts[0])
    for part in parts[1:-1]:
        if part == "..":
            real = real.parent
            continue
        step = real / part
        if not step.is_symlink():
            real = step
        elif step.is_relative_to(repo):
            return step
        else:
            real = Path(os.path.realpath(step))
    return None


def _read_target(path: Path) -> str:
    """The target's text. The file is opened without following a link and checked through its own
    descriptor, so nothing can be swapped in after the checks in :func:`main`. ``O_NONBLOCK`` is so
    a pipe put there is refused rather than waited on; it does nothing to a regular file."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(errno.EINVAL, "not a regular file")
    with os.fdopen(fd, encoding="utf-8") as handle:
        return handle.read()


def _absolute_if_path(command: str) -> str:
    """``command`` as an absolute path if it names one, against the caller's cwd. The capability
    check runs from the cwd and the review runs from the repo, so a relative one would mean two
    different programs. A bare name is left for PATH to find."""
    separators = (os.sep, os.altsep) if os.altsep else (os.sep,)
    # join, not abspath: abspath collapses `link/..` without following the link, which would name a
    # different program from the one the path means.
    named_path = any(sep in command for sep in separators)
    return os.path.join(os.getcwd(), command) if named_path else command


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the external reviewer CLI over a target.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--target", type=Path, required=True, help="file to review")
    parser.add_argument("--kind", choices=sorted(external_review.KINDS), default="code")
    # The operator's own argument: unlike a config file's `command` it may name a path, resolved
    # against the caller's cwd (ADR 0100).
    parser.add_argument("--command", default=None, help="override the configured reviewer command")
    parser.add_argument("--out", type=Path, default=None, help="write a review.md handoff here")
    parser.add_argument("--iteration", type=int, default=1, help="iteration N for the review.md")
    parser.add_argument("--force", action="store_true", help="run even if not enabled in settings")
    args = parser.parse_args(argv[1:])

    # A symlink could read a file the operator did not mean to send to a third party, or overwrite
    # one they did not mean to replace. Checked before anything runs, so a dangling link counts too.
    # A symlinked directory counts inside the repo, which may be what is under review.
    repo = args.repo.resolve()
    for flag, path in (("--target", args.target), ("--out", args.out)):
        if path is None:
            continue
        try:
            if path.is_symlink():
                print(
                    f"refusing {flag} {path}: it is a symlink; pass the real path", file=sys.stderr
                )
                return 1
            link = _symlink_below_repo(path, repo)
        except OSError as exc:
            print(f"refusing {flag} {path}: {type(exc).__name__}", file=sys.stderr)
            return 1
        if link is not None:
            print(
                f"refusing {flag} {path}: {link} is a symlink inside the repo; pass the real path",
                file=sys.stderr,
            )
            return 1
    if not args.target.is_file():  # graceful: never crash on a bad path (even with codex installed)
        print(f"target not found: {args.target}", file=sys.stderr)
        return 1

    resolved = settings.resolve(repo)
    command = resolved.external_reviewer_command
    if args.command:
        command = _absolute_if_path(args.command)
    if not (resolved.external_reviewer_enabled or args.force):
        if resolved.external_reviewer_disabled_by_repo:
            print(f"external reviewer disabled by this repo's config ({settings.CONFIG_PATH}); "
                  "pass --force to run it anyway")
        else:
            print("external reviewer disabled (set external_reviewer.enabled, or pass --force)")
        return 0
    if not external_review.is_available(command):
        print(f"external reviewer {command!r} not found on PATH — skipping")
        return 0

    try:
        text = _read_target(args.target)
    except UnicodeDecodeError:
        print(f"refusing --target {args.target}: it is not UTF-8 text", file=sys.stderr)
        return 1
    except OSError as exc:
        why = exc.strerror or type(exc).__name__
        print(f"refusing --target {args.target}: {why}", file=sys.stderr)
        return 1
    outcome = external_review.review_outcome(
        text,
        args.kind,
        command=command,
        workdir=repo,
        options=external_review.ReviewerOptions.from_settings(resolved),
    )
    result = outcome.review
    if result is None:  # a skip is never an approval: no verdict is printed, no review.md written
        message = f"external reviewer {command!r} skipped ({outcome.reason})"
        print(f"{message}: {outcome.detail}" if outcome.detail else message, file=sys.stderr)
        return 0 if outcome.reason == "missing-cli" else 1
    print(_render(result))
    if args.out:
        try:
            # Again: the review can run for minutes, and O_NOFOLLOW covers only the last component.
            if _symlink_below_repo(args.out, repo) is not None:
                raise OSError(errno.ELOOP, "a parent directory became a symlink during the review")
            _write_review_md(args.out, str(args.target), result, args.iteration)
        except OSError as exc:  # includes a symlink put there while the review ran
            print(f"could not write {args.out}: {exc}", file=sys.stderr)
            return 1
        except ImportError:
            print(f"could not write {args.out}: PyYAML is not installed", file=sys.stderr)
            return 1
        print(f"wrote {args.out}")
    return 0 if result["verdict"] == "approve" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
