"""Operational alerts: the Redis Stream ``alerts`` behind the UI banner.

Three sources publish here (increment 6):

- the scheduler's SLA checks (ingest missing at 06:15, queue backlog at
  06:30, verification late at 07:00, brief not published by 07:30);
- Grafana alert rules, through the webhook ``POST /alerts/grafana``
  (worker down, cloud budget at 80%);
- the cloud budget itself when a call crosses 80% or 100% of the cap.

``GET /alerts/stream`` forwards the stream to ANALYST and ADMIN browsers as
server-sent events (the banner). A stream keeps its entries, so a browser
that reconnects replays what it missed. Delivery is the banner only: no
e-mail, chat or pager in the lab.

An alert is identified by its ``key`` (for example
``sla:verify:2026-09-28``). Publishing the same key and status again within
``dedup_s`` does nothing, so a check that runs every minute or a Grafana
rule that re-notifies doesn't flood the banner. ``resolved`` clears it.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
from typing import Any

from redis import asyncio as aioredis

STREAM = "alerts"
SEVERITIES = ("info", "warning", "critical")
STATUSES = ("firing", "resolved")
# Seven days of alerts at most; the banner shows the last day's.
_MAX_LEN = 500
_TTL_S = 7 * 24 * 3600
_DEFAULT_DEDUP_S = 6 * 3600


@dataclasses.dataclass(frozen=True)
class Alert:
    """One alert event.

    Attributes:
        key: Identifies the condition (the same key updates the banner).
        title: One line for the banner.
        severity: ``info``, ``warning`` or ``critical``.
        status: ``firing`` or ``resolved``.
        detail: More text (the check's numbers).
        source: ``scheduler``, ``grafana`` or ``budget``.
        at: When it happened (UTC); None means now.
    """

    key: str
    title: str
    severity: str = "warning"
    status: str = "firing"
    detail: str = ""
    source: str = "scheduler"
    at: datetime.datetime | None = None

    def __post_init__(self) -> None:
        """Checks the enumerations and lengths.

        Raises:
            ValueError: A field is invalid.
        """
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if not self.key or len(self.key) > 200:
            raise ValueError("key must be 1 to 200 characters")
        if not self.title or len(self.title) > 200:
            raise ValueError("title must be 1 to 200 characters")

    def to_json(self) -> dict[str, Any]:
        """The event's data (JSON-serializable)."""
        at = self.at
        if at is None:
            at = datetime.datetime.now(datetime.UTC)
        return {
            "key": self.key,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "detail": self.detail[:1000],
            "source": self.source,
            "at": at.astimezone(datetime.UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }


class Alerts:
    """Publishes and reads the ``alerts`` stream (a decoded Redis client)."""

    def __init__(self, redis: aioredis.Redis) -> None:
        """Uses ``redis`` (decode_responses=True)."""
        self._redis = redis

    async def publish(
        self, alert: Alert, dedup_s: int = _DEFAULT_DEDUP_S
    ) -> str | None:
        """Appends the alert unless the same key and status is recent.

        Args:
            alert: The alert.
            dedup_s: Seconds during which the same key and status is
                published only once.

        Returns:
            The stream id, or None when it was a duplicate.
        """
        marker = f"alert:last:{alert.key}"
        previous = await self._redis.set(
            marker, alert.status, ex=dedup_s, get=True
        )
        if previous == alert.status:
            return None
        event_id = await self._redis.xadd(
            STREAM,
            {"kind": "alert", "data": json.dumps(alert.to_json())},
            maxlen=_MAX_LEN,
            approximate=True,
        )
        await self._redis.expire(STREAM, _TTL_S)
        return event_id

    async def resolve(self, key: str, title: str, source: str) -> str | None:
        """Publishes ``resolved`` for ``key`` if it is firing.

        Args:
            key: The alert's key.
            title: The banner line of the resolution.
            source: Who resolved it.

        Returns:
            The stream id, or None when it wasn't firing.
        """
        if await self._redis.get(f"alert:last:{key}") != "firing":
            return None
        return await self.publish(
            Alert(
                key=key,
                title=title,
                severity="info",
                status="resolved",
                source=source,
            )
        )

    async def read(
        self, after: str = "0", block_ms: int = 15_000
    ) -> list[tuple[str, dict[str, Any]]]:
        """Alerts after the stream id ``after`` (``0``: from the start).

        Args:
            after: The last id the client has.
            block_ms: How long to wait for a new one (0: don't wait).

        Returns:
            (id, alert data) pairs, oldest first; empty on a timeout.
        """
        found = await self._redis.xread(
            {STREAM: after},
            count=100,
            block=block_ms if block_ms > 0 else None,
        )
        events = []
        for _, entries in found or []:
            for event_id, fields in entries:
                events.append((event_id, json.loads(fields["data"])))
        return events

    async def since(
        self, hours: float = 24
    ) -> list[tuple[str, dict[str, Any]]]:
        """The alerts of the last ``hours`` (for a banner that connects)."""
        start_ms = int(
            (
                datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(hours=hours)
            ).timestamp()
            * 1000
        )
        found = await self._redis.xrange(STREAM, min=f"{start_ms}-0")
        return [(i, json.loads(f["data"])) for i, f in found]


def active(events: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """The alerts still firing: the latest event of each key, if firing.

    Args:
        events: (id, alert) pairs, oldest first.

    Returns:
        The firing alerts, newest first.
    """
    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    for event_id, data in events:
        latest[data["key"]] = (event_id, data)
    firing = [
        dict(data, id=event_id)
        for event_id, data in latest.values()
        if data["status"] == "firing"
    ]
    return sorted(firing, key=lambda a: a["id"], reverse=True)
