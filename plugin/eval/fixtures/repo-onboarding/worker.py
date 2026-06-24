"""Background worker — processes jobs off an in-memory queue."""

import queue

_q: "queue.Queue[tuple[str, str]]" = queue.Queue()


def enqueue(kind: str, item_id: str) -> None:
    _q.put((kind, item_id))


def run() -> None:
    while True:
        kind, item_id = _q.get()
        # NOTE: no retry or backoff on failure — a job that raises is lost.
        process(kind, item_id)


def process(kind: str, item_id: str) -> None:
    ...
