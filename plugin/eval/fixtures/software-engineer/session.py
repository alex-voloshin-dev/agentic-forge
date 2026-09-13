"""Auth session handling."""

from __future__ import annotations

import secrets

SESSION_TTL_SECONDS = 1800


def new_session_id() -> str:
    return secrets.token_urlsafe(32)
