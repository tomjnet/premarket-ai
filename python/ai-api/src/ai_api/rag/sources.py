"""The trusted sources: SEC EDGAR, XBRL company facts, Fed and SEC releases.

Primary public sources only. Every SEC request carries SEC_USER_AGENT and
goes through the shared EDGAR token bucket (10 requests/s, the same one
the rule run uses); the Fed's site gets a gentler 2 requests/s.

- 8-K filings of the last 12 months (newest 8 per company): the filing's
  main document and its EX-99.1 press release, when it has one.
- XBRL company facts: one fact sheet per company with the latest annual and
  quarterly revenue, net income, diluted EPS and shares outstanding.
- Federal Reserve and SEC press releases, from their RSS feeds.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import dataclasses
import datetime
import email.utils
import json
import logging
import re
from typing import Any, Protocol
import xml.etree.ElementTree as ET  # noqa: N817 - the standard alias.

import httpx

from ai_api.rag import html_text

_log = logging.getLogger(__name__)
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}"
FED_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
SEC_RSS = "https://www.sec.gov/news/pressreleases.rss"
_EX99 = re.compile(r"ex-?99[-_.]?0?1\b|ex991|exhibit99-?1", re.IGNORECASE)
_MAX_BYTES = 8_000_000
_MIN_TEXT_CHARS = 200
_RETRIES = 3
# XBRL concepts of the fact sheet, first match wins.
_REVENUE = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "RevenuesNetOfInterestExpense",
)
_FACTS = (
    ("Revenue", _REVENUE, "USD"),
    ("Net income", ("NetIncomeLoss",), "USD"),
    ("Operating income", ("OperatingIncomeLoss",), "USD"),
    ("Diluted EPS", ("EarningsPerShareDiluted",), "USD/shares"),
)


class Limiter(Protocol):
    """Waits for a request slot (``rules.ratelimit.TokenBucket``)."""

    async def acquire(self, timeout_s: float = ...) -> None:
        """Returns when a request may be sent."""
        ...


class SourceError(RuntimeError):
    """A source couldn't be fetched or parsed."""


@dataclasses.dataclass(frozen=True)
class Document:
    """One trusted document, as plain text.

    Attributes:
        source: edgar_8k, edgar_ex99, xbrl_facts, fed_press or sec_press.
        url: Where it was fetched (unique).
        title: A human title for citations.
        text: The text.
        published_at: When it was filed or released.
        ticker: The company's ticker, for company documents.
        cik: The company's SEC CIK, for company documents.
    """

    source: str
    url: str
    title: str
    text: str
    published_at: datetime.datetime | None
    ticker: str | None = None
    cik: int | None = None


@dataclasses.dataclass(frozen=True)
class Company:
    """A universe company with its CIK from the SEC registry."""

    ticker: str
    name: str
    cik: int


