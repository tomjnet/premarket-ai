"""The monthly cloud budget (LLM_MONTHLY_BUDGET_USD, default $20).

Every cloud call's cost comes back from the gateway in the
``x-litellm-response-cost`` header; it is added to a Redis counter per
calendar month (UTC). While the month's spend is below the cap, the judge
may escalate uncertain items to the cloud model; at the cap everything
stays local. The call that crosses 80% or the cap also publishes an alert
to the operations banner (increment 6), and every user sees the "Cloud
budget reached, running local" banner (``GET /llm/budget``).
"""

from __future__ import annotations

import datetime
import logging

from redis import asyncio as aioredis

from ai_api import alerts
from ai_api.llm import switches

_log = logging.getLogger(__name__)
_KEY_TTL_S = 40 * 24 * 3600
_WARN_SHARE = 0.8


def _key(now: datetime.datetime | None = None) -> str:
    if now is None:
        now = datetime.datetime.now(datetime.UTC)
    return f"llm:cloud_spend:{now:%Y-%m}"


def day_key(day: datetime.date) -> str:
    """The Redis key of one day's spend (UTC; the scorecard's cost)."""
    return f"llm:cloud_spend_day:{day.isoformat()}"


class CloudBudget:
    """The month's cloud spend in Redis."""

    def __init__(self, redis: aioredis.Redis, monthly_usd: float) -> None:
        """Uses ``redis`` (decoded responses) and the monthly cap."""
        self._redis = redis
        self._cap = monthly_usd

    @property
    def cap_usd(self) -> float:
        """The monthly cap."""
        return self._cap

    async def spent(self) -> float:
        """This month's spend in dollars."""
        value = await self._redis.get(_key())
        return 0.0 if value is None else float(value)

    async def allows(self, task: str | None = None) -> bool:
        """True while cloud calls are switched on and under the cap.

        Args:
            task: ``judge`` or ``brief``: its admin switch must be on too
                (``llm.switches``); None checks only the master switch.

        Returns:
            Whether a cloud call may be made now.
        """
        if self._cap <= 0:
            return False
        names = ["enabled"] if task is None else ["enabled", task]
        found = await self._redis.mget([switches.redis_key(n) for n in names])
        if "off" in found:
            return False
        return await self.spent() < self._cap

    async def spent_on(self, day: datetime.date) -> float:
        """One day's spend in dollars (UTC day)."""
        value = await self._redis.get(day_key(day))
        return 0.0 if value is None else float(value)

    async def add(self, cost_usd: float) -> float:
        """Adds one call's cost; returns the month's new total."""
        if cost_usd <= 0:
            return await self.spent()
        now = datetime.datetime.now(datetime.UTC)
        key = _key(now)
        total = float(await self._redis.incrbyfloat(key, cost_usd))
        await self._redis.expire(key, _KEY_TTL_S)
        today = day_key(now.date())
        await self._redis.incrbyfloat(today, cost_usd)
        await self._redis.expire(today, _KEY_TTL_S)
        month = key.rsplit(":", 1)[-1]
        if total >= self._cap > total - cost_usd:
            _log.warning(
                "cloud budget reached: $%.2f of $%.2f; staying local",
                total,
                self._cap,
            )
            await self._alert(
                f"budget:100:{month}",
                f"Cloud budget reached (${total:.2f} of ${self._cap:.2f}):"
                " running local",
                "critical",
            )
        elif total >= _WARN_SHARE * self._cap > total - cost_usd:
            _log.warning(
                "cloud budget at 80%%: $%.2f of $%.2f", total, self._cap
            )
            await self._alert(
                f"budget:80:{month}",
                f"Cloud budget at 80% (${total:.2f} of ${self._cap:.2f})",
                "warning",
            )
        return total

    async def _alert(self, key: str, title: str, severity: str) -> None:
        try:
            await alerts.Alerts(self._redis).publish(
                alerts.Alert(
                    key=key, title=title, severity=severity, source="budget"
                ),
                dedup_s=_KEY_TTL_S,
            )
        except Exception as e:  # noqa: BLE001 - the call already happened.
            _log.warning("budget alert not published: %r", e)
