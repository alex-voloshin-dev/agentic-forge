"""Report downloads (security review fixture).

Signed-in users list their reports, sorted by a column they choose, and download one as a
file. Callers have already authenticated the request; ``request.user_id`` is the session's
user, never a client-supplied value.
"""

from __future__ import annotations

import hashlib
import random
import subprocess
from pathlib import Path

REPORT_ROOT = Path("/srv/reports").resolve()

# Allowlist: the client's sort key maps to a fixed SQL fragment; the client's text never
# reaches the query.
_SORT_COLUMNS = {"name": "name", "created": "created_at", "size": "size_bytes"}


def list_reports(db, request) -> list[tuple]:
    sort = request.query.get("sort", "created")
    column = _SORT_COLUMNS.get(sort)
    if column is None:
        raise ValueError("unsupported sort key")
    direction = "DESC" if request.query.get("desc") == "1" else "ASC"
    sql = f"SELECT id, name, size_bytes FROM reports WHERE owner_id = ? ORDER BY {column} {direction}"
    return db.execute(sql, (request.user_id,)).fetchall()


def report_path(request) -> Path:
    """Resolve the requested file inside the caller's own report directory."""
    user_dir = (REPORT_ROOT / str(int(request.user_id))).resolve()
    target = (user_dir / request.query["file"]).resolve()
    if not target.is_relative_to(user_dir):
        raise PermissionError("path escapes the report directory")
    if not target.is_file():
        raise FileNotFoundError(target.name)
    return target


def etag(path: Path) -> str:
    """HTTP cache validator for a report file (not a security control)."""
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def retry_delay(attempt: int) -> float:
    """Back-off with jitter for the archive job; spreads retries, nothing more."""
    return min(30.0, 2.0**attempt) * random.uniform(0.5, 1.0)


def archive(request, names: list[str], out: Path) -> None:
    """Bundle several of the caller's reports into one tarball at ``out``, a temporary path
    the server generates (never client-supplied)."""
    files = [str(report_path_for(request, n)) for n in names]
    subprocess.run(["tar", "-czf", str(out), "--", *files], check=True)


def report_path_for(request, name: str) -> Path:
    """report_path for an explicit file name (same containment check)."""
    user_dir = (REPORT_ROOT / str(int(request.user_id))).resolve()
    target = (user_dir / name).resolve()
    if not target.is_relative_to(user_dir):
        raise PermissionError("path escapes the report directory")
    return target
