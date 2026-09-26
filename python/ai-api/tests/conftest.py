"""Test doubles: in-memory users and news, fakeredis for sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
import datetime
from typing import Any

import fakeredis
from fastapi import testclient
import pytest

from ai_api import app
from ai_api import config
from ai_api import deps
from ai_api import news
from ai_api import passwords
from ai_api import sessions
from ai_api import users

PASSWORD = "correct-horse-battery"
ORIGIN = "http://localhost:8080"
DAY = datetime.date(2026, 9, 24)
UTC = datetime.UTC


class FakeUsers:
    """In-memory users; records audit events."""

    def __init__(self) -> None:
        """Seeds trader1, analyst1, admin1 and the disabled gone1."""
        hashed = passwords.hash_password(PASSWORD)
        self.users = {
            "trader1": users.User("trader1", "TRADER", hashed),
            "analyst1": users.User("analyst1", "ANALYST", hashed),
            "admin1": users.User("admin1", "ADMIN", hashed),
            "gone1": users.User("gone1", "TRADER", hashed, disabled=True),
        }
        self.events: list[tuple[str, str | None]] = []

    async def get(self, username: str) -> users.User | None:
        """Returns the user or None."""
        return self.users.get(username)

    async def audit(
        self,
        action: str,
        actor: str | None,
        client_ip: str | None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Records the action and actor."""
        del client_ip, detail
        self.events.append((action, actor))


def make_row(number: int, **overrides: Any) -> dict[str, Any]:
    row = {
        "id": 2000 + number,
        "vendor_item_id": f"VND-20260924-{number:03d}",
        "feed_date": DAY,
        "headline": f"[SYNTHETIC] Headline {number}",
        "body": "NEW YORK, September 24 (Acme Market Wire) -- Body text. " * 3,
        "source_url": "https://acme-market-wire.example/a",
        "source_domain": "acme-market-wire.example",
        "published_at": datetime.datetime(2026, 9, 24, 8, number, tzinfo=UTC),
        "tickers": ["AAPL"],
        "synthetic": True,
        "is_dup": False,
        "dup_of": None,
        "reason_codes": [],
        "dup_type": None,
        "copies": 0,
        "rules_checked": True,
        "summary": f"Apple said item {number} happened.",
        "sentiment": "neutral",
        "ai_status": "DONE",
        "summary_source": "llm",
        "ai_evidence": [],
        "ai_model": "main-gpu4gb",
        "prompt_version": "enrich-v1",
        "enriched_at": datetime.datetime(2026, 9, 24, 10, 5, tzinfo=UTC),
        "verdict": "VERIFIED",
        "confidence": 0.91,
        "review_status": None,
        "verdict_source": "ai",
        "evidence": [
            {
                "check": "entity",
                "code": None,
                "message": "AAPL is Apple Inc. in the SEC ticker registry.",
            }
        ],
    }
    row.update(overrides)
    return row


class FakeNews:
    """Three items of 2026-09-24 (one duplicate), a DONE run and rule run."""

    def __init__(self) -> None:
        """Creates the rows and the runs."""
        self.rows = [
            make_row(1, copies=1),
            make_row(
                2,
                tickers=["QVXH"],
                reason_codes=["FAKE_COMPANY", "FAKE_TICKER"],
                verdict="FAKE",
                confidence=0.97,
            ),
            make_row(
                3,
                is_dup=True,
                dup_of="VND-20260924-001",
                dup_type="near",
                verdict_source="inherited",
            ),
        ]
        self.rule_run: dict[str, Any] | None = {
            "status": "DONE",
            "finished_at": datetime.datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
            "items": 3,
            "duplicates": 1,
            "flagged": 1,
        }
        self.ai_run: dict[str, Any] | None = {
            "status": "DONE",
            "finished_at": datetime.datetime(2026, 9, 24, 10, 9, tzinfo=UTC),
            "items": 2,
            "paraphrases": 0,
            "conflicts": 0,
            "summarized": 2,
            "fallbacks": 0,
            "failed": 0,
            "model": "main-gpu4gb",
        }
        self.extractions: dict[int, list[dict[str, Any]]] = {
            2001: [
                {
                    "kind": "entity",
                    "seq": 0,
                    "text": "Apple Inc.",
                    "ticker": "AAPL",
                },
                {
                    "kind": "claim",
                    "seq": 0,
                    "text": "Apple said X.",
                    "ticker": None,
                },
            ]
        }
        self.verify_run: dict[str, Any] | None = make_verify_run()
        self.verifications: dict[int, tuple] = {
            2001: (
                make_verification(),
                [
                    {
                        "seq": 1,
                        "check": "entity",
                        "code": None,
                        "message": "SEC registry: AAPL is Apple Inc.",
                        "source": "registry",
                        "url": None,
                        "title": None,
                    }
                ],
                None,
            )
        }
        self.queries: list[news.NewsQuery] = []
        self.run: dict[str, Any] | None = {
            "run_id": 42,
            "status": "DONE",
            "started_at": datetime.datetime(
                2026, 9, 24, 9, 30, 2, 123456, tzinfo=UTC
            ),
            "finished_at": datetime.datetime(2026, 9, 24, 9, 30, 5, tzinfo=UTC),
            "rows_received": 3,
            "dups": 1,
        }

    async def latest_run(self, day: datetime.date) -> dict[str, Any] | None:
        """Returns the run for DAY only."""
        return self.run if day == DAY else None

    async def latest_rule_run(
        self, day: datetime.date
    ) -> dict[str, Any] | None:
        """Returns the rule run for DAY only."""
        return self.rule_run if day == DAY else None

    async def latest_ai_run(self, day: datetime.date) -> dict[str, Any] | None:
        """Returns the AI run for DAY only."""
        return self.ai_run if day == DAY else None

    async def extraction(self, item_id: int) -> list[dict[str, Any]]:
        """Returns the extraction rows of one item."""
        return self.extractions.get(item_id, [])

    async def latest_verify_run(
        self, day: datetime.date
    ) -> dict[str, Any] | None:
        """Returns the verify run for DAY only."""
        return self.verify_run if day == DAY else None

    async def verification(self, item_id: int) -> tuple:
        """The verification, evidence and review of one item."""
        return self.verifications.get(item_id, ({}, [], None))

    async def items(self, query: news.NewsQuery) -> list[dict[str, Any]]:
        """Applies the date, duplicate and ticker filters."""
        self.queries.append(query)
        return [
            row
            for row in self.rows
            if row["feed_date"] == query.day
            and (query.include_duplicates or not row["is_dup"])
            and (query.ticker is None or query.ticker in row["tickers"])
            and (query.verdict is None or row["verdict"] == query.verdict)
            and (not query.pending_review or row["review_status"] == "PENDING")
        ]

    async def item(self, item_id: int) -> dict[str, Any] | None:
        """Returns one row by id."""
        return next((r for r in self.rows if r["id"] == item_id), None)


