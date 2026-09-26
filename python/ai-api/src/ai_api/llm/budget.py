"""The monthly cloud budget (LLM_MONTHLY_BUDGET_USD, default $20).

Every cloud call's cost comes back from the gateway in the
``x-litellm-response-cost`` header; it is added to a Redis counter per
calendar month (UTC). While the month's spend is below the cap, the judge
may escalate uncertain items to the cloud model; at the cap everything
stays local. A warning is logged once the spend passes 80% (the banner in
the UI comes with the observability work of increment 6).
"""

from __future__ import annotations

import datetime
import logging

from redis import asyncio as aioredis

_log = logging.getLogger(__name__)
_KEY_TTL_S = 40 * 24 * 3600
_WARN_SHARE = 0.8


def _key(now: datetime.datetime | None = None) -> str:
    if now is None:
        now = datetime.datetime.now(datetime.UTC)
    return f"llm:cloud_spend:{now:%Y-%m}"


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

    async def allows(self) -> bool:
        """True while this month's spend is below the cap."""
        return self._cap > 0 and await self.spent() < self._cap

    async def add(self, cost_usd: float) -> float:
        """Adds one call's cost; returns the month's new total."""
        if cost_usd <= 0:
            return await self.spent()
        key = _key()
        total = float(await self._redis.incrbyfloat(key, cost_usd))
        await self._redis.expire(key, _KEY_TTL_S)
        if total >= self._cap:
            _log.warning(
                "cloud budget reached: $%.2f of $%.2f; staying local",
                total,
                self._cap,
            )
        elif total >= _WARN_SHARE * self._cap > total - cost_usd:
            _log.warning(
                "cloud budget at 80%%: $%.2f of $%.2f", total, self._cap
            )
        return total
