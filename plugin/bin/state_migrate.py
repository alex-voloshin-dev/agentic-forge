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
* leaves the committed `config.json` alone — that file is the repository's, not runtime state.

    python plugin/bin/state_migrate.py --repo .            # dry run: report what would move
    python plugin/bin/state_migrate.py --repo . --apply    # merge, verify, remove the legacy dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "lib"))

from agentic_forge import diagnostics  # noqa: E402

# Runtime state files, and whether they are line-oriented (mergeable) or a single JSON document
# (last-writer-wins: a schedule cursor or a queue has no meaningful concatenation).
_JSONL = ("diagnostics.jsonl", "audit.jsonl")
_JSON_DOC = ("schedule-state.json", "pr-watch-queue.json")
_KEEP_IN_REPO = ("config.json",)  # committed configuration — never runtime state


def _merge_jsonl(legacy: Path, target: Path) -> tuple[int, int]:
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
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            if existing and not target.read_text(encoding="utf-8").endswith("\n"):
                handle.write("\n")
            handle.write("\n".join(added) + "\n")
    return len(added), duplicates


def plan(repo: Path) -> tuple[Path, Path, list[str]]:
    """Return (legacy dir, resolved state root, the state files present in the legacy dir)."""
    root = diagnostics.main_repo_root(repo)
    legacy = root / diagnostics.STATE_DIRNAME
    resolved = diagnostics.state_root(repo)
    if not legacy.is_dir():
        return legacy, resolved, []
    present = [
        p.name
        for p in sorted(legacy.iterdir())
        if p.is_file() and p.name not in _KEEP_IN_REPO and p.name in _JSONL + _JSON_DOC
    ]
    return legacy, resolved, present


def migrate(repo: Path, *, apply: bool) -> int:
    legacy, resolved, present = plan(repo)
    if resolved == legacy:
        print("state.in_repo is on — the repo IS the state root; nothing to migrate.")
        return 0
    if not present:
        print(f"nothing to migrate: no legacy state files under {legacy}")
        return 0

    print(f"legacy : {legacy}")
    print(f"target : {resolved}")
    for name in present:
        source = legacy / name
        if name in _JSONL:
            text = source.read_text(encoding="utf-8")
            lines = sum(1 for line in text.splitlines() if line.strip())
            print(f"  {name}: {lines} record(s), {source.stat().st_size} bytes -> merge")
        else:
            print(f"  {name}: {source.stat().st_size} bytes -> keep the NEWER of the two")
    if not apply:
        print("\ndry run — re-run with --apply to merge and remove the legacy directory")
        return 0

    for name in present:
        source, target = legacy / name, resolved / name
        if name in _JSONL:
            added, duplicates = _merge_jsonl(source, target)
            print(f"  {name}: +{added} record(s), {duplicates} already present")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or source.stat().st_mtime > target.stat().st_mtime:
                json.loads(source.read_text(encoding="utf-8"))  # validate before overwriting
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"  {name}: replaced (legacy was newer)")
            else:
                print(f"  {name}: kept the newer copy already at the target")
        source.unlink()

    remaining = sorted(p.name for p in legacy.iterdir()) if legacy.is_dir() else []
    if not remaining:
        legacy.rmdir()
        print(f"\nremoved {legacy}")
    else:
        print(f"\nkept {legacy} — it still holds: {', '.join(remaining)}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Merge legacy in-repo state into the state root.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true", help="perform the merge (default: dry run)")
    args = parser.parse_args(argv[1:])
    try:
        return migrate(args.repo, apply=args.apply)
    except json.JSONDecodeError as exc:
        print(f"error: a state file has an unparseable line, nothing was removed: {exc}",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
