"""``/runs`` and ``/review``: roles, contract, conflicts, events."""

import asyncio
import datetime

import conftest
from fastapi import testclient
import pytest

from ai_api import app
from ai_api import deps
from ai_api import verdicts
from ai_api.verify import events

UTC = datetime.UTC


def _task(**overrides):
    task = {
        "id": 31,
        "news_id": 11,
        "run_id": 7,
        "status": "PENDING",
        "reasons": ["low_confidence", "judge_disagrees"],
        "ai_verdict": "VERIFIED",
        "ai_confidence": 0.39,
        "final_verdict": None,
        "impact_score": 0.98,
        "reviewer": None,
        "comment": None,
        "created_at": datetime.datetime(2026, 9, 24, 10, 15, tzinfo=UTC),
        "decided_at": None,
        "thread_id": "verify-7-11",
        "feed_date": conftest.DAY,
        "vendor_item_id": "VND-20260924-001",
        "raw_id": 2001,
        "headline": "[SYNTHETIC] Apple raises dividend",
        "source_domain": "wire.vendornews.example",
        "tickers": ["AAPL"],
        "reason_codes": [],
        "rationale": "Trusted wire [E1].",
        "rule_verdict": "VERIFIED",
        "judge_verdict": "MISLEADING",
        "impact": "high",
    }
    task.update(overrides)
    return task


class FakeVerdicts:
    """Runs and one review task in memory."""

    def __init__(self):
        """One DONE run, one pending task."""
        self.runs_ = {7: conftest.make_verify_run()}
        self.tasks = {31: _task()}
        self.decisions = []

    async def create_run(self, day, user):
        """A QUEUED run."""
        run = conftest.make_verify_run(
            run_id=8,
            feed_date=day,
            status="QUEUED",
            requested_by=user,
            started_at=None,
            finished_at=None,
            total=0,
            done=0,
        )
        self.runs_[8] = run
        return run

    async def active_run(self, day):
        """QUEUED/RUNNING runs of the day."""
        return next(
            (
                r
                for r in self.runs_.values()
                if r["feed_date"] == day
                and r["status"] in ("QUEUED", "RUNNING")
            ),
            None,
        )

    async def runs(self, day, limit):
        """Newest first."""
        found = [
            r for r in self.runs_.values() if day in (None, r["feed_date"])
        ]
        return sorted(found, key=lambda r: -r["run_id"])[:limit]

    async def run(self, run_id):
        """One run."""
        return self.runs_.get(run_id)

    async def queue(self, status, day, limit):
        """Tasks by status."""
        return [t for t in self.tasks.values() if status in (None, t["status"])]

    async def task(self, task_id):
        """One task."""
        return self.tasks.get(task_id)

    async def decide(self, task_id, decision):
        """Decides a pending task."""
        task = self.tasks.get(task_id)
        if task is None:
            return None
        if task["status"] != "PENDING":
            raise verdicts.ReviewConflictError("decided")
        self.decisions.append(decision)
        override = decision.action == "override"
        task.update(
            status="OVERRIDDEN" if override else "APPROVED",
            final_verdict=decision.verdict if override else task["ai_verdict"],
            reviewer=decision.reviewer,
            comment=decision.comment or None,
            decided_at=datetime.datetime(2026, 9, 24, 11, 0, tzinfo=UTC),
        )
        return task


class FakeQueue:
    """Records the jobs."""

    def __init__(self):
        """No jobs yet."""
        self.jobs = []

    async def run_day(self, run_id):
        """Records a run."""
        self.jobs.append(("run_day", run_id))

    async def resume(self, run_id, news_id, thread_id, decision):
        """Records a resume."""
        self.jobs.append(("resume", thread_id, decision))


@pytest.fixture
def setup(harness):
    store = FakeVerdicts()
    jobs = FakeQueue()
    services = deps.Services(
        settings=harness.settings,
        users=harness.users,
        news=harness.news,
        sessions=harness.sessions,
        ping=conftest._ping,
        verdicts=store,
        queue=jobs,
        run_events=events.RunEvents(harness.redis),
    )
    client = testclient.TestClient(
        app.create_app(services=services), base_url="https://testserver"
    )
    with client:
        yield harness, client, store, jobs


def _bearer(harness, username):
    return {"Authorization": f"Bearer {harness.login(username)}"}


def test_traders_can_start_no_run_and_see_no_queue(setup):
    harness, client, _, _ = setup
    trader = _bearer(harness, "trader1")
    assert client.post("/runs", json={}, headers=trader).status_code == 403
    assert client.get("/runs", headers=trader).status_code == 403
    assert client.get("/review", headers=trader).status_code == 403
    assert (
        client.post(
            "/review/31", json={"action": "approve"}, headers=trader
        ).status_code
        == 403
    )


