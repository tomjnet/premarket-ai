"""Increment 6: admin pages, vendor scorecard, SLA panel, cloud switches."""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import conftest
import fakeredis
from fastapi import testclient
import pytest

from ai_api import admin
from ai_api import app
from ai_api import deps
from ai_api import scorecard
from ai_api import sessions
from ai_api import users
from ai_api.llm import budget
from ai_api.llm import switches

UTC = datetime.UTC
NOW = datetime.datetime(2026, 9, 28, 13, 0, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


class FakeUserAdmin(conftest.FakeUsers):
    """The conftest users, plus the admin operations."""

    async def list_all(self) -> list[users.UserRow]:
        """Every user, by name."""
        return [
            users.UserRow(u.username, u.role, u.disabled, NOW, NOW)
            for u in sorted(self.users.values(), key=lambda u: u.username)
        ]

    async def create(self, username: str, role: str, password_hash: str):
        """Adds a user."""
        if username in self.users:
            raise users.DuplicateUserError(username)
        self.users[username] = users.User(username, role, password_hash)

    async def update(
        self, username, role=None, disabled=None, password_hash=None
    ):
        """Changes a user."""
        found = self.users.get(username)
        if found is None:
            return None
        self.users[username] = users.User(
            username,
            found.role if role is None else role,
            found.password_hash if password_hash is None else password_hash,
            found.disabled if disabled is None else disabled,
        )
        changed = self.users[username]
        return users.UserRow(username, changed.role, changed.disabled, NOW, NOW)


class FakeAdmin:
    """Source reputation in memory; switches in (fake) Redis."""

    def __init__(self, redis) -> None:
        """Seeds one domain."""
        self.redis = redis
        self.rows = {
            "reuters.com": admin.SourceRow(
                "reuters.com", "trusted", 0.95, "wire", NOW
            )
        }

    async def sources(self, query: str = "") -> list[admin.SourceRow]:
        """Domains containing ``query``."""
        return [r for d, r in sorted(self.rows.items()) if query in d]

    async def upsert_source(self, domain, tier, reputation, note):
        """Adds or changes a domain."""
        self.rows[domain] = admin.SourceRow(domain, tier, reputation, note, NOW)
        return self.rows[domain]

    async def cloud_switches(self) -> dict[str, bool]:
        """The switches in effect."""
        return await switches.read(self.redis)

    async def set_cloud_switches(self, values, user):
        """Mirrors to Redis only."""
        await switches.mirror(self.redis, values)
        return await switches.read(self.redis)


def score_row(day: datetime.date, **overrides: Any) -> dict[str, Any]:
    row = {
        "feed_date": day,
        "received": 100,
        "unique_items": 80,
        "duplicates": 20,
        "dup_url": 3,
        "dup_exact": 6,
        "dup_near": 5,
        "dup_paraphrase": 6,
        "stale": 4,
        "verified": 50,
        "unverified": 12,
        "misleading": 8,
        "fake": 10,
        "failed": 0,
        "pending_review": 2,
        "injection": 2,
        "avg_corroboration": 1.4,
        "reviewed": 10,
        "overridden": 2,
        "billable": 62,
        "contracted": 100,
        "cloud_cost_usd": 0.04,
        "computed_at": NOW,
    }
    row.update(overrides)
    return row


class FakeScorecard:
    """Three days of rows."""

    def __init__(self) -> None:
        """Newest last."""
        days = [datetime.date(2026, 9, d) for d in (24, 25, 28)]
        self.rows = [score_row(d, billable=60 + i) for i, d in enumerate(days)]

    async def days(self, last, count):
        """Newest first, up to ``last``."""
        found = [r for r in self.rows if last is None or r["feed_date"] <= last]
        return sorted(found, key=lambda r: r["feed_date"], reverse=True)[:count]


class FakeSummarizer:
    """Records what it was asked to summarize."""

    def __init__(self) -> None:
        """No calls yet."""
        self.calls = 0

    async def write(self, found):
        """A fixed summary."""
        self.calls += 1
        return scorecard.Summary(f"{len(found)} days summarized.", "llm", "m")


class FakeSchedule:
    """A trading day with every SLA green."""

    async def runs(self, day):
        """The day's rows."""
        at = datetime.datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
        return [
            {
                "job": job,
                "run_mode": "production",
                "status": status,
                "started_at": at,
                "finished_at": at,
                "detail": "",
            }
            for job, status in (
                ("pipeline", "DONE"),
                ("sla-ingest", "OK"),
                ("sla-verify", "OK"),
                ("sla-brief", "OK"),
            )
        ]


class AdminHarness:
    """The app with the increment 6 services wired to fakes."""

    def __init__(self) -> None:
        """Wires the fakes."""
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.users = FakeUserAdmin()
        self.summarizer = FakeSummarizer()
        self.sessions = sessions.SessionStore(
            self.redis, ttl_s=3600, grace_s=30, max_failures=5, lockout_s=900
        )
        services = deps.Services(
            settings=conftest.make_settings(
                judge_cloud_model="cloud-openai", brief_model="cloud-openai"
            ),
            users=self.users,
            news=conftest.FakeNews(),
            sessions=self.sessions,
            ping=conftest._ping,
            budget=budget.CloudBudget(self.redis, 20.0),
            admin=FakeAdmin(self.redis),
            user_admin=self.users,
            scorecard=FakeScorecard(),
            summarizer=self.summarizer,
            cache=self.redis,
            schedule=FakeSchedule(),
        )
        self.client = testclient.TestClient(
            app.create_app(services=services), base_url="https://testserver"
        )

    def bearer(self, username: str, password: str = conftest.PASSWORD):
        """Logs in; returns the Authorization header."""
        response = self.client.post(
            "/auth/login", data={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def h():
    harness = AdminHarness()
    with harness.client:
        yield harness


# --- users --------------------------------------------------------------------


def test_admin_pages_are_admin_only(h):
    for username in ("trader1", "analyst1"):
        bearer = h.bearer(username)
        for path in ("/admin/users", "/admin/sources", "/admin/llm"):
            assert h.client.get(path, headers=bearer).status_code == 403
    assert h.client.get("/admin/users").status_code == 401


def test_admin_creates_and_changes_users(h):
    bearer = h.bearer("admin1")
    listed = h.client.get("/admin/users", headers=bearer).json()
    assert "password_hash" not in listed["items"][0]
    body = {"username": "trader2", "role": "TRADER", "password": "short"}
    assert (
        h.client.post("/admin/users", json=body, headers=bearer).status_code
        == 422
    )
    body["password"] = "a-long-enough-password"
    created = h.client.post("/admin/users", json=body, headers=bearer)
    assert created.status_code == 201
    assert created.json()["role"] == "TRADER"
    again = h.client.post("/admin/users", json=body, headers=bearer)
    assert again.status_code == 409
    changed = h.client.post(
        "/admin/users/trader2", json={"role": "ANALYST"}, headers=bearer
    )
    assert changed.json()["role"] == "ANALYST"
    missing = h.client.post(
        "/admin/users/nobody", json={"disabled": True}, headers=bearer
    )
    assert missing.status_code == 404
    actions = [a for a, _ in h.users.events if a.startswith("admin_")]
    assert actions == ["admin_user_create", "admin_user_update"]


def test_disabling_a_user_ends_their_sessions(h):
    trader = h.bearer("trader1")
    assert h.client.get("/llm/budget", headers=trader).status_code == 200
    admin_bearer = h.bearer("admin1")
    response = h.client.post(
        "/admin/users/trader1", json={"disabled": True}, headers=admin_bearer
    )
    assert response.json()["disabled"]
    assert h.client.get("/llm/budget", headers=trader).status_code == 401


def test_an_admin_cant_lock_themselves_out(h):
    bearer = h.bearer("admin1")
    for body in ({"disabled": True}, {"role": "TRADER"}):
        response = h.client.post(
            "/admin/users/admin1", json=body, headers=bearer
        )
        assert response.status_code == 409


# --- sources and LLM settings -------------------------------------------------


def test_admin_edits_source_reputation(h):
    bearer = h.bearer("admin1")
    body = {
        "domain": "pennyrocket.example",
        "tier": "blocked",
        "reputation": 0.05,
        "note": "fake wire",
    }
    saved = h.client.post("/admin/sources", json=body, headers=bearer)
    assert saved.status_code == 200
    assert saved.json()["tier"] == "blocked"
    bad = dict(body, domain="not a domain")
    assert (
        h.client.post("/admin/sources", json=bad, headers=bearer).status_code
        == 422
    )
    bad = dict(body, reputation=1.5)
    assert (
        h.client.post("/admin/sources", json=bad, headers=bearer).status_code
        == 422
    )
    found = h.client.get("/admin/sources?q=penny", headers=bearer).json()
    assert [i["domain"] for i in found["items"]] == ["pennyrocket.example"]


def test_cloud_switches_gate_the_budget(h):
    bearer = h.bearer("admin1")
    shown = h.client.get("/admin/llm", headers=bearer).json()
    assert shown["cloud"] == {"enabled": True, "judge": True, "brief": True}
    assert shown["judge_cloud_model"] == "cloud-openai"
    cap = budget.CloudBudget(h.redis, 20.0)
    assert run(cap.allows("brief"))
    changed = h.client.post("/admin/llm", json={"brief": False}, headers=bearer)
    assert changed.json()["cloud"] == {
        "enabled": True,
        "judge": True,
        "brief": False,
    }
    assert not run(cap.allows("brief"))
    assert run(cap.allows("judge"))
    h.client.post("/admin/llm", json={"enabled": False}, headers=bearer)
    assert not run(cap.allows("judge"))
    assert not run(cap.allows())
    extra = h.client.post("/admin/llm", json={"chat": True}, headers=bearer)
    assert extra.status_code == 422


# --- vendor scorecard and the SLA panel ---------------------------------------


def test_scorecard_for_analysts(h):
    trader = h.bearer("trader1")
    assert h.client.get("/vendor/scorecard", headers=trader).status_code == 403
    analyst = h.bearer("analyst1")
    body = h.client.get("/vendor/scorecard?days=30", headers=analyst).json()
    assert body["count"] == 3
    assert body["items"][0]["feed_date"] == "2026-09-28"
    assert body["contracted"] == 100
    assert body["average_billable"] == 61.0
    assert body["items"][0]["rates"]["duplicate_rate"] == 0.2
    older = h.client.get(
        "/vendor/scorecard?date=2026-09-25", headers=analyst
    ).json()
    assert [i["feed_date"] for i in older["items"]] == [
        "2026-09-25",
        "2026-09-24",
    ]


def test_scorecard_csv(h):
    analyst = h.bearer("analyst1")
    response = h.client.get("/vendor/scorecard.csv", headers=analyst)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.splitlines()
    assert lines[0].startswith("feed_date,received,unique_items")
    assert lines[1].startswith("2026-09-24,100,80")
    assert len(lines) == 4


def test_scorecard_summary_is_cached(h):
    analyst = h.bearer("analyst1")
    first = h.client.get("/vendor/scorecard/summary", headers=analyst).json()
    second = h.client.get("/vendor/scorecard/summary", headers=analyst).json()
    assert first == second
    assert first["text"] == "3 days summarized."
    assert h.summarizer.calls == 1


def test_schedule_shows_every_sla_green(h):
    analyst = h.bearer("analyst1")
    body = h.client.get("/schedule?date=2026-09-28", headers=analyst).json()
    assert body["sla_checked"] == 3
    assert body["sla_green"]
    trader = h.bearer("trader1")
    assert h.client.get("/schedule", headers=trader).status_code == 403


# --- scorecard helpers --------------------------------------------------------


def test_rates_and_fallback_summary():
    row = score_row(datetime.date(2026, 9, 28))
    rates = scorecard.rates(row)
    assert rates["fake_rate"] == 0.125
    assert rates["override_rate"] == 0.2
    assert rates["billable_vs_contract"] == 0.62
    empty = scorecard.rates(dict(row, received=0, unique_items=0, reviewed=0))
    assert empty["duplicate_rate"] == 0.0
    text = scorecard.fallback_summary([row])
    assert "62 billable items per day against 100" in text
    assert scorecard.fallback_summary([]) == "No scorecard days yet."


def test_summary_falls_back_on_advice():
    class Advisor:
        async def ainvoke(self, messages):
            class Answer:
                content = "You should buy NVDA shares now."

            return Answer()

    writer = scorecard.Summarizer(Advisor(), "main-gpu4gb", "skill")
    summary = run(writer.write([score_row(datetime.date(2026, 9, 28))]))
    assert summary.source == "fallback"
