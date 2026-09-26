"""``ai-api rules --date D``: the rule run of one feed date.

1. Waits for nothing: the day's ingest run must already be DONE (the
   scheduler of increment 6 does the waiting).
2. Refreshes the SEC registry when it's older than a week.
3. Makes sure the 7 days before D are in the Redis dedup index: a day
   that was never checked is checked now; a checked day whose index expired
   (or Redis restarted: it has no persistence) is re-indexed from Postgres.
4. Checks D's items in order and replaces D's results.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import time

import psycopg
from redis import asyncio as aioredis

from ai_api import config
from ai_api.dedup import fastpath
from ai_api.dedup import service
from ai_api.dedup import store
from ai_api.rules import checks
from ai_api.rules import engine
from ai_api.rules import ratelimit
from ai_api.rules import registry as registry_lib
from ai_api.rules import repository

_log = logging.getLogger(__name__)
_REGISTRY_LOCK = "edgar:registry:lock"
_EDGAR_RATE_PER_S = 10


class NotReadyError(RuntimeError):
    """The feed date has no finished ingest run yet."""


@dataclasses.dataclass
class _Context:
    repo: repository.RulesRepository
    dedup: service.DedupService
    engine: engine.RuleEngine
    registry: registry_lib.Registry | None


def _redis(settings: config.RulesSettings) -> aioredis.Redis:
    return aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=5,
    )


async def ensure_registry(
    repo: repository.RulesRepository,
    redis: aioredis.Redis,
    settings: config.RulesSettings,
    force: bool = False,
) -> registry_lib.Registry | None:
    """The SEC registry, refreshed from SEC when it's stale.

    A failed refresh keeps the previous copy. Without any copy the entity
    check is skipped (never guessed), and the run log says so.

    Args:
        repo: The repository.
        redis: Redis (rate limiter and refresh lock).
        settings: The settings.
        force: Refresh even when the copy is fresh.

    Returns:
        The registry, or None when there's no copy at all.
    """
    refreshed = await repo.registry_refreshed_at()
    now = datetime.datetime.now(datetime.UTC)
    max_age = datetime.timedelta(days=settings.registry_max_age_days)
    if refreshed is not None and now - refreshed < max_age and not force:
        return await repo.load_registry()
    if not settings.sec_user_agent:
        _log.warning(
            "SEC_USER_AGENT is empty: the SEC registry isn't refreshed "
            "(copy from %s)",
            "nowhere" if refreshed is None else refreshed.date(),
        )
        return await repo.load_registry()
    if not await redis.set(_REGISTRY_LOCK, "1", nx=True, ex=300):
        _log.info("another process is refreshing the SEC registry")
        return await repo.load_registry()
    try:
        limiter = ratelimit.TokenBucket(redis, "edgar", _EDGAR_RATE_PER_S)
        companies = await registry_lib.fetch(settings.sec_user_agent, limiter)
        await repo.replace_registry(companies, now)
        _log.info("SEC registry refreshed: %d tickers", len(companies))
    except (registry_lib.RegistryError, ratelimit.RateLimitTimeoutError) as e:
        _log.warning("SEC registry refresh failed, keeping the copy: %s", e)
    finally:
        await redis.delete(_REGISTRY_LOCK)
    return await repo.load_registry()


async def _check_day(ctx: _Context, day: datetime.date) -> engine.DaySummary:
    run_id = await ctx.repo.start_run(day, fastpath.backend())
    started = time.monotonic()
    try:
        items = await ctx.repo.load_day(day)
        results = await ctx.engine.check_items(items)
        await ctx.repo.save_results(results)
        await ctx.dedup.mark_day(day)
        summary = engine.DaySummary.of(results)
        total_ms = int((time.monotonic() - started) * 1000)
        tickers = None if ctx.registry is None else len(ctx.registry)
        await ctx.repo.finish_run(run_id, summary, tickers, total_ms)
    except Exception as e:
        await ctx.repo.fail_run(run_id, repr(e))
        raise
    _log.info("rules %s: %s (%d ms)", day, summary.line(), total_ms)
    return summary


async def _prepare_window(
    ctx: _Context, day: datetime.date, window_days: int
) -> None:
    first = day - datetime.timedelta(days=window_days)
    last = day - datetime.timedelta(days=1)
    checked = await ctx.repo.checked_days(first, last)
    for earlier in await ctx.repo.raw_days(first, last):
        if earlier not in checked:
            _log.info("rules %s: never checked, checking it first", earlier)
            await _check_day(ctx, earlier)
        elif not await ctx.dedup.has_day(earlier):
            unique = await ctx.repo.unique_items(earlier)
            await ctx.dedup.index_unique([i.dedup_item() for i in unique])
            await ctx.dedup.mark_day(earlier)
            _log.info("dedup index: re-indexed %s (%d)", earlier, len(unique))


async def _context(
    conn: psycopg.AsyncConnection,
    redis: aioredis.Redis,
    settings: config.RulesSettings,
    force_registry: bool = False,
) -> _Context:
    repo = repository.RulesRepository(conn)
    policy = checks.SourcePolicy.from_yaml(settings.config_dir / "sources.yaml")
    await repo.seed_reputations(list(policy.reputations.values()))
    policy = policy.with_reputations(await repo.load_reputations())
    registry = await ensure_registry(repo, redis, settings, force_registry)
    dedup = service.DedupService(
        store.DedupStore(redis, settings.dedup.ttl_s), settings.dedup
    )
    rule_engine = engine.RuleEngine(
        dedup, registry, policy, settings.stale_max_age_days
    )
    return _Context(repo, dedup, rule_engine, registry)


async def run(
    settings: config.RulesSettings, day: datetime.date
) -> engine.DaySummary:
    """The rule run of ``day`` (see the module docstring).

    Args:
        settings: The settings.
        day: The feed date.

    Returns:
        The day's counts.

    Raises:
        NotReadyError: The day's ingest run isn't DONE.
        fastpath.FastpathMissingError: The C++ module is required but
            missing.
    """
    fastpath.check_required()
    redis = _redis(settings)
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.owner.dsn(), autocommit=True
        ) as conn:
            status = await repository.RulesRepository(conn).ingest_status(day)
            if status != "DONE":
                raise NotReadyError(
                    f"the ingest run of {day} is {status or 'missing'}; "
                    "run `make -C python ingest DATE=...` first"
                )
            ctx = await _context(conn, redis, settings)
            if ctx.registry is None:
                _log.warning("no SEC registry: FAKE_* checks are skipped")
            await _prepare_window(ctx, day, settings.dedup.window_days)
            return await _check_day(ctx, day)
    finally:
        await redis.aclose()


async def refresh_registry(settings: config.RulesSettings) -> int:
    """Refreshes the SEC registry now; returns its ticker count (0: none)."""
    redis = _redis(settings)
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.owner.dsn(), autocommit=True
        ) as conn:
            repo = repository.RulesRepository(conn)
            found = await ensure_registry(repo, redis, settings, force=True)
            return 0 if found is None else len(found)
    finally:
        await redis.aclose()


async def rebuild_index(
    settings: config.RulesSettings, day: datetime.date
) -> int:
    """Re-indexes the checked days of the window ending at ``day``.

    The warm-up after Redis lost its data: every unique item of each
    checked day in [day - window, day] goes back into the index.

    Returns:
        The number of items indexed.
    """
    redis = _redis(settings)
    total = 0
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.owner.dsn(), autocommit=True
        ) as conn:
            repo = repository.RulesRepository(conn)
            dedup = service.DedupService(
                store.DedupStore(redis, settings.dedup.ttl_s), settings.dedup
            )
            first = day - datetime.timedelta(days=settings.dedup.window_days)
            for checked in sorted(await repo.checked_days(first, day)):
                unique = await repo.unique_items(checked)
                await dedup.index_unique([i.dedup_item() for i in unique])
                await dedup.mark_day(checked)
                total += len(unique)
                _log.info("dedup index: %s (%d unique)", checked, len(unique))
    finally:
        await redis.aclose()
    return total
