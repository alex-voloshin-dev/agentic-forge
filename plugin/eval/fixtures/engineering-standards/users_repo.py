"""A tiny users repository over sqlite3 (engineering-standards Tier-2 eval fixture target)."""

from __future__ import annotations

import sqlite3


def connect() -> sqlite3.Connection:
    """An in-memory database with the users table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)")
    return conn


def add_user(conn: sqlite3.Connection, name: str, email: str) -> int:
    """Insert a user and return its id."""
    cur = conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    return int(cur.lastrowid or 0)
