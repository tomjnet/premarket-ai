"""``/briefs`` and ``/me/watchlist``: roles, the stream, memory."""

import asyncio
import datetime
import json

import conftest
from fastapi import testclient
from langgraph.store import memory as lg_memory
import pytest

from ai_api import app
from ai_api import briefs
from ai_api import deps
from ai_api import memory
from ai_api.verify import events

UTC = datetime.UTC
_SECTORS = ("Energy", "Information Technology")


def _item(n, news_id, tickers, sector, section="top", verdict="VERIFIED"):
    return {
        "n": n,
        "news_id": news_id,
        "vendor_item_id": f"VND-20260924-{news_id:03d}",
        "headline": f"[SYNTHETIC] Story {news_id}",
        "summary": "Apple said X.",
        "sentiment": "neutral",
        "tickers": tickers,
        "sector": sector,
        "source_domain": "wire.example",
        "published_at": "2026-09-24T08:01:00Z",
        "verdict": verdict,
        "confidence": 0.9,
        "review_status": None,
        "impact": "high",
        "impact_score": 0.9,
        "filing_url": "https://www.sec.gov/x",
        "filing_title": "8-K",
        "section": section,
        "new": False,
    }


def _brief(**overrides):
    row = {
        "brief_id": 3,
        "feed_date": conftest.DAY,
        "edition": "morning",
        "status": "DONE",
        "requested_by": "cli",
        "requested_at": datetime.datetime(2026, 9, 24, 11, 15, tzinfo=UTC),
        "started_at": datetime.datetime(2026, 9, 24, 11, 15, 1, tzinfo=UTC),
        "finished_at": datetime.datetime(2026, 9, 24, 11, 16, tzinfo=UTC),
        "error": None,
        "overview": "Apple reported X [1].",
        "overview_source": "llm",
        "citations": [1],
        "model": "cloud-openai",
        "cloud": True,
        "prompt_version": "brief-v1",
        "content": {
            "items": [
                _item(1, 11, ["AAPL"], "Information Technology"),
                _item(2, 12, ["XOM"], "Energy", "sector"),
                _item(
                    3,
                    13,
                    ["MSFT"],
                    "Information Technology",
                    "watch",
                    "UNVERIFIED",
                ),
            ],
            "top": [1],
            "sectors": [
                {"name": "Information Technology", "items": [1]},
                {"name": "Energy", "items": [2]},
            ],
            "watch": [3],
            "counts": {
                "verified": 2,
                "unconfirmed": 1,
                "unverified": 1,
                "pending_review": 4,
                "misleading": 1,
                "fake": 5,
                "failed": 0,
                "new": 0,
            },
            "notes": ["internal"],
        },
    }
    row.update(overrides)
    return row


class _FakeBriefs:
    def __init__(self):
        self.rows = {3: _brief()}
        self.finished = {}
        self.created = []

    async def create(self, day, edition, user):
        row = _brief(
            brief_id=4,
            edition=edition,
            status="QUEUED",
            requested_by=user,
            started_at=None,
            finished_at=None,
        )
        self.created.append(row)
        return row

    async def active(self, day):
        found = [r for r in self.rows.values() if r["status"] == "RUNNING"]
        return found[0] if found else None

    async def current(self, day):
        if day != conftest.DAY:
            return None
        return max(self.rows.values(), key=lambda r: r["brief_id"])

    async def get(self, brief_id):
        # The row as the worker left it (a finished brief), else as is.
        return self.finished.get(brief_id, self.rows.get(brief_id))


class _FakeQueue:
    def __init__(self):
        self.briefs = []

    async def write_brief(self, brief_id):
        self.briefs.append(brief_id)


@pytest.fixture
def setup(harness):
    store = _FakeBriefs()
    jobs = _FakeQueue()
    mem = memory.StoreMemory(lg_memory.InMemoryStore())
    services = deps.Services(
        settings=harness.settings,
        users=harness.users,
        news=harness.news,
        sessions=harness.sessions,
        ping=conftest._ping,
        queue=jobs,
        briefs=store,
        brief_events=events.RunEvents(harness.redis, prefix="brief"),
        memory=mem,
        sectors=_SECTORS,
    )
    client = testclient.TestClient(
        app.create_app(services=services), base_url="https://testserver"
    )
    with client:
        yield harness, client, store, jobs, mem


def _bearer(harness, username="trader1"):
    return {"Authorization": f"Bearer {harness.login(username)}"}


def _events(text):
    found = []
    for block in text.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        found.append((lines["event"], json.loads(lines["data"])))
    return found


def test_a_done_brief_streams_at_once_with_the_callers_watchlist(setup):
    harness, client, _, _, mem = setup
    asyncio.run(mem.save_watchlist("trader1", memory.Watchlist(("XOM",), ())))
    response = client.get(
        "/briefs/today?date=2026-09-24", headers=_bearer(harness)
    )
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    found = _events(response.text)
    assert [name for name, _ in found] == ["brief", "done"]
    meta, done = found[0][1], found[1][1]
    assert meta["edition"] == "morning" and meta["status"] == "DONE"
    assert done["watchlist"] == {
        "tickers": ["XOM"],
        "sectors": [],
        "items": [2],
    }
    assert done["counts"]["pending_review"] == 4
    assert done["items"][2]["section"] == "watch"
    assert "notes" not in done
    assert done["finished_at"] == "2026-09-24T11:16:00Z"
    assert ("brief", "trader1") in harness.users.events


