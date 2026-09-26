import asyncio
import datetime

from ai_api import alerts
from ai_api import config as ai_config
import fakeredis
import pytest

from scheduler import cli
from scheduler import config
from scheduler import jobs
from scheduler import market
from scheduler import service
from scheduler import store
from scheduler import timeline

DAY = datetime.date(2026, 9, 28)  # a Monday
SECRET = "x" * 40
NY = market.NEW_YORK


def at(hour, minute=0, day=DAY):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=NY
    )


class Clock:
    """A fixed New York time."""

    def __init__(self, now):
        """Always returns ``now``."""
        self.now = now

    def __call__(self):
        """The fixed time."""
        return self.now


class FakeStore:
    """The scheduler's database in memory."""

    def __init__(self):
        """An ingested day, nothing else run yet."""
        self.rows = []
        self.ingest = "DONE"
        self.runs = {"ai.rule_run": None, "ai.ai_run": None}
        self.verify_state = store.VerifyState(None)
        self.briefs = {}

    async def start(self, day, job, mode):
        """Adds a RUNNING row."""
        self.rows.append({"job": job, "mode": mode, "status": "RUNNING"})
        return len(self.rows) - 1

    async def finish(self, run_id, status, detail):
        """Ends a row."""
        self.rows[run_id].update(status=status, detail=detail)

    async def record(self, day, job, mode, status, detail):
        """Adds a finished row."""
        self.rows.append(
            {"job": job, "mode": mode, "status": status, "detail": detail}
        )

    async def finished_today(self, day, job):
        """A DONE row for the job."""
        return any(r["job"] == job and r["status"] == "DONE" for r in self.rows)

    async def ingest_status(self, day):
        """The ingest run."""
        return self.ingest

    async def run_status(self, table, day):
        """A rule or AI run."""
        return self.runs[table]

    async def verify(self, day):
        """The verify run."""
        return self.verify_state

    async def brief(self, day, edition):
        """A brief edition."""
        return self.briefs.get(edition, store.BriefState(None))


class Runner:
    """Records ai-api calls; each step marks its run DONE in the store."""

    def __init__(self, db, fail=()):
        """Steps in ``fail`` exit 1."""
        self.db = db
        self.calls = []
        self.fail = set(fail)

    async def __call__(self, args, timeout_s):
        """Runs one fake step."""
        self.calls.append(list(args))
        step = args[0]
        if step in self.fail:
            return 1, "boom\nstep failed"
        if step == "rules":
            self.db.runs["ai.rule_run"] = "DONE"
        elif step == "enrich":
            self.db.runs["ai.ai_run"] = "DONE"
        elif step == "verify":
            self.db.verify_state = store.VerifyState("DONE", 88, 88)
        elif step == "brief":
            self.db.briefs[args[4]] = store.BriefState(
                "DONE", at(7, 20).astimezone(datetime.UTC)
            )
        return 0, "ok"


def settings(mode="production"):
    return config.Settings(
        run_mode=mode,
        owner=ai_config.Database("pg", 5432, "premarket", "premarket", "pw"),
        redis_host="redis",
        redis_password=SECRET,
    )


def make_jobs(db, runner, now, mode="production"):
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def no_sleep(_s):
        return None

    built = jobs.Jobs(
        settings(mode), db, redis, runner, Clock(now), no_sleep, poll_s=0
    )
    return built, redis


def run(coro):
    return asyncio.run(coro)


# --- timeline and calendar ---------------------------------------------------


def test_timeline_order_and_modes():
    times = [s.at for s in timeline.TIMELINE]
    assert times == sorted(times)
    demo = timeline.active(production=False)
    assert [s.job for s in demo] == ["retention"]
    production = timeline.active(production=True, corpus=False)
    assert "corpus" not in [s.job for s in production]
    assert timeline.slot("sla-brief").at == datetime.time(7, 30)


def test_catch_up_window():
    slots = timeline.active(production=True)
    due = [s.job for s in timeline.catch_up(slots, datetime.time(6, 20))]
    # SLA checks never catch up; the pipeline and retention windows are
    # open... retention closes at 05:00.
    assert due == ["pipeline"]
    due = [s.job for s in timeline.catch_up(slots, datetime.time(9, 10))]
    assert due == ["pipeline", "refresh"]


class Sessions:
    """Weekdays except ``holidays``."""

    def __init__(self, holidays=()):
        """The holidays are closed."""
        self.holidays = {d.isoformat() for d in holidays}

    def is_session(self, day):
        """True on an open weekday."""
        weekday = datetime.date.fromisoformat(day).weekday() < 5
        return weekday and day not in self.holidays


def test_calendar_skips_weekends_and_holidays():
    thanksgiving = datetime.date(2026, 11, 26)
    cal = market.Calendar(Sessions([thanksgiving]))
    assert cal.is_trading_day(DAY)
    assert not cal.is_trading_day(datetime.date(2026, 9, 27))  # Sunday
    assert not cal.is_trading_day(thanksgiving)
    assert cal.next_trading_day(thanksgiving) == datetime.date(2026, 11, 27)


