"""The run coordinator: one job per verify run (``verify.run_day``).

1. Checks the day is ready (rule run and AI run DONE: every duplicate level
   ran first, so only unique items are verified), clears the day's old
   verdicts and their checkpoints, and counts the unique items.
2. Runs Llama Guard over all of them in one phase, so one model stays on
   the GPU (a 4 GB card can't hold the guard and the main model at once).
3. Queues one ``verify.item`` job per item, with its guard verdict.

A day with no unique item finishes at once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import logging
from typing import Any, Protocol

from ai_api.guard import llama_guard
from ai_api.guard import sanitize
from ai_api.verify import graph as graph_lib
from ai_api.verify import prompts
from ai_api.verify import repository

_log = logging.getLogger(__name__)


class Enqueuer(Protocol):
    """Queues one item's graph (``worker.queue.Queue``)."""

    async def verify_item(
        self, run_id: int, news_id: int, guard: dict[str, Any]
    ) -> None:
        """Queues the job."""
        ...


class ThreadCleaner(Protocol):
    """Deletes old checkpoint threads (a LangGraph checkpointer)."""

    async def adelete_thread(self, thread_id: str) -> None:
        """Deletes one thread."""
        ...


class Coordinator:
    """Starts a verify run (see the module docstring)."""

    def __init__(
        self,
        repo: repository.VerifyRepository,
        deps: graph_lib.Deps,
        guard: llama_guard.Guard,
        queue: Enqueuer,
        saver: ThreadCleaner | None,
        concurrency: int = 2,
    ) -> None:
        """Wires the coordinator.

        Args:
            repo: Reads and writes.
            deps: The graph's dependencies (events, finishing a run).
            guard: Llama Guard (off when it has no model).
            queue: Where the item jobs go.
            saver: The checkpointer, to delete the day's old threads.
            concurrency: Guard calls in flight.
        """
        self._repo = repo
        self._deps = deps
        self._guard = guard
        self._queue = queue
        self._saver = saver
        self._concurrency = concurrency

    async def _publish(self, run_id: int, kind: str, data: dict) -> None:
        if self._deps.events is not None:
            await self._deps.events.publish(run_id, kind, data)

    async def _guard_all(self, ids: Sequence[int]) -> dict[int, dict]:
        gate = asyncio.Semaphore(self._concurrency)

        async def one(news_id: int) -> tuple[int, dict]:
            async with gate:
                row = await self._repo.load_item(news_id)
                if row is None or not self._guard.enabled:
                    return news_id, llama_guard.Verdict(ran=False).to_json()
                clean = sanitize.sanitize(row["headline"], row["body"])
                found = await self._guard.check_news(clean.headline, clean.body)
                return news_id, found.to_json()

        return dict(await asyncio.gather(*(one(i) for i in ids)))

    async def run(self, run_id: int, model: str) -> int:
        """Starts the run.

        Args:
            run_id: A QUEUED ``ai.verify_run``.
            model: The judge's alias (recorded on the run).

        Returns:
            How many item jobs were queued.
        """
        try:
            day, ids, threads = await self._repo.start_run(
                run_id, model, prompts.PROMPT_VERSION
            )
        except repository.NotReadyError as e:
            _log.warning("verify run %s: %s", run_id, e)
            await self._repo.fail_run(run_id, str(e))
            await self._publish(run_id, "run.failed", {"error": str(e)})
            return 0
        if self._saver is not None:
            for thread in threads:
                try:
                    await self._saver.adelete_thread(thread)
                except Exception as e:  # noqa: BLE001 - cleanup only.
                    _log.warning("could not delete thread %s: %r", thread, e)
        await self._publish(
            run_id,
            "run.started",
            {"total": len(ids), "feed_date": day.isoformat()},
        )
        _log.info("verify run %s (%s): %d unique items", run_id, day, len(ids))
        if not ids:
            run = await self._repo.finish_run(run_id)
            if run is not None:
                await self._publish(
                    run_id, "run.done", graph_lib.run_summary(run)
                )
            return 0
        guard = await self._guard_all(ids)
        unsafe = sum(1 for g in guard.values() if g["ran"] and not g["safe"])
        _log.info("verify run %s: Llama Guard flagged %d", run_id, unsafe)
        for news_id in ids:
            await self._queue.verify_item(run_id, news_id, guard[news_id])
        return len(ids)
