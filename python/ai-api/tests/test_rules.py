"""Rule checks: SEC registry, entities, sources, dates, rate limit, engine."""

import asyncio
import datetime
import os
import pathlib

import fakeredis
import pytest

from ai_api.dedup import config as dedup_config
from ai_api.dedup import service
from ai_api.dedup import store
from ai_api.rules import checks
from ai_api.rules import engine
from ai_api.rules import ratelimit
from ai_api.rules import registry

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIXTURE = _ROOT / "evals" / "datasets" / "sec_company_tickers.json"
# The image copies python/config to PREMARKET_CONFIG_DIR.
_CONFIG = os.environ.get("PREMARKET_CONFIG_DIR") or _ROOT.parent / "config"
_SOURCES = pathlib.Path(_CONFIG) / "sources.yaml"
_DAY = datetime.date(2026, 9, 24)
_REFRESHED = datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC)


@pytest.fixture(scope="module")
def sec():
    companies = registry.parse_sec_json(_FIXTURE.read_bytes())
    return registry.Registry(companies, _REFRESHED)


@pytest.fixture(scope="module")
def policy():
    return checks.SourcePolicy.from_yaml(_SOURCES)


# --- registry -----------------------------------------------------------------


def test_parse_sec_json_skips_bad_rows(sec):
    assert len(sec) == 58
    assert sec.company("brk.b").title == "BERKSHIRE HATHAWAY INC"
    assert sec.company("BAD TICKER") is None
    assert sec.describe() == "58 tickers, refreshed 2026-09-20"


@pytest.mark.parametrize(
    ("vendor", "sec_title"),
    [
        ("The Procter & Gamble Company", "PROCTER & GAMBLE Co"),
        ("Eli Lilly and Company", "ELI LILLY & Co"),
        ("Costco Wholesale Corporation", "COSTCO WHOLESALE CORP /NEW"),
        ("McDonald's Corporation", "MCDONALDS CORP"),
        ("The Coca-Cola Company", "COCA COLA CO"),
        ("Bank of America Corporation", "BANK OF AMERICA CORP /DE/"),
        ("AT&T Inc.", "AT&T INC."),
    ],
)
def test_company_names_match_sec_titles(vendor, sec_title):
    assert registry.normalize_name(vendor) == registry.normalize_name(sec_title)


def test_parse_rejects_non_objects():
    for payload in (b"[]", b"not json"):
        with pytest.raises(registry.RegistryError):
            registry.parse_sec_json(payload)


def test_user_agent_needs_a_contact_email():
    assert registry.check_user_agent(" lab a@b.example ") == "lab a@b.example"
    for bad in ("", "premarket-ai lab"):
        with pytest.raises(registry.RegistryError):
            registry.check_user_agent(bad)


# --- entity check -------------------------------------------------------------


def test_names_before_a_ticker():
    body = (
        "The board of Bank of America Corporation (BAC) met. Apple Inc. "
        "(AAPL) and Microsoft Corporation (MSFT) signed; (NVDA) alone."
    )
    assert checks.names_before(body, "BAC") == ["Bank of America Corporation"]
    assert checks.names_before(body, "MSFT") == ["Microsoft Corporation"]
    assert checks.names_before(body, "AAPL") == ["Apple Inc."]
    assert checks.names_before(body, "NVDA") == []


def test_real_ticker_passes(sec):
    finding = checks.check_entities(("AAPL",), "Apple Inc. (AAPL) said", sec)
    assert finding.codes == ()
    assert finding.evidence[0].message == (
        "AAPL is Apple Inc. in the SEC ticker registry."
    )


def test_invented_company_is_fake_company_and_fake_ticker(sec):
    body = "Quantavex Holdings Inc. (QVXH) agreed to be acquired by Apple."
    finding = checks.check_entities(("QVXH",), body, sec)
    assert finding.codes == ("FAKE_TICKER", "FAKE_COMPANY")
    assert 'No registered company is named "Quantavex Holdings Inc.".' in [
        e.message for e in finding.evidence
    ]


def test_real_company_with_a_bogus_ticker_is_fake_ticker_only(sec):
    body = "The board of Apple Inc. (AAPLQZ) approved it."
    finding = checks.check_entities(("AAPLQZ",), body, sec)
    assert finding.codes == ("FAKE_TICKER",)
    assert "Apple Inc. is a registered company" in finding.evidence[0].message


def test_without_a_registry_nothing_is_flagged():
    finding = checks.check_entities(("QVXH",), "Q (QVXH)", None)
    assert finding.codes == ()
    assert "skipped" in finding.evidence[0].message


