#!/usr/bin/env python3
"""Merge a repo's legacy in-repo state into its user-level state root (ADR 0072/0080).

Before 2026.7.10 the plugin wrote `diagnostics.jsonl`, `audit.jsonl`, `schedule-state.json` and
`pr-watch-queue.json` into `<repo>/.agentic-forge/`. They now live under
`~/.agentic-forge/state/<repo-slug>/`, where the slug is the repo's name plus a digest of its
absolute path — **which nobody guesses**. A hand migration into the guessed name fails silently in
both directions at once: the resolved root has no file, so reads fall back to the legacy path, so
the in-repo directory stays alive *and* the moved history is orphaned. Field-reported after
exactly that happened.

This CLI does the migration the way it has to be done:

* **Concatenates** the JSONL logs rather than moving them — a still-running old install keeps
  appending to the legacy path while you migrate (the field report found 102 records that landed
  after the copy), and records already at the destination must survive too;
* **de-duplicates** identical lines, so re-running it is safe and a partial hand-migration merges
  cleanly instead of doubling;
* **validates** every line parses as JSON before it removes anything;
* leaves the committed `config.json` alone — that file is the repository's, not runtime state;
* **does not follow a symlink**, at a legacy name, a legacy directory that is one, or a target: the
  first would copy another file's content into your state, and the last would remove the legacy file
  after merging into something the readers then refuse. What is skipped is named and kept, and the
  exit code is 1 if that left a target unmerged (ADR 0102);
* deletes a legacy `notices.json`, which holds only per-session markers;
* names only its own files, since it may be run by a model: a repo chooses its other filenames.

    python plugin/bin/state_migrate.py --repo .            # dry run: report what would move
    python plugin/bin/state_migrate.py --repo . --apply    # merge, verify, remove the legacy dir
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))

from agentic_forge import diagnostics, state_io  # noqa: E402

# Runtime state files, and whether they are line-oriented (mergeable) or a single JSON document
# (last-writer-wins: a schedule cursor or a queue has no meaningful concatenation).
_JSONL = ("diagnostics.jsonl", "audit.jsonl")
_JSON_DOC = ("schedule-state.json", "pr-watch-queue.json")
_DISPOSABLE = (diagnostics.NOTICES_FILE,)  # per-session markers: nothing to keep


def _merge_jsonl(legacy: Path, target: Path, anchor: Path) -> tuple[int, int]:
    """Append legacy lines missing from ``target``. Returns (added, skipped_duplicates)."""
    existing = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    seen = set(existing)
    added, duplicates = [], 0
    for line in legacy.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        json.loads(line)  # validate before anything is removed; a bad line aborts the migration
        if line in seen:
            duplicates += 1
            continue
        seen.add(line)
        added.append(line)
    if added:
        gap = existing and not target.read_text(encoding="utf-8").endswith("\n")
        state_io.append_text(target, ("\n" if gap else "") + "\n".join(added) + "\n", anchor=anchor)
    return len(added), duplicates


def plan(repo: Path) -> tuple[Path, Path, list[str]]:
    """Return (legacy dir, resolved state root, the state files present in the legacy dir)."""
    root = diagnostics.main_repo_root(repo)
    legacy = root / diagnostics.STATE_DIRNAME
    resolved = diagnostics.state_root(repo)
    present = sorted(
        name for name in diagnostics.LEGACY_STATE_FILES if state_io.readable(legacy / name, root)
    )
    return legacy, resolved, present


def _print_symlinks(legacy: Path) -> None:
    """Say what is not being migrated. A link's target is another file, not this repo's state."""
    if legacy.is_symlink():
        print(f"not following {legacy}: it is a symlink")
        return
    for name in diagnostics.LEGACY_STATE_FILES:
        if (legacy / name).is_symlink():
            print(f"not following {legacy / name}: it is a symlink")


def _print_archive(legacy: Path) -> None:
    if (legacy / "archive").is_dir():
        print(f"  archive/: rotated logs, not moved -> stays in {legacy}")


def _target_problem(target: Path, anchor: Path) -> str:
    """Why ``target`` must not be merged into, or "". Asked before it is read or compared: a link
    there would be followed by the merge and then refused by every reader, with the legacy file
    already deleted."""
    link = state_io.symlink_below(target, anchor)
    if link is not None:
        return f"{link} is a symlink"
    if os.path.lexists(target) and not state_io.readable(target, anchor):
        return f"{target} is not a regular file"
    return ""


def migrate(repo: Path, *, apply: bool, handled: list[str]) -> int:
    """``handled`` receives each file's name as it is reached, so that an error can name it."""
    legacy, resolved, present = plan(repo)
    if resolved == legacy:
        print("state.in_repo is on — the repo IS the state root; nothing to migrate.")
        return 0
    _print_symlinks(legacy)
    if not present:
        print(f"nothing to migrate: no legacy state files under {legacy}")
        return 0

    print(f"legacy : {legacy}")
    print(f"target : {resolved}")
    anchor = diagnostics.state_anchor(repo)
    for name in present:
        handled.append(name)
        source = legacy / name
        problem = "" if name in _DISPOSABLE else _target_problem(resolved / name, anchor)
        if problem:
            print(f"  {name}: skipped, {problem}; {source} stays")
        elif name in _DISPOSABLE:
            print(f"  {name}: per-session markers -> delete")
        elif name in _JSONL:
            text = source.read_text(encoding="utf-8")
            lines = sum(1 for line in text.splitlines() if line.strip())
            print(f"  {name}: {lines} record(s), {source.stat().st_size} bytes -> merge")
        else:
            print(f"  {name}: {source.stat().st_size} bytes -> keep the NEWER of the two")
    _print_archive(legacy)
    if not apply:
        print("\ndry run — re-run with --apply to merge these and remove them from the repo")
        return 0

    skipped = 0
    for name in present:
        handled.append(name)
        source, target = legacy / name, resolved / name
        if name in _DISPOSABLE:
            source.unlink()
            print(f"  {name}: deleted")
            continue
        if _target_problem(target, anchor):
            skipped += 1
            continue  # named above
        if name in _JSONL:
            added, duplicates = _merge_jsonl(source, target, anchor)
            print(f"  {name}: +{added} record(s), {duplicates} already present")
        else:
            if not target.is_file() or source.stat().st_mtime > target.stat().st_mtime:
                text = source.read_text(encoding="utf-8")
                json.loads(text)  # validate before overwriting
                state_io.write_text(target, text, anchor=anchor)
                print(f"  {name}: replaced (legacy was newer)")
            else:
                print(f"  {name}: kept the newer copy already at the target")
        source.unlink()

    remaining = len(list(legacy.iterdir())) if legacy.is_dir() else 0
    if not remaining:
        legacy.rmdir()
        print(f"\nremoved {legacy}")
    else:
        print(f"\nkept {legacy} — it still holds {remaining} entries")
    return 1 if skipped else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Merge legacy in-repo state into the state root.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true", help="perform the merge (default: dry run)")
    args = parser.parse_args(argv[1:])
    handled: list[str] = []
    try:
        return migrate(args.repo, apply=args.apply, handled=handled)
    except ValueError as exc:  # not JSON, or not UTF-8. Its text could quote the file.
        name = handled[-1] if handled else "a state file"
        print(f"error: {name} cannot be parsed ({type(exc).__name__}): it and the files after it "
              "stay in the repo; any reported above as merged or deleted have gone from it",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