def test_no_brief_is_404(setup):
    harness, client, _, _, _ = setup
    response = client.get(
        "/briefs/today?date=2026-09-23", headers=_bearer(harness)
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "No brief for 2026-09-23 yet"}
    assert client.get("/briefs/today").status_code == 401


def test_a_running_brief_streams_its_progress_then_the_brief(setup):
    harness, client, store, _, _ = setup
    store.rows[5] = _brief(brief_id=5, status="RUNNING", finished_at=None)
    stream = events.RunEvents(harness.redis, prefix="brief")

    async def publish():
        await stream.publish(5, "status", {"detail": "Collecting"})
        await stream.publish(5, "sections", {"counts": {"verified": 2}})
        store.finished[5] = _brief(brief_id=5, edition="refresh")
        await stream.publish(5, "brief.done", {"brief_id": 5})

    asyncio.run(publish())
    response = client.get(
        "/briefs/today?date=2026-09-24", headers=_bearer(harness)
    )
    names = [name for name, _ in _events(response.text)]
    assert names == ["brief", "status", "sections", "done"]
    assert _events(response.text)[-1][1]["edition"] == "refresh"


def test_a_failed_brief_says_so(setup):
    harness, client, store, _, _ = setup
    store.rows[5] = _brief(brief_id=5, status="FAILED", error="Trace...")
    found = _events(
        client.get(
            "/briefs/today?date=2026-09-24", headers=_bearer(harness)
        ).text
    )
    assert found[0][1]["error"] == "The brief failed."
    assert found[1][0] == "error"


def test_only_analysts_queue_a_brief_after_the_verification(setup):
    harness, client, store, jobs, _ = setup
    body = {"date": "2026-09-24", "edition": "refresh"}
    trader = _bearer(harness)
    assert client.post("/briefs", json=body, headers=trader).status_code == 403
    analyst = _bearer(harness, "analyst1")
    queued = client.post("/briefs", json=body, headers=analyst)
    assert queued.status_code == 202
    assert queued.json()["status"] == "QUEUED"
    assert queued.json()["edition"] == "refresh"
    assert jobs.briefs == [4]
    assert ("brief_write", "analyst1") in harness.users.events
    store.rows[5] = _brief(brief_id=5, status="RUNNING")
    busy = client.post("/briefs", json=body, headers=analyst)
    assert busy.status_code == 409
    harness.news.verify_run = conftest.make_verify_run(status="RUNNING")
    late = client.post("/briefs", json=body, headers=analyst)
    assert late.json() == {
        "detail": "The AI verification of 2026-09-24 is RUNNING"
    }
    assert (
        client.post(
            "/briefs", json={**body, "edition": "noon"}, headers=analyst
        ).status_code
        == 422
    )


def test_the_watchlist_is_saved_per_user_and_checked(setup):
    harness, client, _, _, mem = setup
    trader = _bearer(harness)
    empty = client.get("/me/watchlist", headers=trader).json()
    assert empty == {
        "tickers": [],
        "sectors": [],
        "available_sectors": list(_SECTORS),
    }
    saved = client.put(
        "/me/watchlist",
        json={"tickers": ["aapl", "BRK.B", "AAPL"], "sectors": ["Energy"]},
        headers=trader,
    )
    assert saved.status_code == 200
    assert saved.json()["tickers"] == ["AAPL", "BRK.B"]
    assert ("watchlist", "trader1") in harness.users.events
    analyst = _bearer(harness, "analyst1")
    assert client.get("/me/watchlist", headers=analyst).json()["tickers"] == []
    assert asyncio.run(mem.watched_tickers()) == {"AAPL", "BRK.B"}
    unknown = client.put(
        "/me/watchlist", json={"tickers": ["QVXH"]}, headers=trader
    )
    assert unknown.status_code == 422
    assert unknown.json() == {"detail": "Not in the SEC ticker registry: QVXH"}
    bad = client.put("/me/watchlist", json={"tickers": ["A;B"]}, headers=trader)
    assert bad.json() == {"detail": "Not a ticker: 'A;B'"}
    sector = client.put(
        "/me/watchlist", json={"sectors": ["Crypto"]}, headers=trader
    )
    assert sector.json() == {"detail": "Unknown sector: 'Crypto'"}
    harness.news.registry = None
    anything = client.put(
        "/me/watchlist", json={"tickers": ["QVXH"]}, headers=trader
    )
    assert anything.status_code == 200


def test_for_user_matches_tickers_and_sectors():
    content = _brief()["content"]
    both = memory.Watchlist(("MSFT",), ("Energy",))
    assert briefs.for_user(content, both) == [2, 3]
    assert briefs.for_user(content, memory.Watchlist()) == []