# --- source check -------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "domain", "spoofed"),
    [
        ("https://wire.vendornews.example/a", "wire.vendornews.example", False),
        ("https://reuters-news.test/a", "reuters-news.test", True),
        ("https://bl00mberg.test/a", "bl00mberg.test", True),
        ("https://reutres.com/a", "reutres.com", True),
        ("https://www.reuters.com/a", "www.reuters.com", False),
        ("https://sec-filings.test/a", "sec-filings.test", True),
        ("https://secure.example/a", "secure.example", False),
        ("https://a.example/x", "b.example", True),
        ("not a url", "a.example", True),
    ],
)
def test_source_check(policy, url, domain, spoofed):
    finding = policy.check(url, domain)
    assert (finding.codes == ("SPOOFED_SOURCE",)) is spoofed


def test_source_reputation_is_context(policy):
    finding = policy.check(
        "https://pennyrocket.example/x", "pennyrocket.example"
    )
    assert finding.codes == ()
    assert "low source, reputation 0.10" in finding.evidence[-1].message


# --- dated text ---------------------------------------------------------------


def test_old_dates_are_stale():
    finding = checks.check_dates(
        "On January 3, 2026, Apple announced a buyback.", _DAY, 30
    )
    assert finding.codes == ("STALE",)
    assert "264 days before" in finding.evidence[0].message
    assert checks.check_dates("On September 1, 2026, x", _DAY, 30).codes == ()
    assert checks.check_dates("February 30, 2026", _DAY, 30).codes == ()


# --- rate limiter -------------------------------------------------------------


def test_token_bucket_allows_a_burst_then_asks_to_wait():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    bucket = ratelimit.TokenBucket(redis, "edgar", rate=10)

    async def take(times):
        return [await bucket.try_take() for _ in range(times)]

    waits = asyncio.run(take(11))
    assert waits[:10] == [0] * 10
    assert 0 < waits[10] <= 0.1


def test_token_bucket_times_out():
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    bucket = ratelimit.TokenBucket(redis, "slow", rate=0.01, burst=1)

    async def twice():
        await bucket.acquire(timeout_s=1)
        await bucket.acquire(timeout_s=0.1)

    with pytest.raises(ratelimit.RateLimitTimeoutError):
        asyncio.run(twice())


# --- engine -------------------------------------------------------------------


def _raw(news_id, number, headline, body, domain, tickers):
    return engine.RawItem(
        news_id=news_id,
        feed_date=_DAY,
        vendor_item_id=f"VND-20260924-{number:03d}",
        headline=f"[SYNTHETIC] {headline}",
        body=f"NEW YORK, September 24 (Acme Market Wire) -- {body}",
        source_url=f"https://{domain}/2026/09/24/story-{number:03d}",
        source_domain=domain,
        tickers=tickers,
    )


def test_engine_combines_every_check(sec, policy):
    cfg = dedup_config.DedupConfig()
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    dedup = service.DedupService(store.DedupStore(redis, cfg.ttl_s), cfg)
    rules = engine.RuleEngine(dedup, sec, policy)
    real = _raw(
        1,
        1,
        "Apple lifts dividend",
        "Apple Inc. (AAPL) raised its dividend to $0.26.",
        "wire.vendornews.example",
        ("AAPL",),
    )
    fake = _raw(
        2,
        2,
        "Umbrix to be acquired",
        "Umbrix Robotics Corp. (UMBX) agreed to be acquired.",
        "reuters-news.test",
        ("UMBX",),
    )
    copy = _raw(
        3,
        3,
        "APPLE LIFTS DIVIDEND",
        "Apple Inc. (AAPL)  raised its dividend to $0.26.",
        "markets.dailybrief.example",
        ("AAPL",),
    )
    results = asyncio.run(rules.check_items([real, fake, copy]))

    assert [r.reason_codes for r in results] == [
        (),
        ("FAKE_COMPANY", "FAKE_TICKER", "SPOOFED_SOURCE"),
        (),
    ]
    assert results[2].duplicate.canonical_id == 1
    assert results[2].evidence[0].message == (
        "Exact copy (L1) of VND-20260924-001 from 2026-09-24."
    )
    summary = engine.DaySummary.of(results)
    assert summary.line() == (
        "3 received -> 2 unique, 1 dup (exact 1); flagged 1: "
        "FAKE_COMPANY 1, FAKE_TICKER 1, SPOOFED_SOURCE 1, STALE 0"
    )
