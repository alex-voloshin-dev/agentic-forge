"""agentic-forge shared library.

Importable helpers used by skill scripts, hooks, the Tier-0 validator, and the
eval-harness. Keep this package dependency-light (pyyaml, jsonschema) and fully
unit-tested.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
