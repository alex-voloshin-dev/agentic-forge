"""Load and validate a component's evals.json against the project schema.

evals.json is the single machine-readable source of a component's readiness contract:
its identity, purpose, trigger examples, and numeric thresholds (definition of done).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

# plugin/lib/agentic_forge/evals.py -> plugin/schemas/evals.schema.json
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "evals.schema.json"


class EvalsError(ValueError):
    """Raised when evals.json cannot be read or parsed."""


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return data


def load_evals(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalsError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvalsError(f"{path}: top-level value must be an object")
    return data


def validate_evals(data: dict[str, Any], *, schema: dict[str, Any] | None = None) -> list[str]:
    """Return a list of schema-violation messages. Empty list means valid."""
    validator = jsonschema.Draft7Validator(schema or _schema())
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{location}: {err.message}")
    return errors
