"""Port parsing helpers."""

from __future__ import annotations


def parse_port(text: str) -> int:
    """Parse ``text`` as a TCP port in the range 1-65535."""
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError(f"not a port: {text!r}") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"port out of range: {value}")
    return value
