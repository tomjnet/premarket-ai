"""Today's operations as Prometheus gauges, read on every scrape.

The Grafana dashboard's business panels come from here (the scheduler has
the owner connection and Redis anyway). Each scrape runs a few small
queries for today's feed date (New York):

- ``premarket_items{kind}``: today's items: ``all``, ``unique``.
- ``premarket_duplicates{type}``: duplicate links by type (dedup hits).
- ``premarket_verdicts{verdict}``: the verdict mix.
- ``premarket_review_pending``: items waiting for an analyst.
- ``premarket_verify_backlog`` / ``premarket_verify_done`` /
  ``premarket_verify_total``: the newest verify run's progress.
- ``premarket_queue_pending``: jobs on the Redis Stream not yet
  acknowledged by a worker (consumer group ``ai-worker``).
- ``premarket_brief_published_timestamp_seconds{edition}``.
- ``premarket_llm_cloud_spend_usd{period}`` (``month``, ``today``) and
  ``premarket_llm_cloud_budget_usd``: the cloud budget (the 80% alert).

A failing query is logged and its gauges are left out of that scrape; the
dashboard shows a gap, not a wrong number.
"""

from __future__ import annotations

from collections.abc import Iterator
import datetime
import logging
from typing import Any

from ai_api.llm import budget
from prometheus_client import core
from prometheus_client import registry
import psycopg
import redis

from scheduler import market

_log = logging.getLogger(__name__)
_QUEUE = "premarket:verify"
_GROUP = "ai-worker"

_ITEMS_SQL = """
SELECT count(*) AS all_items,
       count(*) FILTER (WHERE d.news_id IS NULL) AS unique_items
FROM ai.news_item n LEFT JOIN ai.duplicate_link d ON d.news_id = n.id
WHERE n.feed_date = %(day)s
"""
_DUPLICATES_SQL = """
SELECT d.dup_type, count(*) FROM ai.duplicate_link d
JOIN ai.news_item n ON n.id = d.news_id
WHERE n.feed_date = %(day)s GROUP BY 1
"""
_VERDICTS_SQL = """
SELECT coalesce(v.verdict::text, 'NONE'), count(*),
       count(*) FILTER (WHERE v.review_status = 'PENDING')
FROM ai.verification v JOIN ai.news_item n ON n.id = v.news_id
WHERE n.feed_date = %(day)s GROUP BY 1
"""
_VERIFY_SQL = """
SELECT status, total, done FROM ai.verify_run WHERE feed_date = %(day)s
ORDER BY requested_at DESC LIMIT 1
"""
_BRIEF_SQL = """
SELECT edition, extract(epoch FROM max(finished_at)) FROM ai.brief
WHERE feed_date = %(day)s AND status = 'DONE' GROUP BY 1
"""


def _gauge(
    name: str, text: str, labels: tuple[str, ...] = ()
) -> core.GaugeMetricFamily:
    return core.GaugeMetricFamily(name, text, labels=list(labels))


class OpsCollector(registry.Collector):
    """A ``prometheus_client`` collector over Postgres and Redis."""

    def __init__(self, dsn: str, redis_client: Any, cap_usd: float) -> None:
        """Reads with ``dsn`` (owner) and a sync, decoded Redis client."""
        self._dsn = dsn
        self._redis = redis_client
        self._cap = cap_usd

    def collect(self) -> Iterator[core.Metric]:
        """One scrape."""
        day = market.now_new_york().date()
        try:
            yield from self._database(day)
        except psycopg.Error as e:
            _log.warning("ops metrics: database: %r", e)
        try:
            yield from self._redis_metrics()
        except redis.RedisError as e:
            _log.warning("ops metrics: redis: %r", e)

    def _database(self, day: datetime.date) -> Iterator[core.Metric]:
        params = {"day": day}
        with psycopg.connect(self._dsn, connect_timeout=3) as conn:
            items = conn.execute(_ITEMS_SQL, params).fetchone()
            duplicates = conn.execute(_DUPLICATES_SQL, params).fetchall()
            verdicts = conn.execute(_VERDICTS_SQL, params).fetchall()
            run = conn.execute(_VERIFY_SQL, params).fetchone()
            briefs = conn.execute(_BRIEF_SQL, params).fetchall()
        gauge = _gauge("premarket_items", "Today's vendor items.", ("kind",))
        gauge.add_metric(["all"], items[0])
        gauge.add_metric(["unique"], items[1])
        yield gauge
        gauge = _gauge(
            "premarket_duplicates", "Today's duplicate links.", ("type",)
        )
        found = dict(duplicates)
        for kind in ("url", "exact", "near", "paraphrase"):
            gauge.add_metric([kind], found.get(kind, 0))
        yield gauge
        gauge = _gauge(
            "premarket_verdicts", "Today's verdict mix.", ("verdict",)
        )
        counted = {verdict: count for verdict, count, _ in verdicts}
        for verdict in ("VERIFIED", "UNVERIFIED", "MISLEADING", "FAKE"):
            gauge.add_metric([verdict], counted.get(verdict, 0))
        yield gauge
        gauge = _gauge(
            "premarket_review_pending", "Items waiting for an analyst."
        )
        gauge.add_metric([], sum(pending for _, _, pending in verdicts))
        yield gauge
        status, total, done = run if run is not None else (None, 0, 0)
        running = status in ("QUEUED", "RUNNING")
        for name, value, text in (
            ("premarket_verify_total", total, "Items of the verify run."),
            ("premarket_verify_done", done, "Items verified so far."),
            (
                "premarket_verify_backlog",
                max(total - done, 0) if running else 0,
                "Items still queued while the verify run runs.",
            ),
        ):
            gauge = _gauge(name, text)
            gauge.add_metric([], value)
            yield gauge
        gauge = _gauge(
            "premarket_brief_published_timestamp_seconds",
            "When today's brief edition was published (Unix time).",
            ("edition",),
        )
        for edition, finished in briefs:
            gauge.add_metric([edition], float(finished))
        yield gauge

    def _redis_metrics(self) -> Iterator[core.Metric]:
        gauge = _gauge(
            "premarket_queue_pending",
            "Verify jobs on the stream not yet acknowledged.",
        )
        try:
            pending = self._redis.xpending(_QUEUE, _GROUP)["pending"]
        except redis.ResponseError:
            pending = 0  # no stream or group yet
        gauge.add_metric([], pending)
        yield gauge
        now = datetime.datetime.now(datetime.UTC)
        month = self._redis.get(f"llm:cloud_spend:{now:%Y-%m}")
        today = self._redis.get(budget.day_key(now.date()))
        gauge = _gauge(
            "premarket_llm_cloud_spend_usd",
            "Cloud LLM spend (UTC month and day).",
            ("period",),
        )
        gauge.add_metric(["month"], float(month or 0))
        gauge.add_metric(["today"], float(today or 0))
        yield gauge
        gauge = _gauge(
            "premarket_llm_cloud_budget_usd",
            "The monthly cloud cap (LLM_MONTHLY_BUDGET_USD).",
        )
        gauge.add_metric([], self._cap)
        yield gauge
