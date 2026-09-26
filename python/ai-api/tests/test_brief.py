"""The briefing agent: what goes in, the checked overview, the job."""

import asyncio
import datetime
import os
import pathlib

import fakeredis
from langchain_core import messages
from langchain_core.language_models import fake_chat_models

from ai_api.agents import brief
from ai_api.agents import skills
from ai_api.guard import llama_guard
from ai_api.llm import budget
from ai_api.llm import tracing
from ai_api.rag import universe
from ai_api.verify import events

_DAY = datetime.date(2026, 9, 24)
_UTC = datetime.UTC
_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SKILLS = pathlib.Path(os.environ.get("SKILLS_DIR") or _ROOT / "skills")
_CONFIG = pathlib.Path(
    os.environ.get("PREMARKET_CONFIG_DIR") or _ROOT / "config"
)
_MEMBERS = universe.load(_CONFIG)
_TRACER = tracing.Tracer(tracing.TracingConfig())


def row(news_id, verdict, status="DONE", impact="medium", score=0.5, **extra):
    found = {
        "news_id": news_id,
        "vendor_item_id": f"VND-20260924-{news_id:03d}",
        "headline": f"[SYNTHETIC] Story {news_id}",
        "source_domain": "wire.example",
        "published_at": datetime.datetime(2026, 9, 24, 8, news_id, tzinfo=_UTC),
        "tickers": ["AAPL"],
        "status": status,
        "verdict": verdict,
        "confidence": 0.9,
        "review_status": None,
        "impact": impact,
        "impact_score": score,
        "summary": f"Apple said thing {news_id}.",
        "sentiment": "neutral",
        "filing_url": None,
        "filing_title": None,
    }
    found.update(extra)
    return found


ROWS = [
    row(1, "VERIFIED", score=0.4),
    row(2, "VERIFIED", impact="high", score=0.9, tickers=["XOM"]),
    row(3, "UNVERIFIED", impact="high", score=0.95),
    row(4, "UNVERIFIED", impact="low", score=0.1),
    row(5, "FAKE", impact="high", score=0.99),
    row(6, "MISLEADING", score=0.7),
    row(7, "VERIFIED", status="PENDING_REVIEW", score=0.8),
    row(8, None, status="FAILED"),
    row(9, "VERIFIED", score=0.3, tickers=["QVXH"], review_status="APPROVED"),
]


def test_only_verified_and_high_impact_unverified_items_go_in():
    content = brief.compose(ROWS, _MEMBERS)
    by_n = {i["n"]: i for i in content["items"]}
    assert [i["news_id"] for i in content["items"]] == [2, 1, 9, 3]
    assert content["top"] == [1, 2, 3] and content["watch"] == [4]
    assert by_n[4]["section"] == "watch" and by_n[4]["verdict"] == "UNVERIFIED"
    assert content["sectors"] == [
        {"name": "Energy", "items": [1]},
        {"name": "Information Technology", "items": [2]},
        {"name": "Other", "items": [3]},
    ]
    assert content["counts"] == {
        "verified": 3,
        "unconfirmed": 1,
        "unverified": 2,
        "pending_review": 1,
        "misleading": 1,
        "fake": 1,
        "failed": 1,
        "new": 0,
    }
    assert by_n[1]["published_at"] == "2026-09-24T08:02:00Z"


def test_top_stories_are_capped_and_the_refresh_marks_new_items():
    content = brief.compose(ROWS, _MEMBERS, previous={1, 2}, top_max=1)
    sections = {
        i["news_id"]: (i["section"], i["new"]) for i in content["items"]
    }
    assert sections == {
        2: ("top", False),
        1: ("sector", False),
        9: ("sector", True),
        3: ("watch", True),
    }
    assert content["counts"]["new"] == 2


def test_the_overview_checks():
    valid = {1, 2}
    assert brief.check_overview("Apple rose [1][2].", valid) == (
        "Apple rose [1][2].",
        [1, 2],
        "",
    )
    assert brief.check_overview("Apple rose.", valid)[2] == "no citation"
    assert brief.check_overview("See [7].", valid)[2] == "unknown citation"
    assert brief.check_overview("You should buy Apple [1].", valid)[2] == (
        "advice"
    )


def test_the_fallback_overview_cites_the_top_items():
    content = brief.compose(ROWS, _MEMBERS)
    text = brief.fallback_overview(content, _DAY)
    assert text.startswith("3 stories are verified for 2026-09-24")
    assert "[1]" in text and "[3]" in text and "[4]" not in text
    empty = brief.compose([row(7, "VERIFIED", status="PENDING_REVIEW")], [])
    assert brief.fallback_overview(empty, _DAY).startswith("No story")


def _model(*answers):
    return fake_chat_models.GenericFakeChatModel(
        messages=iter([messages.AIMessage(content=a) for a in answers])
    )


class _Failing(fake_chat_models.GenericFakeChatModel):
    async def ainvoke(self, *args, **kwargs):
        raise ConnectionError("provider key missing")


