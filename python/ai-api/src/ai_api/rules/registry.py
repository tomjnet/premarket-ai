"""The SEC ticker registry: every US-listed ticker and its company.

Source: ``https://www.sec.gov/files/company_tickers.json`` (about 10,000
tickers). ``ai-api rules`` refreshes it when the copy in Postgres
(``ai.ticker_registry``) is older than REGISTRY_MAX_AGE_DAYS (7), through the
Redis rate limiter, with the contact User-Agent SEC requires (SEC_USER_AGENT
in ``.env``; never hardcoded). Postgres is the cache: a run loads the whole
registry once, so no per-ticker lookups go to the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import dataclasses
import datetime
import gzip
import json
import re
import urllib.request

from ai_api.rules import ratelimit

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_MAX_BYTES = 32 << 20
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
_CONTACT = re.compile(r"\S+@\S+\.\S+")
# Legal-form and filler words: "Apple Inc." and "APPLE INC" are one name.
_NAME_FILLER = frozenset(
    {
        "the",
        "and",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "companies",
        "ltd",
        "limited",
        "plc",
        "llc",
        "lp",
        "holdings",
        "holding",
        "sa",
        "ag",
        "nv",
        "se",
    }
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class RegistryError(RuntimeError):
    """The registry can't be fetched or parsed."""


@dataclasses.dataclass(frozen=True)
class Company:
    """One registry entry.

    Attributes:
        ticker: The ticker as SEC writes it (``BRK-B``).
        cik: SEC's Central Index Key.
        title: The company name as SEC writes it.
    """

    ticker: str
    cik: int
    title: str


def normalize_ticker(ticker: str) -> str:
    """Upper case, and ``.`` as SEC's ``-`` (``BRK.B`` is ``BRK-B``)."""
    return ticker.strip().upper().replace(".", "-")


def normalize_name(name: str) -> tuple[str, ...]:
    """A company name as comparable words.

    ``"The Procter & Gamble Company"`` and ``"PROCTER & GAMBLE Co"`` both
    give ``("procter", "gamble")``. SEC suffixes such as ``/DE/`` or ``/NEW``
    are cut off first.

    Args:
        name: A company name.

    Returns:
        The lowercase words without legal forms and fillers.
    """
    text = name.lower().split("/", 1)[0].replace("'", "").replace("’", "")
    return tuple(
        word
        for word in _NON_ALNUM.split(text)
        if word and word not in _NAME_FILLER
    )


class Registry:
    """The loaded registry: ticker and name lookups."""

    def __init__(
        self,
        companies: Iterable[Company],
        refreshed_at: datetime.datetime | None,
    ) -> None:
        """Indexes ``companies`` by normalized ticker and name."""
        self._by_ticker: dict[str, Company] = {}
        self._names: set[tuple[str, ...]] = set()
        for company in companies:
            self._by_ticker[normalize_ticker(company.ticker)] = company
            words = normalize_name(company.title)
            if words:
                self._names.add(words)
        self.refreshed_at = refreshed_at

    def __len__(self) -> int:
        """The number of tickers."""
        return len(self._by_ticker)

    def company(self, ticker: str) -> Company | None:
        """The company listed under ``ticker``, or None."""
        return self._by_ticker.get(normalize_ticker(ticker))

    def has_name(self, name: str) -> bool:
        """True when a registered company has this name (normalized)."""
        words = normalize_name(name)
        return bool(words) and words in self._names

    def describe(self) -> str:
        """``10,381 tickers, refreshed 2026-09-24`` for evidence messages."""
        refreshed = (
            "never refreshed"
            if self.refreshed_at is None
            else f"refreshed {self.refreshed_at.date().isoformat()}"
        )
        return f"{len(self):,} tickers, {refreshed}"


def parse_sec_json(payload: bytes) -> list[Company]:
    """Parses SEC's ``company_tickers.json``.

    Args:
        payload: The JSON: ``{"0": {"cik_str": 320193, "ticker": "AAPL",
            "title": "Apple Inc."}, ...}``.

    Returns:
        One entry per valid ticker (malformed rows are skipped).

    Raises:
        RegistryError: The payload isn't the expected JSON object.
    """
    try:
        data = json.loads(payload)
    except ValueError as e:
        raise RegistryError(f"registry is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise RegistryError("registry must be a JSON object")
    companies = {}
    for row in data.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        title = str(row.get("title", "")).strip()
        try:
            cik = int(row.get("cik_str", ""))
        except (TypeError, ValueError):
            continue
        if _TICKER.match(ticker) and title:
            companies.setdefault(ticker, Company(ticker, cik, title))
    return list(companies.values())


def check_user_agent(user_agent: str) -> str:
    """Validates SEC_USER_AGENT: a name and a contact email.

    Args:
        user_agent: For example ``premarket-ai lab you@example.com``.

    Returns:
        The stripped value.

    Raises:
        RegistryError: It's empty or has no email address.
    """
    value = user_agent.strip()
    if not _CONTACT.search(value):
        raise RegistryError(
            "SEC_USER_AGENT must name you and give a contact email, e.g. "
            "'premarket-ai lab you@example.com' (SEC fair-access policy)"
        )
    return value


def _download(url: str, user_agent: str, timeout_s: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        body = response.read(_MAX_BYTES + 1)
        encoding = response.headers.get("Content-Encoding", "")
    if len(body) > _MAX_BYTES:
        raise RegistryError("registry response is too large")
    if encoding == "gzip":
        body = gzip.decompress(body)
    return body


async def fetch(
    user_agent: str,
    limiter: ratelimit.TokenBucket,
    url: str = SEC_TICKERS_URL,
    timeout_s: float = 30.0,
) -> list[Company]:
    """Downloads and parses the registry, within the EDGAR rate limit.

    Args:
        user_agent: The SEC_USER_AGENT value.
        limiter: The shared EDGAR token bucket.
        url: The registry URL.
        timeout_s: Network timeout.

    Returns:
        The registry entries.

    Raises:
        RegistryError: Bad User-Agent, network error or bad payload.
    """
    agent = check_user_agent(user_agent)
    await limiter.acquire()
    try:
        payload = await asyncio.to_thread(_download, url, agent, timeout_s)
    except OSError as e:
        raise RegistryError(f"GET {url} failed: {e}") from e
    companies = parse_sec_json(payload)
    if not companies:
        raise RegistryError("registry is empty")
    return companies
