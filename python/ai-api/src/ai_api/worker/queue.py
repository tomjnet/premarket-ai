"""The job queue: taskiq on a Redis Stream (consumer group ``ai-worker``).

Changed from the plan's arq (2026-09-26): arq pins redis-py below 6, and
RedisVL (dedup L3) needs 6.3 or newer, so both can't be in one image.
taskiq-redis's ``RedisStreamBroker`` keeps the design: jobs in Redis, a
consumer group shared by every ``ai-worker`` replica
(``podman compose up --scale ai-worker=3``), and a job is acknowledged
only after it ran, so a crashed worker's job is claimed again by another
one after ``IDLE_TIMEOUT_MS``.

The API and the CLI only enqueue (by task name); the worker registers the
tasks (``worker.app``).
"""

from __future__ import annotations

from typing import Any
import urllib.parse

from taskiq import kicker
import taskiq_redis

QUEUE = "premarket:verify"
GROUP = "ai-worker"
RUN_DAY = "verify.run_day"
VERIFY_ITEM = "verify.item"
RESUME = "verify.resume"
# A job unacknowledged this long (its worker died) is run again elsewhere.
# Longer than the slowest job: a judge call waits up to LLM_TIMEOUT_S.
IDLE_TIMEOUT_MS = 30 * 60 * 1000


def redis_url(host: str, password: str, port: int = 6379) -> str:
    """``redis://:password@host:port/0`` with the password quoted."""
    return f"redis://:{urllib.parse.quote(password, safe='')}@{host}:{port}/0"


def make_broker(host: str, password: str) -> taskiq_redis.RedisStreamBroker:
    """The broker (the worker reads one job at a time per fetch).

    Args:
        host: Redis host.
        password: Redis password.

    Returns:
        The broker; call ``startup()`` before enqueueing.
    """
    return taskiq_redis.RedisStreamBroker(
        redis_url(host, password),
        queue_name=QUEUE,
        consumer_group_name=GROUP,
        idle_timeout=IDLE_TIMEOUT_MS,
        # Fetch one job at a time: a fetched job is unacknowledged until it
        # ran, and must not wait in memory long enough to be re-claimed.
        xread_count=1,
        maxlen=10_000,
    )


class Queue:
    """Enqueues verification jobs (the API and ``ai-api verify``)."""

    def __init__(self, broker: Any) -> None:
        """Uses a started (or startable) broker."""
        self._broker = broker

    async def start(self) -> None:
        """Connects the broker."""
        await self._broker.startup()

    async def stop(self) -> None:
        """Disconnects the broker."""
        await self._broker.shutdown()

    async def _kick(self, task: str, **kwargs: Any) -> None:
        await kicker.AsyncKicker(task, self._broker, {}).kiq(**kwargs)

    async def run_day(self, run_id: int) -> None:
        """Queues the coordinator of a verify run."""
        await self._kick(RUN_DAY, run_id=run_id)

    async def verify_item(
        self, run_id: int, news_id: int, guard: dict[str, Any]
    ) -> None:
        """Queues one item's graph."""
        await self._kick(
            VERIFY_ITEM, run_id=run_id, news_id=news_id, guard=guard
        )

    async def resume(
        self, run_id: int, news_id: int, thread_id: str, decision: dict
    ) -> None:
        """Queues the resume of a graph waiting for review."""
        await self._kick(
            RESUME,
            run_id=run_id,
            news_id=news_id,
            thread_id=thread_id,
            decision=decision,
        )
