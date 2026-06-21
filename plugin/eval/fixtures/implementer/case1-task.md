# Task T1 (from plan.md)

Add a `slugify(text)` helper to `lib/text.py` that:
- lowercases the text,
- trims leading/trailing whitespace,
- replaces runs of internal whitespace with a single hyphen.

Add a unit test for it.

## Current state of lib/text.py

    """Text helpers."""


    def truncate(text, length):
        return text[:length]

The module exists with one helper; add `slugify` alongside it and a test under `tests/`.