def make_verify_run(**overrides: Any) -> dict[str, Any]:
    run = {
        "run_id": 7,
        "feed_date": DAY,
        "status": "DONE",
        "requested_by": "analyst1",
        "requested_at": datetime.datetime(2026, 9, 24, 10, 10, tzinfo=UTC),
        "started_at": datetime.datetime(2026, 9, 24, 10, 10, 1, tzinfo=UTC),
        "finished_at": datetime.datetime(2026, 9, 24, 10, 20, tzinfo=UTC),
        "total": 2,
        "done": 2,
        "failed": 0,
        "verified": 1,
        "unverified": 0,
        "misleading": 0,
        "fake": 1,
        "pending_review": 0,
        "escalated": 0,
        "model": "main-gpu4gb",
        "error": None,
    }
    run.update(overrides)
    return run


def make_verification(**overrides: Any) -> dict[str, Any]:
    found = {
        "news_id": 11,
        "status": "DONE",
        "verdict": "VERIFIED",
        "confidence": 0.91,
        "reason_codes": [],
        "rationale": "From a trusted-tier newswire [E1].",
        "rule_verdict": "VERIFIED",
        "rule_confidence": 0.75,
        "judge_verdict": "VERIFIED",
        "judge_confidence": 0.9,
        "judge_model": "main-gpu4gb",
        "escalated": False,
        "review_status": None,
        "review_reasons": [],
        "impact": "high",
        "impact_score": 0.98,
        "prompt_version": "verify-v1",
        "verified_at": datetime.datetime(2026, 9, 24, 10, 15, tzinfo=UTC),
    }
    found.update(overrides)
    return found


async def _ping() -> None:
    return None


def make_settings(**overrides: Any) -> config.Settings:
    values: dict[str, Any] = {
        "database": config.Database("db", 5432, "premarket", "u", "p"),
        "redis_host": "redis",
        "redis_password": "x" * 32,
        "jwt_secret": "s" * 48,
        "allowed_origins": frozenset({ORIGIN}),
        "login_max_failures": 3,
    }
    values.update(overrides)
    return config.Settings(**values)


class Harness:
    """The app wired to fakes, with a TestClient."""

    def __init__(self, settings: config.Settings) -> None:
        """Builds the fakes and the client."""
        self.settings = settings
        self.users = FakeUsers()
        self.news = FakeNews()
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.sessions = sessions.SessionStore(
            self.redis,
            ttl_s=settings.refresh_token_ttl_s,
            grace_s=settings.refresh_grace_s,
            max_failures=settings.login_max_failures,
            lockout_s=settings.login_lockout_s,
        )
        services = deps.Services(
            settings=settings,
            users=self.users,
            news=self.news,
            sessions=self.sessions,
            ping=_ping,
        )
        self.client = testclient.TestClient(
            app.create_app(services=services), base_url="https://testserver"
        )

    def session_ids(self) -> list[str]:
        """Returns the ids of the live sessions."""

        async def scan() -> list[str]:
            return [
                key.split(":")[1]
                async for key in self.redis.scan_iter("session:*")
                if key.count(":") == 1
            ]

        return asyncio.run(scan())

    def login(self, username: str = "trader1") -> str:
        """Logs in and returns the access token."""
        response = self.client.post(
            "/auth/login",
            data={"username": username, "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]


@pytest.fixture
def harness() -> Iterator[Harness]:
    h = Harness(make_settings())
    with h.client:
        yield h