def test_calendar_falls_back_to_weekdays():
    class Broken:
        def is_session(self, day):
            raise ValueError("out of range")

    cal = market.Calendar(Broken())
    assert cal.is_trading_day(DAY)
    assert not cal.is_trading_day(datetime.date(2026, 9, 26))


def test_settings_run_mode():
    env = {
        "PGUSER": "premarket",
        "PGPASSWORD": "pw",
        "REDIS_PASSWORD": SECRET,
    }
    assert config.Settings.from_env(env).run_mode == "demo"
    env["RUN_MODE"] = "production"
    assert config.Settings.from_env(env).production
    env["RUN_MODE"] = "live"
    with pytest.raises(ai_config.ConfigError):
        config.Settings.from_env(env)


# --- the day's pipeline ------------------------------------------------------


def test_pipeline_runs_rules_enrich_verify():
    db = FakeStore()
    runner = Runner(db)
    built, redis = make_jobs(db, runner, at(6))
    assert run(built.run("pipeline", DAY)) == "DONE"
    assert [c[0] for c in runner.calls] == ["rules", "enrich", "verify"]
    assert db.rows[-1]["status"] == "DONE"
    assert run(redis.get("run:premarket:2026-09-28")) == "production"
    # The lock keeps a second replica (or firing) from running it again.
    assert run(built.run("pipeline", DAY)) == "SKIPPED"
    assert len(runner.calls) == 3


def test_pipeline_resumes_after_a_crash():
    db = FakeStore()
    db.runs["ai.rule_run"] = "DONE"
    runner = Runner(db)
    built, _ = make_jobs(db, runner, at(6, 20))
    assert run(built.run("pipeline", DAY)) == "DONE"
    assert [c[0] for c in runner.calls] == ["enrich", "verify"]
    assert "rules already DONE" in db.rows[-1]["detail"]


def test_pipeline_waits_for_ingest_then_fails_and_alerts():
    db = FakeStore()
    db.ingest = "RUNNING"
    runner = Runner(db)
    built, redis = make_jobs(db, runner, at(7, 1))
    assert run(built.run("pipeline", DAY)) == "FAILED"
    assert runner.calls == []
    assert db.rows[-1]["detail"] == "ingest run RUNNING"
    # A failed job releases its lock and raises a critical alert.
    assert run(redis.get("run:premarket:2026-09-28")) is None
    fired = run(alerts.Alerts(redis).read(block_ms=0))
    assert fired[0][1]["key"] == "job:pipeline:2026-09-28"
    assert fired[0][1]["severity"] == "critical"


def test_pipeline_step_failure_is_recorded():
    db = FakeStore()
    runner = Runner(db, fail={"enrich"})
    built, _ = make_jobs(db, runner, at(6))
    assert run(built.run("pipeline", DAY)) == "FAILED"
    assert db.rows[-1]["detail"] == "enrich (exit 1): step failed"


def test_verify_exit_code_does_not_fail_a_done_run():
    db = FakeStore()

    class OneItemFailed(Runner):
        async def __call__(self, args, timeout_s):
            code, tail = await super().__call__(args, timeout_s)
            return (1, tail) if args[0] == "verify" else (code, tail)

    built, _ = make_jobs(db, OneItemFailed(db), at(6))
    assert run(built.run("pipeline", DAY)) == "DONE"


def test_force_takes_a_held_lock():
    db = FakeStore()
    runner = Runner(db)
    built, redis = make_jobs(db, runner, at(6))
    run(redis.set("run:premarket:2026-09-28", "crashed"))
    assert run(built.run("pipeline", DAY)) == "SKIPPED"
    assert run(built.run("pipeline", DAY, mode="manual", force=True)) == "DONE"
    assert db.rows[-1]["mode"] == "manual"


# --- brief, other jobs -------------------------------------------------------


def test_brief_waits_for_verify_and_publishes():
    db = FakeStore()
    db.verify_state = store.VerifyState("DONE", 88, 88)
    runner = Runner(db)
    built, _ = make_jobs(db, runner, at(7, 15))
    assert run(built.run("brief", DAY)) == "DONE"
    assert runner.calls == [
        [
            "brief",
            "--date",
            "2026-09-28",
            "--edition",
            "morning",
            "--timeout",
            "1800",
        ],
    ]
    # The refresh is its own edition.
    assert run(built.run("refresh", DAY)) == "DONE"
    assert runner.calls[-1][4] == "refresh"


def test_brief_without_verify_fails_at_its_deadline():
    db = FakeStore()
    db.verify_state = store.VerifyState("RUNNING", 88, 40)
    runner = Runner(db)
    built, _ = make_jobs(db, runner, at(9, 1))
    assert run(built.run("brief", DAY)) == "FAILED"
    assert runner.calls == []


def test_simple_jobs_call_their_commands():
    db = FakeStore()
    runner = Runner(db)
    built, _ = make_jobs(db, runner, at(9, 30))
    assert run(built.run("expire", DAY)) == "DONE"
    assert run(built.run("retention", DAY)) == "DONE"
    assert run(built.run("scorecard", DAY)) == "DONE"
    assert runner.calls == [
        ["expire", "--date", "2026-09-28"],
        ["retention", "--days", "90"],
        ["scorecard", "--date", "2026-09-28"],
    ]