class Fetcher:
    """HTTP GET with the SEC User-Agent, a rate limit and retries."""

    def __init__(
        self,
        user_agent: str,
        sec_limiter: Limiter,
        other_limiter: Limiter,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Sends ``user_agent``; SEC hosts use ``sec_limiter``.

        Args:
            user_agent: SEC_USER_AGENT (a name and contact email).
            sec_limiter: The EDGAR token bucket.
            other_limiter: The bucket for the other hosts.
            client: An HTTP client (tests); None creates one.
        """
        self._sec = sec_limiter
        self._other = other_limiter
        self._client = client
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": user_agent,
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
            )

    async def aclose(self) -> None:
        """Closes the HTTP client."""
        await self._client.aclose()

    async def get(self, url: str) -> bytes:
        """The body of ``url``.

        Raises:
            SourceError: Not found, too large, or still failing after
                retries.
        """
        host = httpx.URL(url).host
        limiter = self._sec if host.endswith("sec.gov") else self._other
        for attempt in range(_RETRIES):
            await limiter.acquire(timeout_s=120)
            try:
                response = await self._client.get(url)
            except httpx.HTTPError as e:
                error = repr(e)
            else:
                if response.status_code == 200:
                    if len(response.content) > _MAX_BYTES:
                        raise SourceError(f"{url}: larger than {_MAX_BYTES}")
                    return response.content
                if response.status_code in (403, 404):
                    raise SourceError(f"{url}: HTTP {response.status_code}")
                error = f"HTTP {response.status_code}"
            await asyncio.sleep(2**attempt)
        raise SourceError(f"{url}: {error}")

    async def json(self, url: str) -> Any:
        """The JSON body of ``url``.

        Raises:
            SourceError: The fetch failed or the body isn't JSON.
        """
        try:
            return json.loads(await self.get(url))
        except ValueError as e:
            raise SourceError(f"{url}: not JSON") from e


def _date(text: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(text).replace(
            tzinfo=datetime.UTC
        )
    except ValueError:
        return None


def recent_8ks(
    submissions: dict[str, Any], since: datetime.date, limit: int
) -> list[dict[str, str]]:
    """The newest 8-K filings since ``since`` (at most ``limit``).

    Args:
        submissions: The EDGAR submissions JSON of a company.
        since: The oldest filing date to keep.
        limit: How many to keep.

    Returns:
        ``{"accession", "date", "document", "items"}`` per filing, newest
        first.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    found = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        try:
            filed = datetime.date.fromisoformat(recent["filingDate"][i])
            filing = {
                "accession": recent["accessionNumber"][i],
                "date": filed.isoformat(),
                "document": recent["primaryDocument"][i],
                "items": recent.get("items", [""] * len(forms))[i] or "",
            }
        except (KeyError, IndexError, ValueError):
            continue
        if filed >= since:
            found.append(filing)
    found.sort(key=lambda f: f["date"], reverse=True)
    return found[:limit]


def ex99_name(index: dict[str, Any]) -> str | None:
    """The EX-99.1 document of a filing's ``index.json``, or None."""
    items = index.get("directory", {}).get("item", [])
    names = [item.get("name", "") for item in items]
    for name in names:
        if name.lower().endswith((".htm", ".html", ".txt")) and _EX99.search(
            name
        ):
            return name
    return None


async def company_filings(
    fetcher: Fetcher,
    company: Company,
    since: datetime.date,
    limit: int,
    known: set[str],
) -> list[Document]:
    """The company's recent 8-Ks and their EX-99.1 press releases.

    Args:
        fetcher: The fetcher.
        company: The company.
        since: Oldest filing date.
        limit: Newest filings to take.
        known: URLs already in the corpus (not fetched again).

    Returns:
        The new documents.
    """
    submissions = await fetcher.json(SUBMISSIONS_URL.format(cik=company.cik))
    documents = []
    for filing in recent_8ks(submissions, since, limit):
        folder = ARCHIVE_URL.format(
            cik=company.cik, folder=filing["accession"].replace("-", "")
        )
        published = _date(filing["date"])
        items = filing["items"]
        main_url = f"{folder}/{filing['document']}"
        targets = [
            (
                "edgar_8k",
                main_url,
                f"{company.name} 8-K filed {filing['date']}"
                + (f" (items {items})" if items else ""),
            )
        ]
        try:
            index = await fetcher.json(f"{folder}/index.json")
        except SourceError as e:
            _log.info("no index for %s: %s", folder, e)
        else:
            name = ex99_name(index)
            if name is not None:
                targets.append(
                    (
                        "edgar_ex99",
                        f"{folder}/{name}",
                        f"{company.name} press release (8-K EX-99.1) "
                        f"filed {filing['date']}",
                    )
                )
        for source, url, title in targets:
            if url in known:
                continue
            try:
                raw = await fetcher.get(url)
            except SourceError as e:
                _log.info("skipped %s: %s", url, e)
                continue
            text = html_text.to_text(raw.decode("utf-8", errors="replace"))
            if len(text) < _MIN_TEXT_CHARS:
                continue
            documents.append(
                Document(
                    source=source,
                    url=url,
                    title=title,
                    text=text,
                    published_at=published,
                    ticker=company.ticker,
                    cik=company.cik,
                )
            )
    return documents


def _money(value: float, unit: str) -> str:
    if unit == "USD/shares":
        return f"${value:,.2f}"
    magnitude = abs(value)
    for size, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if magnitude >= size:
            return f"${value / size:,.2f} {word}"
    return f"${value:,.0f}"


def _entries(
    facts: dict[str, Any], concepts: Sequence[str], unit: str, form: str
) -> list[dict[str, Any]]:
    """Values of ``concepts`` reported in ``form``.

    A 10-K's full year, or a 10-Q's own quarter (not year to date).
    """
    found = []
    for concept in concepts:
        entries = (
            facts.get("us-gaap", {}).get(concept, {}).get("units", {}).get(unit)
        )
        for entry in entries or []:
            if entry.get("form") != form or "start" not in entry:
                continue
            start = datetime.date.fromisoformat(entry["start"])
            end = datetime.date.fromisoformat(entry["end"])
            days = (end - start).days
            if form == "10-K" and not 350 <= days <= 380:
                continue
            if form == "10-Q" and not 80 <= days <= 100:
                continue
            found.append(entry)
    return found


def _period_facts(
    facts: dict[str, Any], form: str
) -> tuple[tuple[str, str, str], list[str]] | None:
    """The newest period of ``form`` and every fact reported for it.

    Companies switch XBRL concepts over the years (Revenues, then
    RevenueFromContractWithCustomer...), so the period is chosen first,
    as the newest one any fact has, and each fact is then taken for exactly
    that period, from whichever concept reports it.
    """
    by_fact = [
        (name, unit, _entries(facts, concepts, unit, form))
        for name, concepts, unit in _FACTS
    ]
    ends = [e["end"] for _, _, entries in by_fact for e in entries]
    if not ends:
        return None
    newest = max(ends)
    parts = []
    period = None
    for name, unit, entries in by_fact:
        matching = [e for e in entries if e["end"] == newest]
        if not matching:
            continue
        entry = max(matching, key=lambda e: e["filed"])
        if period is None:
            period = (entry["start"], entry["end"], entry["filed"])
        parts.append(f"{name} {_money(float(entry['val']), unit)}")
    return period, parts


def fact_sheet(company: Company, facts_json: dict[str, Any]) -> str | None:
    """A plain-text fact sheet from the XBRL company facts.

    Args:
        company: The company.
        facts_json: The companyfacts JSON.

    Returns:
        The text, or None when no fact was found.
    """
    facts = facts_json.get("facts", {})
    lines = [
        f"{company.name} ({company.ticker}): financial facts reported to the "
        "SEC in XBRL (as filed)."
    ]
    for form, label in (("10-K", "Fiscal year"), ("10-Q", "Latest quarter")):
        found = _period_facts(facts, form)
        if found is None:
            continue
        period, parts = found
        lines.append(
            f"{label} ({form}, {period[0]} to {period[1]}, filed "
            f"{period[2]}): " + "; ".join(parts) + "."
        )
    shares = facts.get("dei", {}).get("EntityCommonStockSharesOutstanding", {})
    entries = shares.get("units", {}).get("shares", [])
    if entries:
        newest = max(entries, key=lambda e: (e.get("end", ""), e["filed"]))
        lines.append(
            f"Shares outstanding: {float(newest['val']) / 1e9:,.3f} billion "
            f"(as of {newest.get('end', newest['filed'])})."
        )
    return "\n".join(lines) if len(lines) > 1 else None


async def company_facts(fetcher: Fetcher, company: Company) -> Document | None:
    """The company's XBRL fact sheet, or None when it has no facts."""
    url = FACTS_URL.format(cik=company.cik)
    text = fact_sheet(company, await fetcher.json(url))
    if text is None:
        return None
    return Document(
        source="xbrl_facts",
        url=url,
        title=f"{company.name} financial facts (SEC XBRL)",
        text=text,
        published_at=datetime.datetime.now(datetime.UTC),
        ticker=company.ticker,
        cik=company.cik,
    )


def rss_items(data: bytes) -> list[tuple[str, str, datetime.datetime | None]]:
    """(title, link, published) of each RSS item.

    Raises:
        SourceError: The feed isn't RSS or declares entities.
    """
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data[:500]:
        raise SourceError("RSS feed with a DTD refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise SourceError(f"bad RSS: {e}") from e
    found = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                published = email.utils.parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                published = None
        if title and link.startswith("https://"):
            found.append((title, link, published))
    return found


async def press_releases(
    fetcher: Fetcher,
    feed_url: str,
    source: str,
    since: datetime.date,
    limit: int,
    known: set[str],
) -> list[Document]:
    """Press releases from an RSS feed (newest ``limit`` since ``since``).

    Args:
        fetcher: The fetcher.
        feed_url: FED_RSS or SEC_RSS.
        source: fed_press or sec_press.
        since: Oldest release date.
        limit: How many to take.
        known: URLs already in the corpus.

    Returns:
        The new documents.
    """
    documents = []
    prefix = "Federal Reserve" if source == "fed_press" else "SEC"
    items = rss_items(await fetcher.get(feed_url))
    for title, link, published in items[:limit]:
        if published is not None and published.date() < since:
            continue
        if link in known:
            continue
        try:
            raw = await fetcher.get(link)
        except SourceError as e:
            _log.info("skipped %s: %s", link, e)
            continue
        text = html_text.to_text(raw.decode("utf-8", errors="replace"))
        if len(text) < _MIN_TEXT_CHARS:
            continue
        documents.append(
            Document(
                source=source,
                url=link,
                title=f"{prefix} press release: {title}",
                text=text,
                published_at=published,
            )
        )
    return documents
