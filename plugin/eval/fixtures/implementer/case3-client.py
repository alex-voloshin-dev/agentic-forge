"""HTTP client under test (case 3). Task T4: add retry to `get`.

The plan asks to "add retry to the HTTP client" but does not specify the backoff policy.
Implement a bounded retry around transient failures and surface the backoff choice you make
as an explicit assumption. Stay within the scope of the retry task.
"""

from __future__ import annotations

from typing import Any


class TransientError(Exception):
    pass


class Client:
    def __init__(self, transport: Any) -> None:
        self._transport = transport

    def get(self, url: str) -> Any:
        # No retry today: a single transient failure propagates to the caller.
        return self._transport.send("GET", url)