def _writer(local, cloud=None, spent=0.0, guard=None, blocks=False):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    cap = budget.CloudBudget(redis, 20.0)
    if spent:
        asyncio.run(cap.add(spent))
    return brief.Writer(
        local,
        "main-gpu4gb",
        skills.Library.load(_SKILLS),
        _TRACER,
        cloud=cloud,
        cloud_name="cloud-openai",
        budget=cap,
        guard=guard,
        guard_blocks=blocks,
    )


def _content():
    return brief.compose(ROWS, _MEMBERS)


def test_the_cloud_model_writes_while_the_budget_allows():
    writer = _writer(_model("local [1]."), cloud=_model("Cloud wrote [1][2]."))
    assert asyncio.run(writer.model_name()) == "cloud-openai"
    written = asyncio.run(writer.overview(_content(), _DAY))
    assert (written.text, written.source, written.cloud) == (
        "Cloud wrote [1][2].",
        "llm",
        True,
    )
    assert written.citations == (1, 2)


def test_budget_used_up_or_a_cloud_error_falls_back_to_local():
    spent = _writer(_model("Local wrote [2]."), cloud=_model("x"), spent=20.0)
    assert asyncio.run(spent.model_name()) == "main-gpu4gb"
    written = asyncio.run(spent.overview(_content(), _DAY))
    assert (written.model, written.cloud) == ("main-gpu4gb", False)
    failing = _writer(
        _model("Local wrote [2]."), cloud=_Failing(messages=iter([]))
    )
    written = asyncio.run(failing.overview(_content(), _DAY))
    assert written.model == "main-gpu4gb"
    assert written.notes == ("cloud-openai failed: ConnectionError",)


def test_advice_gets_one_rewrite_then_the_deterministic_overview():
    retried = _writer(_model("Buy the stock [1].", "Apple reported [1]."))
    written = asyncio.run(retried.overview(_content(), _DAY))
    assert written.text == "Apple reported [1]." and written.source == "llm"
    assert written.notes == ("attempt 1 failed the checks: advice",)
    stubborn = _writer(_model("Buy the stock [1].", "No numbers here."))
    written = asyncio.run(stubborn.overview(_content(), _DAY))
    assert written.source == "fallback" and written.model is None
    assert written.citations == (1, 2, 3)


class _Guard:
    enabled = True

    async def check_answer(self, question, answer):
        del question, answer
        return llama_guard.Verdict(True, False, ("S1",))


def test_llama_guard_blocks_only_when_configured():
    evidence = _writer(_model("Apple reported [1]."), guard=_Guard())
    assert asyncio.run(evidence.overview(_content(), _DAY)).source == "llm"
    blocking = _writer(
        _model("Apple reported [1]."), guard=_Guard(), blocks=True
    )
    assert asyncio.run(blocking.overview(_content(), _DAY)).source == (
        "fallback"
    )


class _Repo:
    def __init__(self, status="QUEUED", edition="refresh"):
        self.status = status
        self.edition = edition
        self.finished = None
        self.failed = None

    async def start(self, brief_id):
        if self.status != "QUEUED":
            return None
        self.status = "RUNNING"
        return {
            "brief_id": brief_id,
            "feed_date": _DAY,
            "edition": self.edition,
        }

    async def items(self, day):
        assert day == _DAY
        return ROWS

    async def morning_ids(self, day):
        return {1, 2}

    async def finish(self, brief_id, content, written, total_ms):
        self.finished = (content, written)

    async def fail(self, brief_id, error):
        self.failed = error


def test_the_job_publishes_its_progress_and_stores_the_brief():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    stream = events.RunEvents(redis, prefix="brief")
    repo = _Repo()
    job = brief.Job(
        repo, _writer(_model("Apple reported [1].")), stream, _MEMBERS
    )
    assert asyncio.run(job.run(5)) == "done"
    content, written = repo.finished
    assert content["counts"]["new"] == 2 and written.source == "llm"
    found = asyncio.run(stream.read(5, block_ms=0))
    assert [kind for _, kind, _ in found] == [
        "status",
        "sections",
        "status",
        "brief.done",
    ]
    assert found[2][2]["detail"] == "Writing the overview (main-gpu4gb)"
    assert asyncio.run(redis.exists("brief:5:events")) == 1
    assert asyncio.run(job.run(5)) == "skipped"


def test_a_failing_job_is_recorded():
    class Broken(_Repo):
        async def items(self, day):
            raise RuntimeError("db down")

    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    stream = events.RunEvents(redis, prefix="brief")
    repo = Broken(edition="morning")
    job = brief.Job(repo, _writer(_model()), stream, _MEMBERS)
    assert asyncio.run(job.run(6)) == "failed"
    assert "db down" in repo.failed
    kinds = [kind for _, kind, _ in asyncio.run(stream.read(6, block_ms=0))]
    assert kinds == ["status", "brief.failed"]
