"""Shared helpers for the dev/ eval-runner CLIs (run_agent/skill/tier1_evals)."""

from __future__ import annotations

import os
import sys

_API_KEY_WARNING = (
    "warning: ANTHROPIC_API_KEY is set; the claude CLI uses it before the subscription token. "
    "Unset it to bill this run to your Claude subscription."
)


def warn_if_api_key_set(runner: str) -> None:
    """Warn on stderr when the ``claude`` runner is chosen but ``ANTHROPIC_API_KEY`` is set — it
    takes precedence over the subscription token, so the run would bill per token."""
    if runner == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        print(_API_KEY_WARNING, file=sys.stderr)
