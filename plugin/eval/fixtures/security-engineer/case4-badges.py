"""Profile badges (security review fixture).

A user sets a display name once; a nightly job renders a PNG badge for every user and
uploads it to object storage.
"""

from __future__ import annotations

import html
import logging
import os
import subprocess

import requests

log = logging.getLogger("badges")

STORAGE_URL = "https://storage.example.com/v1/badges"
STORAGE_KEY = os.environ["BADGE_STORAGE_KEY"]  # write-scoped key for the badges bucket


def save_display_name(db, user_id: int, form: dict[str, str]) -> None:
    """Profile form handler: store the user's display name.

    The name is shown on the public profile page, so it is HTML-escaped before it is stored.
    """
    name = form["display_name"][:64]  # user-supplied
    safe_name = html.escape(name, quote=True)
    db.execute("UPDATE users SET display_name = ? WHERE id = ?", (safe_name, user_id))


def render_badge(db, user_id: int, out_dir: str) -> str:
    """Nightly job: render the stored display name into a PNG with ImageMagick."""
    (label,) = db.execute(
        "SELECT display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    out_path = os.path.join(out_dir, f"{user_id}.png")
    # label was escaped when it was saved, so it is safe to interpolate here
    cmd = f'convert -size 240x40 xc:white -annotate +10+28 "{label}" {out_path}'
    subprocess.run(cmd, shell=True, check=True)
    return out_path


def upload_badge(user_id: int, path: str) -> bool:
    """Upload a rendered badge. Failures are logged and retried by the next nightly run."""
    url = f"{STORAGE_URL}/{user_id}.png?key={STORAGE_KEY}"
    try:
        with open(path, "rb") as fh:
            resp = requests.put(url, data=fh, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("badge upload failed for user %s: %s", user_id, exc)
        return False
    return True


def nightly(db, out_dir: str) -> None:
    for (user_id,) in db.execute("SELECT id FROM users").fetchall():
        upload_badge(user_id, render_badge(db, user_id, out_dir))
