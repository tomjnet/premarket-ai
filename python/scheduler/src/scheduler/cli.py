"""scheduler command line.

Usage:

    scheduler serve                      the service (compose: scheduler)
    scheduler health                     exit 0 if the loop is alive
    scheduler plan [--date D]            the day's timeline for RUN_MODE
    scheduler run JOB [--date D] [--force]
                                         run one job now (recorded as
                                         manual): pipeline, brief, sla-...
    scheduler status [--date D]          the day's job runs and SLA checks

``run`` takes the job's lock like the service does; ``--force`` takes it
even when another run holds it (after a crash).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import os
import pathlib
import sys
import time

from ai_api import config as ai_config
import psycopg

from scheduler import config
from scheduler import market
from scheduler import timeline

_HEALTHY_WITHIN_S = 120


def _health(settings_file: str) -> int:
    path = pathlib.Path(settings_file)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError as e:
        print(f"no heartbeat: {e}", file=sys.stderr)
        return 1
    if age > _HEALTHY_WITHIN_S:
        print(f"heartbeat {age:.0f} s old", file=sys.stderr)
        return 1
    return 0


def _plan(settings: config.Settings, day: datetime.date) -> int:
    calendar = market.Calendar()
    trading = calendar.is_trading_day(day)
    print(
        f"{day} ({day:%A}): {'trading day' if trading else 'no NYSE session'};"
        f" RUN_MODE={settings.run_mode}"
    )
    for slot in timeline.TIMELINE:
        runs = slot in timeline.active(settings.production, settings.corpus)
        if runs and not slot.every_day and not trading:
            runs = False
        until = "" if slot.until is None else f" (until {slot.until:%H:%M})"
        mark = "run " if runs else "skip"
        print(f"  {slot.at:%H:%M}  {mark}  {slot.job}{until}")
    if not trading:
        print(f"  next trading day: {calendar.next_trading_day(day)}")
    return 0


def _run(
    settings: config.Settings, job: str, day: datetime.date, force: bool
) -> int:
    from redis import asyncio as aioredis  # noqa: PLC0415

    from scheduler import jobs as jobs_lib  # noqa: PLC0415
    from scheduler import store as store_lib  # noqa: PLC0415

    async def once() -> str:
        redis = aioredis.Redis(
            host=settings.redis_host,
            password=settings.redis_password,
            decode_responses=True,
        )
        try:
            store = store_lib.PostgresStore(
                settings.owner.dsn(application="scheduler")
            )
            jobs = jobs_lib.Jobs(settings, store, redis)
            return await jobs.run(job, day, mode="manual", force=force)
        finally:
            await redis.aclose()

    status = asyncio.run(once())
    print(f"{job} {day}: {status}")
    return 0 if status in ("DONE", "OK", "SKIPPED") else 1


def _status(settings: config.Settings, day: datetime.date) -> int:
    with psycopg.connect(settings.owner.dsn(application="scheduler")) as conn:
        found = conn.execute(
            "SELECT job, run_mode, status, to_char(started_at AT TIME ZONE"
            " 'America/New_York', 'HH24:MI:SS'), to_char(finished_at AT TIME"
            " ZONE 'America/New_York', 'HH24:MI:SS'), detail"
            " FROM ai.schedule_run WHERE feed_date = %s ORDER BY started_at",
            (day,),
        ).fetchall()
    if not found:
        print(f"{day}: no scheduled runs")
        return 0
    for job, mode, status, started, finished, detail in found:
        print(
            f"{started or '':>8} {finished or '':>8}  {job:<12} {status:<9}"
            f" {mode:<10} {detail[:80]}"
        )
    sla = [row for row in found if row[0].startswith("sla-")]
    breached = [row[0] for row in sla if row[2] != "OK"]
    if sla:
        print(
            "SLA: every check green"
            if not breached
            else f"SLA: breached {', '.join(breached)}"
        )
    return 1 if breached else 0


def main(argv: list[str] | None = None) -> int:
    """Runs one scheduler command.

    Args:
        argv: The arguments; None means ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(prog="scheduler")
    parser.add_argument(
        "command", choices=("serve", "health", "plan", "run", "status")
    )
    parser.add_argument("job", nargs="?", choices=timeline.JOBS)
    parser.add_argument(
        "--date", type=datetime.date.fromisoformat, default=None
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if args.command == "health":
        return _health(config.Settings.heartbeat_file)
    try:
        settings = config.Settings.from_env(os.environ)
    except ai_config.ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2
    day = args.date
    if day is None:
        day = market.now_new_york().date()
    if args.command == "serve":
        from scheduler import service  # noqa: PLC0415

        asyncio.run(service.serve(settings))
        return 0
    if args.command == "plan":
        return _plan(settings, day)
    if args.command == "status":
        return _status(settings, day)
    if args.job is None:
        parser.error("run needs a JOB")
    return _run(settings, args.job, day, args.force)


if __name__ == "__main__":
    sys.exit(main())
