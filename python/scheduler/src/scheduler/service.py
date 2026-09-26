"""The scheduler service: APScheduler on the New York timeline.

One ``AsyncIOScheduler`` job per slot of ``timeline.TIMELINE`` (cron on
the slot's time, in America/New_York). Each firing checks the NYSE
calendar, then runs the job (``jobs.Jobs``). At startup, jobs whose time
has passed but whose window is still open run at once (catch-up), so a
restart at 06:20 still gets the day done. A heartbeat every 30 s touches a
file (the container healthcheck) and a metric.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import pathlib
import signal
import time

from apscheduler.schedulers import asyncio as aps_asyncio
from apscheduler.triggers import cron
from redis import asyncio as aioredis

from scheduler import config
from scheduler import jobs as jobs_lib
from scheduler import market
from scheduler import metrics
from scheduler import ops
from scheduler import store as store_lib
from scheduler import timeline

_log = logging.getLogger(__name__)
_HEARTBEAT_S = 30
# A job that fires this late (the machine slept) still runs.
_MISFIRE_GRACE_S = 15 * 60


class Service:
    """Fires the timeline's jobs on trading days."""

    def __init__(
        self,
        settings: config.Settings,
        jobs: jobs_lib.Jobs,
        store: store_lib.Store,
        calendar: market.Calendar,
        clock: jobs_lib.Clock = market.now_new_york,
    ) -> None:
        """Wires the service."""
        self._settings = settings
        self._jobs = jobs
        self._store = store
        self._calendar = calendar
        self._clock = clock
        self._slots = timeline.active(settings.production, settings.corpus)
        self._running: set[asyncio.Task[str]] = set()

    @property
    def slots(self) -> tuple[timeline.Slot, ...]:
        """The slots of this run mode."""
        return self._slots

    def applies(self, slot: timeline.Slot, day: datetime.date) -> bool:
        """True when ``slot`` runs on ``day`` (the NYSE calendar)."""
        return slot.every_day or self._calendar.is_trading_day(day)

    async def fire(self, job: str) -> str:
        """Runs ``job`` for today (New York) if today is its kind of day."""
        slot = timeline.slot(job)
        day = self._clock().date()
        if not self.applies(slot, day):
            _log.info("%s: %s is not a trading day", job, day)
            return "SKIPPED"
        return await self._jobs.run(job, day)

    async def catch_up(self) -> list[str]:
        """Starts the jobs that were missed today; returns their names."""
        now = self._clock()
        started = []
        for slot in timeline.catch_up(self._slots, now.time()):
            if not self.applies(slot, now.date()):
                continue
            if await self._store.finished_today(now.date(), slot.job):
                continue
            _log.info("catch-up: %s (due %s)", slot.job, slot.at)
            task = asyncio.create_task(self.fire(slot.job))
            self._running.add(task)
            task.add_done_callback(self._running.discard)
            started.append(slot.job)
        return started

    def schedule(self, scheduler: aps_asyncio.AsyncIOScheduler) -> None:
        """Adds one cron job per slot."""
        for slot in self._slots:
            scheduler.add_job(
                self.fire,
                cron.CronTrigger(
                    day_of_week="*" if slot.every_day else "mon-fri",
                    hour=slot.at.hour,
                    minute=slot.at.minute,
                    timezone=market.NEW_YORK,
                ),
                args=[slot.job],
                id=slot.job,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=_MISFIRE_GRACE_S,
            )


def _heartbeat(path: pathlib.Path) -> None:
    path.touch()
    metrics.HEARTBEAT.set(time.time())


async def serve(settings: config.Settings) -> None:
    """Runs until SIGTERM or SIGINT.

    Args:
        settings: The settings.
    """
    redis = aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        decode_responses=True,
        socket_timeout=10,
    )
    store = store_lib.PostgresStore(settings.owner.dsn(application="scheduler"))
    calendar = market.Calendar()
    service = Service(
        settings, jobs_lib.Jobs(settings, store, redis), store, calendar
    )
    metrics.REGISTRY.register(
        ops.OpsCollector(
            settings.owner.dsn(application="scheduler-metrics"),
            redis.Redis(
                host=settings.redis_host,
                password=settings.redis_password,
                decode_responses=True,
                socket_timeout=3,
            ),
            settings.monthly_budget_usd,
        )
    )
    metrics.serve(settings.metrics_port)
    scheduler = aps_asyncio.AsyncIOScheduler(timezone=market.NEW_YORK)
    service.schedule(scheduler)
    scheduler.start()
    today = market.now_new_york().date()
    _log.info(
        "scheduler: RUN_MODE=%s, %d jobs (%s); %s is %sa trading day",
        settings.run_mode,
        len(service.slots),
        ", ".join(s.job for s in service.slots),
        today,
        "" if calendar.is_trading_day(today) else "not ",
    )
    await service.catch_up()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    beat = pathlib.Path(settings.heartbeat_file)
    try:
        while not stop.is_set():
            _heartbeat(beat)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), _HEARTBEAT_S)
    finally:
        scheduler.shutdown(wait=False)
        await redis.aclose()
        _log.info("scheduler stopped")
