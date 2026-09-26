"""The scheduled jobs: each runs ``ai-api`` commands and checks the result.

Every step is an ``ai-api`` command in a subprocess (the same commands as
``make -C python rules`` etc., run as the database owner in this
container), so a step's memory is freed when it ends and the scheduler
never needs a container-engine socket. A step counts as done when the
database says so (the rule, AI or verify run is DONE), not by its exit
code alone: ``ai-api verify`` exits 1 when one item failed, but the run
still ends DONE and the day goes on.

Locks (Redis ``SET NX EX``): ``run:premarket:{date}`` for the day's
pipeline, ``schedule:{job}:{date}`` for the others. With several scheduler
replicas only one runs each job; a failed or skipped job releases its
lock, so a restart (or ``scheduler run JOB``) can try again.
"""

from __future__ import annotations

import asyncio
import collections
from collections.abc import Awaitable, Callable, Sequence
import datetime
import logging
import time
from typing import Protocol

from ai_api import alerts as alerts_lib
from redis import asyncio as aioredis

from scheduler import config
from scheduler import market
from scheduler import metrics
from scheduler import store as store_lib
from scheduler import timeline

_log = logging.getLogger(__name__)

LOCK_TTL_S = 20 * 3600
_T = datetime.time
# The day's pipeline waits for the ingest run until then.
INGEST_WAIT_UNTIL = _T(7, 0)
BRIEF_BY = _T(7, 30)
_VERIFY_TIMEOUT_S = 3 * 3600
_STEP_TIMEOUT_S = 2 * 3600
_TAIL_LINES = 20

Runner = Callable[[Sequence[str], float], Awaitable[tuple[int, str]]]


class Clock(Protocol):
    """The current time in New York."""

    def __call__(self) -> datetime.datetime:
        """Returns an aware datetime."""


