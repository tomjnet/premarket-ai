"""The ``ai-worker`` process: taskiq tasks around the verify graph.

Run by the taskiq CLI with this module's broker factory::

    taskiq worker ai_api.worker.app:build_broker --workers 1 \
        --max-async-tasks 2 --ack-type when_executed

Tasks (enqueued by name, see ``worker.queue``):

- ``verify.run_day(run_id)``: the coordinator.
- ``verify.item(run_id, news_id, guard)``: one item's graph. A job that
  already stored its verdict (a redelivered job) does nothing; a graph that
  fails twice is recorded as FAILED and counted, so the run still ends.
- ``verify.resume(run_id, news_id, thread_id, decision)``: resumes a graph
  waiting in ``review`` with the analyst's (or the expiry's) decision.

Everything the tasks share (pools, the MCP client, the models, the compiled
graph) is built once per process at worker startup.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
from typing import Any

from langchain_mcp_adapters import client as mcp_client
from langgraph import types as lg_types
from langgraph.checkpoint.postgres import aio as pg_checkpoint
from psycopg import rows
from psycopg_pool import AsyncConnectionPool
from redis import asyncio as aioredis
import taskiq

from ai_api import config
from ai_api.guard import llama_guard
from ai_api.llm import budget
from ai_api.llm import factory
from ai_api.llm import tracing
from ai_api.rag import universe
from ai_api.verify import coordinator
from ai_api.verify import events
from ai_api.verify import graph as graph_lib
from ai_api.verify import judge as judge_lib
from ai_api.verify import repository
from ai_api.verify import tools as tools_lib
from ai_api.worker import queue

_log = logging.getLogger(__name__)
_ATTEMPTS = 2
_GUARD_TOKENS = 20


def _baseline(settings: config.VerifySettings) -> Any:
    """The classic ML baseline, or None (off, or torch not installed)."""
    if not settings.ml_enabled:
        return None
    try:
        import torch  # noqa: F401, PLC0415 - only in the worker image.
    except ImportError:
        _log.info("torch isn't installed: classic ML baseline off")
        return None
    from ai_api.ml import models  # noqa: PLC0415

    baseline = models.Baseline(settings.ml_model_dir)
    if not baseline.trained:
        _log.info(
            "no trained DistilBERT: FinBERT only (make -C python ml-train)"
        )
    return baseline


@dataclasses.dataclass
class _Runtime:
    """What the tasks share in one worker process."""

    pool: AsyncConnectionPool
    checkpoint_pool: AsyncConnectionPool
    redis: aioredis.Redis
    mcp: mcp_client.MultiServerMCPClient
    deps: graph_lib.Deps
    graph: Any
    coordinator: coordinator.Coordinator
    queue: queue.Queue
    tracer: tracing.Tracer


class Worker:
    """The tasks, bound to the process's shared objects."""

    def __init__(self, settings: config.VerifySettings, broker: Any) -> None:
        """Keeps the settings; ``start`` opens the connections."""
        self._settings = settings
        self._broker = broker
        self._runtime: _Runtime | None = None

    @property
    def runtime(self) -> _Runtime:
        """The shared objects (after ``start``)."""
        if self._runtime is None:
            raise RuntimeError("the worker hasn't started")
        return self._runtime

    async def start(self, state: taskiq.TaskiqState) -> None:
        """Opens the pools and clients and compiles the graph."""
        del state
        settings = self._settings
        llm = settings.llm
        pool = AsyncConnectionPool(
            settings.database.dsn(application="ai-worker"),
            min_size=1,
            max_size=6,
            timeout=10,
            check=AsyncConnectionPool.check_connection,
            open=False,
            kwargs={"autocommit": True},
        )
        await pool.open(wait=True)
        # The checkpointer's own pool: dict rows, no prepared statements,
        # and its tables in the `graph` schema.
        checkpoint_pool = AsyncConnectionPool(
            settings.database.dsn(search_path="graph", application="ai-worker"),
            min_size=1,
            max_size=6,
            timeout=10,
            check=AsyncConnectionPool.check_connection,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": rows.dict_row,
            },
        )
        await checkpoint_pool.open(wait=True)
        saver = pg_checkpoint.AsyncPostgresSaver(checkpoint_pool)
        redis = aioredis.Redis(
            host=settings.redis_host,
            password=settings.redis_password,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=5,
        )
        cloud = None
        if settings.judge_cloud_model:
            cloud = factory.chat_model(
                llm,
                model=settings.judge_cloud_model,
                max_tokens=800,
                response_headers=True,
            )
        tracer = tracing.Tracer(settings.tracing)
        repo = repository.VerifyRepository(pool)
        deps = graph_lib.Deps(
            repo=repo,
            judge=judge_lib.Judge(
                factory.chat_model(llm, max_tokens=800),
                llm.main_model,
                cloud=cloud,
                cloud_name=settings.judge_cloud_model,
                budget=budget.CloudBudget(redis, settings.monthly_budget_usd),
            ),
            tracer=tracer,
            events=events.RunEvents(redis),
            ml=_baseline(settings),
            universe_size=len(universe.load(settings.config_dir)),
            min_confidence=settings.hitl_confidence_min,
            guard_routes=settings.guard_news_review,
        )
        guard = llama_guard.Guard(
            factory.chat_model(
                llm, model=llm.guard_model, max_tokens=_GUARD_TOKENS
            )
            if settings.llama_guard
            else None
        )
        jobs = queue.Queue(self._broker)
        self._runtime = _Runtime(
            pool=pool,
            checkpoint_pool=checkpoint_pool,
            redis=redis,
            mcp=mcp_client.MultiServerMCPClient(
                {
                    tools_lib.SERVER: {
                        "transport": "streamable_http",
                        "url": settings.mcp_url,
                        "headers": {
                            "Authorization": f"Bearer {settings.mcp_token}"
                        },
                        "timeout": 30,
                        "sse_read_timeout": 120,
                    }
                }
            ),
            deps=deps,
            graph=graph_lib.build(deps, saver),
            coordinator=coordinator.Coordinator(
                repo, deps, guard, jobs, saver, llm.concurrency
            ),
            queue=jobs,
            tracer=tracer,
        )
        _log.info(
            "ai-worker ready: judge %s, cloud %s, guard %s, classic ML %s",
            llm.main_model,
            settings.judge_cloud_model or "off",
            llm.guard_model if settings.llama_guard else "off",
            "on" if deps.ml is not None else "off",
        )

    async def stop(self, state: taskiq.TaskiqState) -> None:
        """Closes the pools and clients."""
        del state
        if self._runtime is None:
            return
        self._runtime.tracer.flush()
        await self._runtime.pool.close()
        await self._runtime.checkpoint_pool.close()
        await self._runtime.redis.aclose()

    async def run_day(self, run_id: int) -> int:
        """The coordinator job; returns the number of items queued."""
        runtime = self.runtime
        return await runtime.coordinator.run(
            run_id, self._settings.llm.main_model
        )

    async def _invoke(self, payload: Any, config: dict[str, Any]) -> None:
        """Runs the graph with an MCP session (or unavailable tools)."""
        runtime = self.runtime
        async with contextlib.AsyncExitStack() as stack:
            try:
                session = await stack.enter_async_context(
                    runtime.mcp.session(tools_lib.SERVER)
                )
                tools: tools_lib.Tools = tools_lib.McpTools(session)
            except Exception as e:  # noqa: BLE001 - verify without tools.
                _log.warning("MCP server unavailable: %r", e)
                tools = tools_lib.UnavailableTools(repr(e))
            await runtime.graph.ainvoke(
                payload, config, context=graph_lib.Context(tools)
            )

    async def verify_item(
        self, run_id: int, news_id: int, guard: dict[str, Any]
    ) -> str:
        """One item's graph (see the module docstring).

        Returns:
            ``done``, ``review``, ``skipped`` (already stored) or
            ``failed``.
        """
        runtime = self.runtime
        thread = graph_lib.thread_id(run_id, news_id)
        config = {"configurable": {"thread_id": thread}}
        snapshot = await runtime.graph.aget_state(config)
        if snapshot.values.get("progress"):
            _log.info("%s already verified: skipped", thread)
            return "skipped"
        payload = {
            "run_id": run_id,
            "news_id": news_id,
            "thread_id": thread,
            "guard": guard,
        }
        error: BaseException | None = None
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                await self._invoke(payload, config)
            except Exception as e:  # noqa: BLE001 - recorded below.
                error = e
                _log.warning("%s attempt %d failed: %r", thread, attempt, e)
                continue
            snapshot = await runtime.graph.aget_state(config)
            return "review" if snapshot.next else "done"
        progress = await runtime.deps.repo.save_failure(
            run_id, news_id, thread, repr(error)
        )
        if progress.counted:
            await graph_lib.after_count(
                runtime.deps,
                run_id,
                progress,
                {"news_id": news_id, "verdict": None, "failed": True},
            )
        return "failed"

    async def resume(
        self,
        run_id: int,
        news_id: int,
        thread_id: str,
        decision: dict[str, Any],
    ) -> str:
        """Resumes a graph waiting for review.

        Returns:
            ``resumed``, or ``not-waiting`` when the graph isn't at the
            review step (already resumed, or its run was replaced).
        """
        del run_id, news_id
        runtime = self.runtime
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await runtime.graph.aget_state(config)
        if "review" not in (snapshot.next or ()):
            _log.info("%s isn't waiting for review", thread_id)
            return "not-waiting"
        await runtime.graph.ainvoke(
            lg_types.Command(resume=decision),
            config,
            context=graph_lib.Context(None),
        )
        return "resumed"


def build_broker() -> Any:
    """The worker's broker with the tasks (the taskiq CLI's factory)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = config.VerifySettings.from_env(os.environ)
    broker = queue.make_broker(settings.redis_host, settings.redis_password)
    worker = Worker(settings, broker)
    broker.add_event_handler(taskiq.TaskiqEvents.WORKER_STARTUP, worker.start)
    broker.add_event_handler(taskiq.TaskiqEvents.WORKER_SHUTDOWN, worker.stop)
    # taskiq renames the function it registers, which a bound method can't
    # take: each task is a plain function around the worker's method.

    async def run_day(run_id: int) -> int:
        return await worker.run_day(run_id)

    async def verify_item(
        run_id: int, news_id: int, guard: dict[str, Any]
    ) -> str:
        return await worker.verify_item(run_id, news_id, guard)

    async def resume(
        run_id: int, news_id: int, thread_id: str, decision: dict[str, Any]
    ) -> str:
        return await worker.resume(run_id, news_id, thread_id, decision)

    broker.register_task(run_day, task_name=queue.RUN_DAY)
    broker.register_task(verify_item, task_name=queue.VERIFY_ITEM)
    broker.register_task(resume, task_name=queue.RESUME)
    return broker