def test_start_a_run(setup):
    harness, client, _, jobs = setup
    analyst = _bearer(harness, "analyst1")
    response = client.post(
        "/runs", json={"date": "2026-09-24"}, headers=analyst
    )
    assert response.status_code == 202
    body = response.json()
    assert (body["run_id"], body["status"]) == (8, "QUEUED")
    assert body["requested_by"] == "analyst1"
    assert jobs.jobs == [("run_day", 8)]
    assert ("verify_run", "analyst1") in harness.users.events
    again = client.post("/runs", json={"date": "2026-09-24"}, headers=analyst)
    assert again.status_code == 409
    assert "already being verified" in again.json()["detail"]


def test_a_day_without_its_ai_run_is_409(setup):
    harness, client, _, jobs = setup
    harness.news.ai_run = None
    response = client.post(
        "/runs", json={"date": "2026-09-24"}, headers=_bearer(harness, "admin1")
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "The AI run of 2026-09-24 is missing"
    assert jobs.jobs == []


def test_list_and_get_runs(setup):
    harness, client, _, _ = setup
    admin = _bearer(harness, "admin1")
    listed = client.get("/runs", params={"date": "2026-09-24"}, headers=admin)
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["finished_at"] == "2026-09-24T10:20:00Z"
    assert client.get("/runs/7", headers=admin).json()["fake"] == 1
    assert client.get("/runs/99", headers=admin).status_code == 404


def test_the_review_queue(setup):
    harness, client, _, _ = setup
    body = client.get("/review", headers=_bearer(harness, "analyst1")).json()
    assert body["count"] == 1
    task = body["items"][0]
    assert task["item_id"] == 2001
    assert task["reasons"] == ["low_confidence", "judge_disagrees"]
    assert task["created_at"] == "2026-09-24T10:15:00Z"
    assert "thread_id" not in task


def test_approve_resumes_the_graph(setup):
    harness, client, store, jobs = setup
    analyst = _bearer(harness, "analyst1")
    response = client.post(
        "/review/31", json={"action": "approve"}, headers=analyst
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert jobs.jobs == [
        (
            "resume",
            "verify-7-11",
            {
                "action": "approve",
                "verdict": None,
                "reviewer": "analyst1",
                "comment": "",
            },
        )
    ]
    again = client.post(
        "/review/31", json={"action": "approve"}, headers=analyst
    )
    assert again.status_code == 409
    assert ("review", "analyst1") in harness.users.events


def test_override_needs_a_verdict_and_a_comment(setup):
    harness, client, store, _ = setup
    analyst = _bearer(harness, "analyst1")
    for body in (
        {"action": "override", "comment": "No such dividend."},
        {"action": "override", "verdict": "FAKE", "comment": " "},
        {"action": "approve", "verdict": "FAKE"},
        {"action": "delete"},
    ):
        response = client.post("/review/31", json=body, headers=analyst)
        assert response.status_code == 422, body
    response = client.post(
        "/review/31",
        json={"action": "override", "verdict": "FAKE", "comment": "Made up."},
        headers=analyst,
    )
    assert response.status_code == 200
    assert response.json()["final_verdict"] == "FAKE"
    assert store.decisions[-1].comment == "Made up."
    assert (
        client.post(
            "/review/99", json={"action": "approve"}, headers=analyst
        ).status_code
        == 404
    )


def test_run_events_replay_from_the_stream(setup):
    harness, client, _, _ = setup
    reader = events.RunEvents(harness.redis)

    async def publish():
        await reader.publish(7, "run.started", {"total": 2})
        await reader.publish(7, "item", {"news_id": 11, "done": 1, "total": 2})
        await reader.publish(7, "run.done", {"done": 2})

    asyncio.run(publish())
    analyst = _bearer(harness, "analyst1")
    response = client.get("/runs/7/events", headers=analyst)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    names = [
        line.split(": ", 1)[1]
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]
    assert names == ["run.started", "item", "run.done"]
    ids = [
        line.split(": ", 1)[1]
        for line in response.text.splitlines()
        if line.startswith("id: ")
    ]
    resumed = client.get(
        "/runs/7/events", headers={**analyst, "Last-Event-ID": ids[0]}
    )
    assert "run.started" not in resumed.text
    bad = client.get(
        "/runs/7/events", headers={**analyst, "Last-Event-ID": "x; DROP"}
    )
    assert bad.status_code == 422


def test_a_finished_run_without_a_stream_ends_at_once(setup):
    harness, client, _, _ = setup
    response = client.get(
        "/runs/7/events", headers=_bearer(harness, "analyst1")
    )
    assert "event: run.done" in response.text


def test_the_decision_is_what_the_graph_resumes_with():
    decision = verdicts.Decision("override", "analyst1", "FAKE", "Made up.")
    assert decision.resume_value() == {
        "action": "override",
        "verdict": "FAKE",
        "reviewer": "analyst1",
        "comment": "Made up.",
    }