async def run_cli(args: Sequence[str], timeout_s: float) -> tuple[int, str]:
    """Runs ``ai-api ARGS``; logs its output; returns (exit code, tail).

    Args:
        args: The ``ai-api`` arguments.
        timeout_s: Killed after this long (exit code 124).

    Returns:
        The exit code and the last lines of its output.
    """
    process = await asyncio.create_subprocess_exec(
        "ai-api",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    tail: collections.deque[str] = collections.deque(maxlen=_TAIL_LINES)

    async def pump() -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode(errors="replace").rstrip()
            tail.append(line)
            _log.info("%s | %s", args[0], line)

    try:
        await asyncio.wait_for(
            asyncio.gather(pump(), process.wait()), timeout_s
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        tail.append(f"killed after {timeout_s:.0f} s")
        return 124, "\n".join(tail)
    return int(process.returncode or 0), "\n".join(tail)


def lock_key(job: str, day: datetime.date) -> str:
    """The Redis lock of a job on a feed date."""
    if job == "pipeline":
        return f"run:premarket:{day.isoformat()}"
    return f"schedule:{job}:{day.isoformat()}"


def _at(day: datetime.date, when: datetime.time) -> datetime.datetime:
    return datetime.datetime.combine(day, when, tzinfo=market.NEW_YORK)


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


class Jobs:
    """Runs one job for one feed date, with its lock and its record."""

    def __init__(
        self,
        settings: config.Settings,
        store: store_lib.Store,
        redis: aioredis.Redis,
        runner: Runner = run_cli,
        clock: Clock = market.now_new_york,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_s: float = 30,
    ) -> None:
        """Wires the job runner.

        Args:
            settings: The settings.
            store: The database access.
            redis: A decoded Redis client (locks, alerts).
            runner: Runs ``ai-api`` commands.
            clock: The current time in New York.
            sleep: Waits between polls.
            poll_s: Seconds between polls of a run's status.
        """
        self._settings = settings
        self._store = store
        self._redis = redis
        self._alerts = alerts_lib.Alerts(redis)
        self._runner = runner
        self._clock = clock
        self._sleep = sleep
        self._poll_s = poll_s

    async def run(
        self,
        job: str,
        day: datetime.date,
        mode: str | None = None,
        force: bool = False,
    ) -> str:
        """Runs ``job`` for ``day``.

        Args:
            job: A job of ``timeline.JOBS``.
            day: The feed date.
            mode: Recorded run mode; None is RUN_MODE.
            force: Take the lock even if another run holds it (manual).

        Returns:
            The recorded status (DONE, FAILED, SKIPPED, OK, BREACHED).

        Raises:
            KeyError: Unknown job.
        """
        slot = timeline.slot(job)
        mode = self._settings.run_mode if mode is None else mode
        if slot.is_sla:
            return await self._sla(job, day, mode)
        key = lock_key(job, day)
        if force:
            await self._redis.delete(key)
        if not await self._redis.set(key, mode, nx=True, ex=LOCK_TTL_S):
            _log.info("%s %s: another run holds %s", job, day, key)
            return "SKIPPED"
        run_id = await self._store.start(day, job, mode)
        started = time.monotonic()
        try:
            status, detail = await self._dispatch(job, day)
        except Exception as e:  # noqa: BLE001 - recorded and alerted.
            _log.exception("%s %s failed", job, day)
            status, detail = "FAILED", repr(e)
        await self._store.finish(run_id, status, detail)
        metrics.job_finished(job, status, time.monotonic() - started)
        _log.info("%s %s: %s %s", job, day, status, detail)
        if status != "DONE":
            await self._redis.delete(key)
        if status == "FAILED":
            await self._alerts.publish(
                alerts_lib.Alert(
                    key=f"job:{job}:{day.isoformat()}",
                    title=f"Scheduled job {job} failed for {day}",
                    severity="critical"
                    if job in ("pipeline", "brief")
                    else "warning",
                    detail=detail,
                )
            )
        return status

    async def _dispatch(self, job: str, day: datetime.date) -> tuple[str, str]:
        d = day.isoformat()
        if job == "pipeline":
            return await self._pipeline(day)
        if job == "brief":
            return await self._brief(day, "morning", timeline.slot(job).until)
        if job == "refresh":
            return await self._brief(day, "refresh", timeline.slot(job).until)
        if job == "retention":
            args = ["retention", "--days", str(self._settings.retention_days)]
        elif job == "corpus":
            args = ["corpus"]
        elif job == "expire":
            args = ["expire", "--date", d]
        elif job == "scorecard":
            args = ["scorecard", "--date", d]
        else:
            raise KeyError(job)
        code, tail = await self._runner(args, _STEP_TIMEOUT_S)
        return ("DONE" if code == 0 else "FAILED"), _last_line(tail)

    async def _wait(
        self,
        check: Callable[[], Awaitable[str | None]],
        done: frozenset[str],
        until: datetime.datetime,
    ) -> str | None:
        """Polls ``check`` until it returns one of ``done`` or ``until``."""
        while True:
            status = await check()
            if status in done or self._clock() >= until:
                return status
            await self._sleep(self._poll_s)

    async def _pipeline(self, day: datetime.date) -> tuple[str, str]:
        """Ingest DONE -> rules -> AI (enrich) -> verify run."""
        d = day.isoformat()
        ingest = await self._wait(
            lambda: self._store.ingest_status(day),
            frozenset({"DONE", "FAILED"}),
            _at(day, INGEST_WAIT_UNTIL),
        )
        if ingest != "DONE":
            return "FAILED", f"ingest run {ingest or 'missing'}"
        await self._alerts.resolve(
            f"sla:ingest:{d}", f"Ingest run of {d} is DONE", "scheduler"
        )
        notes = []
        for step, table in (("rules", "ai.rule_run"), ("enrich", "ai.ai_run")):
            if await self._store.run_status(table, day) == "DONE":
                notes.append(f"{step} already DONE")
                continue
            code, tail = await self._runner(
                [step, "--date", d], _STEP_TIMEOUT_S
            )
            if await self._store.run_status(table, day) != "DONE":
                return "FAILED", f"{step} (exit {code}): {_last_line(tail)}"
            notes.append(f"{step} DONE")
        state = await self._store.verify(day)
        if state.status != "DONE":
            code, tail = await self._runner(
                [
                    "verify",
                    "--date",
                    d,
                    "--timeout",
                    str(_VERIFY_TIMEOUT_S),
                ],
                _VERIFY_TIMEOUT_S + 60,
            )
            state = await self._store.verify(day)
            if state.status != "DONE":
                return "FAILED", f"verify (exit {code}): {_last_line(tail)}"
        notes.append(f"verify DONE ({state.done}/{state.total})")
        for check in ("backlog", "verify"):
            await self._alerts.resolve(
                f"sla:{check}:{d}", f"Verification of {d} is DONE", "scheduler"
            )
        return "DONE", "; ".join(notes)

    async def _brief(
        self,
        day: datetime.date,
        edition: str,
        until: datetime.time | None,
    ) -> tuple[str, str]:
        """Waits for the verify run, then writes the brief edition."""
        d = day.isoformat()
        if (await self._store.brief(day, edition)).status == "DONE":
            return "DONE", f"{edition} brief already published"
        verify = await self._wait(
            lambda: self._verify_status(day),
            frozenset({"DONE", "FAILED"}),
            _at(day, until or _T(23, 59)),
        )
        if verify != "DONE":
            return "FAILED", f"verify run {verify or 'missing'}"
        code, tail = await self._runner(
            ["brief", "--date", d, "--edition", edition, "--timeout", "1800"],
            1900,
        )
        state = await self._store.brief(day, edition)
        if state.status != "DONE":
            return "FAILED", f"brief (exit {code}): {_last_line(tail)}"
        if edition == "morning":
            await self._alerts.resolve(
                f"sla:brief:{d}", f"The brief of {d} is published", "scheduler"
            )
        return "DONE", f"{edition} brief published"

    async def _verify_status(self, day: datetime.date) -> str | None:
        return (await self._store.verify(day)).status

    async def _sla(self, job: str, day: datetime.date, mode: str) -> str:
        """Checks one SLA, records it, alerts when it is breached."""
        d = day.isoformat()
        check = job.removeprefix("sla-")
        ok, detail, title, severity = await self._evaluate(check, day)
        status = "OK" if ok else "BREACHED"
        await self._store.record(day, job, mode, status, detail)
        metrics.sla_checked(check, ok)
        _log.info("%s %s: %s (%s)", job, day, status, detail)
        if not ok:
            await self._alerts.publish(
                alerts_lib.Alert(
                    key=f"sla:{check}:{d}",
                    title=title,
                    severity=severity,
                    detail=detail,
                )
            )
        return status

    async def _evaluate(
        self, check: str, day: datetime.date
    ) -> tuple[bool, str, str, str]:
        """(ok, detail, alert title, severity) of one SLA check."""
        if check == "ingest":
            status = await self._store.ingest_status(day)
            return (
                status == "DONE",
                f"ingest run {status or 'missing'}",
                f"Ingest run of {day} missing at 06:15 ET",
                "critical",
            )
        if check == "backlog":
            state = await self._store.verify(day)
            limit = self._settings.backlog_max
            return (
                state.backlog <= limit,
                f"{state.backlog} verify jobs queued (limit {limit}),"
                f" run {state.status or 'not started'}",
                f"Verification backlog {state.backlog} > {limit} at 06:30 ET",
                "warning",
            )
        if check == "verify":
            state = await self._store.verify(day)
            return (
                state.status == "DONE",
                f"verify run {state.status or 'missing'}"
                f" ({state.done}/{state.total})",
                f"Verification of {day} not finished by 07:00 ET",
                "critical",
            )
        if check == "brief":
            state = await self._store.brief(day, "morning")
            on_time = (
                state.status == "DONE"
                and state.finished_at is not None
                and state.finished_at <= _at(day, BRIEF_BY)
            )
            when = (
                "not published"
                if state.finished_at is None
                else state.finished_at.astimezone(market.NEW_YORK).strftime(
                    "published %H:%M ET"
                )
            )
            return (
                on_time,
                f"morning brief {state.status or 'missing'}, {when}",
                f"Brief of {day} not published by 07:30 ET",
                "critical",
            )
        raise KeyError(check)
