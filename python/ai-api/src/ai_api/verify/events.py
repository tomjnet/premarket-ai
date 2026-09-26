"""Run progress as Redis Streams: ``run:{id}:events``.

The coordinator and the workers append events; ``GET /runs/{id}/events``
forwards them to the browser as server-sent events. A stream (unlike
Pub/Sub) keeps its events, so a client that reconnects with
``Last-Event-ID`` gets what it missed. Each stream expires a day after its
last event.

Events (``kind`` and its data):

- ``run.started``: ``total`` items queued.
- ``item``: one item verified: ``news_id``, ``vendor_item_id``,
  ``verdict``, ``confidence``, ``review`` (true when it waits for an
  analyst), plus the run's ``done`` / ``total``.
- ``review``: an analyst decided (``news_id``, ``status``, ``verdict``).
- ``run.done`` / ``run.failed``: the run's final counts, or the error.
"""

from __future__ import annotations

import json
from typing import Any

from redis import asyncio as aioredis

TTL_S = 24 * 3600
_MAX_LEN = 5000
FINAL_KINDS = frozenset({"run.done", "run.failed"})


def stream_key(run_id: int) -> str:
    """The Redis key of a run's stream."""
    return f"run:{run_id}:events"


class RunEvents:
    """Appends and reads run events (a decoded Redis client)."""

    def __init__(self, redis: aioredis.Redis) -> None:
        """Uses ``redis`` (decode_responses=True)."""
        self._redis = redis

    async def publish(
        self, run_id: int, kind: str, data: dict[str, Any]
    ) -> str:
        """Appends one event; returns its stream id."""
        key = stream_key(run_id)
        event_id = await self._redis.xadd(
            key,
            {"kind": kind, "data": json.dumps(data)},
            maxlen=_MAX_LEN,
            approximate=True,
        )
        await self._redis.expire(key, TTL_S)
        return event_id

    async def read(
        self, run_id: int, after: str = "0", block_ms: int = 15_000
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Events after the id ``after`` (``0``: from the start).

        Args:
            run_id: The run.
            after: The last id the client has.
            block_ms: How long to wait for a new event (0: don't wait).

        Returns:
            (id, kind, data) triples, oldest first; empty on a timeout.
        """
        found = await self._redis.xread(
            {stream_key(run_id): after},
            count=200,
            block=block_ms if block_ms > 0 else None,
        )
        events = []
        for _, entries in found or []:
            for event_id, fields in entries:
                events.append(
                    (event_id, fields["kind"], json.loads(fields["data"]))
                )
        return events