# --- SLA checks --------------------------------------------------------------


def test_sla_checks_green():
    db = FakeStore()
    db.verify_state = store.VerifyState("DONE", 88, 88)
    db.briefs["morning"] = store.BriefState(
        "DONE", at(7, 20).astimezone(datetime.UTC)
    )
    built, redis = make_jobs(db, Runner(db), at(7, 30))
    for check in ("sla-ingest", "sla-backlog", "sla-verify", "sla-brief"):
        assert run(built.run(check, DAY)) == "OK"
    assert run(alerts.Alerts(redis).read(block_ms=0)) == []


def test_sla_breaches_alert_once():
    db = FakeStore()
    db.ingest = None
    db.verify_state = store.VerifyState("RUNNING", 88, 20)
    db.briefs["morning"] = store.BriefState(
        "DONE", at(7, 41).astimezone(datetime.UTC)
    )
    built, redis = make_jobs(db, Runner(db), at(7, 30))
    for check in ("sla-ingest", "sla-backlog", "sla-verify", "sla-brief"):
        assert run(built.run(check, DAY)) == "BREACHED"
    assert run(built.run("sla-verify", DAY)) == "BREACHED"
    fired = run(alerts.Alerts(redis).read(block_ms=0))
    keys = [data["key"] for _, data in fired]
    assert keys == [
        "sla:ingest:2026-09-28",
        "sla:backlog:2026-09-28",
        "sla:verify:2026-09-28",
        "sla:brief:2026-09-28",
    ]
    assert "68 verify jobs queued" in db.rows[1]["detail"]
    assert "published 07:41 ET" in db.rows[3]["detail"]


def test_verify_done_resolves_the_sla_alert():
    db = FakeStore()
    db.verify_state = store.VerifyState("RUNNING", 88, 20)
    built, redis = make_jobs(db, Runner(db), at(7, 0))
    run(built.run("sla-verify", DAY))
    db.verify_state = store.VerifyState(None)
    assert run(built.run("pipeline", DAY)) == "DONE"
    fired = run(alerts.Alerts(redis).read(block_ms=0))
    assert [d["status"] for _, d in fired] == ["firing", "resolved"]
    assert alerts.active(fired) == []


# --- service -----------------------------------------------------------------


def test_service_skips_non_trading_days_and_catches_up():
    db = FakeStore()
    runner = Runner(db)
    now = at(6, 20)
    built, _ = make_jobs(db, runner, now)
    svc = service.Service(
        settings(), built, db, market.Calendar(Sessions()), Clock(now)
    )

    async def scenario():
        started = await svc.catch_up()
        await asyncio.gather(*svc._running)
        return started

    assert run(scenario()) == ["pipeline"]
    assert [c[0] for c in runner.calls] == ["rules", "enrich", "verify"]
    # Finished today: a second start doesn't run it again.
    assert run(scenario()) == []
    sunday = at(6, 0, datetime.date(2026, 9, 27))
    svc_sunday = service.Service(
        settings(), built, db, market.Calendar(Sessions()), Clock(sunday)
    )
    assert run(svc_sunday.fire("pipeline")) == "SKIPPED"
    assert run(svc_sunday.fire("retention")) == "DONE"


def test_demo_mode_only_schedules_retention():
    db = FakeStore()
    built, _ = make_jobs(db, Runner(db), at(6), mode="demo")
    svc = service.Service(
        settings("demo"), built, db, market.Calendar(Sessions()), Clock(at(6))
    )
    assert [s.job for s in svc.slots] == ["retention"]
    assert run(svc.catch_up()) == []


def test_health_reads_the_heartbeat(tmp_path):
    beat = tmp_path / "alive"
    assert cli._health(str(beat)) == 1
    beat.touch()
    assert cli._health(str(beat)) == 0


def test_lock_keys():
    assert jobs.lock_key("pipeline", DAY) == "run:premarket:2026-09-28"
    assert jobs.lock_key("brief", DAY) == "schedule:brief:2026-09-28"


def test_ops_collector_reads_redis_even_without_the_database():
    from scheduler import ops

    redis = fakeredis.FakeRedis(decode_responses=True)
    now = datetime.datetime.now(datetime.UTC)
    redis.set(f"llm:cloud_spend:{now:%Y-%m}", "4.5")
    collector = ops.OpsCollector(
        "host=nowhere.invalid connect_timeout=1", redis, 20.0
    )
    found = {m.name: m for m in collector.collect()}
    assert "premarket_items" not in found
    spend = {
        s.labels["period"]: s.value
        for s in found["premarket_llm_cloud_spend_usd"].samples
    }
    assert spend == {"month": 4.5, "today": 0.0}
    assert found["premarket_llm_cloud_budget_usd"].samples[0].value == 20.0
    assert found["premarket_queue_pending"].samples[0].value == 0
