"""The run coordinator, run events and the tools' MCP payloads."""

import asyncio
import datetime
import types

import fakeredis
import pytest

from ai_api.guard import llama_guard
from ai_api.verify import coordinator
from ai_api.verify import events
from ai_api.verify import graph as graph_lib
from ai_api.verify import repository
from ai_api.verify import tools as tools_lib

_DAY = datetime.date(2026, 9, 24)


class FakeRepo:
    """start_run / load_item / fail_run / finish_run in memory."""

    def __init__(self, ids, ready=True):
        """Serves ``ids`` for the day (or refuses when not ready)."""
        self.ids = ids
        self.ready = ready
        self.failed = None
        self.finished = False

    async def start_run(self, run_id, model, prompt_version):
        """The day, its items and one old thread."""
        if not self.ready:
            raise repository.NotReadyError("AI run missing")
        return _DAY, list(self.ids), ["verify-1-5"]

    async def fail_run(self, run_id, error):
        """Records the failure."""
        self.failed = error

    async def finish_run(self, run_id):
        """Finishes an empty run."""
        self.finished = True
        return {"run_id": run_id, "status": "DONE", "total": 0, "done": 0}

    async def load_item(self, news_id):
        """A tiny item."""
        return {"headline": f"Headline {news_id}", "body": "Body text."}


class FakeGuard:
    """Flags item 2 as unsafe."""

    enabled = True

    async def check_news(self, headline, body):
        """Unsafe for 'Headline 2'."""
        del body
        if headline.endswith("2"):
            return llama_guard.Verdict(True, False, ("S5",))
        return llama_guard.Verdict(True)


class FakeQueue:
    """Records item jobs."""

    def __init__(self):
        """No jobs yet."""
        self.items = []

    async def verify_item(self, run_id, news_id, guard):
        """Records the job."""
        self.items.append((news_id, guard["safe"]))


class FakeSaver:
    """Records deleted threads."""

    def __init__(self):
        """Nothing deleted yet."""
        self.deleted = []

    async def adelete_thread(self, thread_id):
        """Records the thread."""
        self.deleted.append(thread_id)


def _coordinator(repo, queue, saver=None):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    deps = graph_lib.Deps(repo=repo, events=events.RunEvents(redis))
    return (
        coordinator.Coordinator(repo, deps, FakeGuard(), queue, saver),
        events.RunEvents(redis),
    )


def test_the_coordinator_guards_and_queues_every_item():
    queue = FakeQueue()
    saver = FakeSaver()
    found, reader = _coordinator(FakeRepo([1, 2, 3]), queue, saver)
    assert asyncio.run(found.run(9, "main-gpu4gb")) == 3
    assert queue.items == [(1, True), (2, False), (3, True)]
    assert saver.deleted == ["verify-1-5"]
    kinds = [kind for _, kind, _ in asyncio.run(reader.read(9, block_ms=0))]
    assert kinds == ["run.started"]


def test_a_day_that_isnt_ready_fails_the_run():
    repo = FakeRepo([1], ready=False)
    queue = FakeQueue()
    found, reader = _coordinator(repo, queue)
    assert asyncio.run(found.run(9, "m")) == 0
    assert repo.failed == "AI run missing"
    assert queue.items == []
    data = asyncio.run(reader.read(9, block_ms=0))
    assert data[0][1:] == ("run.failed", {"error": "AI run missing"})


def test_an_empty_day_finishes_at_once():
    repo = FakeRepo([])
    found, reader = _coordinator(repo, FakeQueue())
    asyncio.run(found.run(9, "m"))
    assert repo.finished
    kinds = [kind for _, kind, _ in asyncio.run(reader.read(9, block_ms=0))]
    assert kinds == ["run.started", "run.done"]


def test_events_resume_after_an_id():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    reader = events.RunEvents(redis)

    async def run():
        first = await reader.publish(3, "item", {"n": 1})
        await reader.publish(3, "item", {"n": 2})
        return await reader.read(3, first, block_ms=0), await redis.ttl(
            events.stream_key(3)
        )

    found, ttl = asyncio.run(run())
    assert [data for _, _, data in found] == [{"n": 2}]
    assert 0 < ttl <= events.TTL_S


def test_mcp_payloads_are_unwrapped():
    text = types.SimpleNamespace(text='{"tier": "low"}')
    assert tools_lib._payload(
        types.SimpleNamespace(
            isError=False, structuredContent=None, content=[text]
        )
    ) == {"tier": "low"}
    wrapped = types.SimpleNamespace(
        isError=False, structuredContent={"result": [1, 2]}, content=[]
    )
    assert tools_lib._payload(wrapped) == [1, 2]
    error = types.SimpleNamespace(
        isError=True, content=[types.SimpleNamespace(text="boom")]
    )
    with pytest.raises(tools_lib.ToolError, match="boom"):
        tools_lib._payload(error)


def test_mcp_tools_refuse_tools_outside_the_allowlist():
    class Session:
        async def call_tool(self, name, arguments):
            raise AssertionError("must not be called")

    tools = tools_lib.McpTools(Session())
    with pytest.raises(tools_lib.ToolError):
        asyncio.run(tools._call("fetch_url", {"url": "http://x"}))
