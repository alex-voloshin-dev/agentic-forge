"""Skill name validation per the Agent Skills standard (agentskills.io/specification).

Rules:
- 1-64 characters
- lowercase ascii letters, digits, and hyphens only
- must not start or end with a hyphen
- must not contain consecutive hyphens
- must match the parent directory name
"""

from __future__ import annotations

import re

__all__ = ["NAME_MAX_LEN", "is_valid_name", "validate_name"]

NAME_MAX_LEN = 64
_ALLOWED = re.compile(r"^[a-z0-9-]+$")


def validate_name(name: str, *, dir_name: str | None = None) -> list[str]:
    """Return a list of human-readable errors. Empty list means valid."""
    errors: list[str] = []

    if not name:
        return ["name is empty"]

    if len(name) > NAME_MAX_LEN:
        errors.append(f"name exceeds {NAME_MAX_LEN} characters (got {len(name)})")
    if not _ALLOWED.match(name):
        errors.append("name may only contain lowercase letters, digits, and hyphens")
    if name.startswith("-") or name.endswith("-"):
        errors.append("name must not start or end with a hyphen")
    if "--" in name:
        errors.append("name must not contain consecutive hyphens")
    if dir_name is not None and name != dir_name:
        errors.append(f"name '{name}' must match parent directory name '{dir_name}'")

    return errors


def is_valid_name(name: str, *, dir_name: str | None = None) -> bool:
    return not validate_name(name, dir_name=dir_name)
