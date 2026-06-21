"""User lookup endpoint (security review fixture: clean — parameterized + validated)."""

import re

_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def find_user(db, request):
    name = request.query["name"]
    if not _NAME.match(name):
        raise ValueError("invalid name")
    # Safe: bound parameter, no string interpolation.
    return db.execute("SELECT id, email FROM users WHERE name = ?", (name,)).fetchall()
