"""Companies and sources the synthetic vendor writes about.

REAL_COMPANIES matches sql/02_legacy_seed.sql. FAKE_COMPANIES are invented;
from increment 2 the entity check proves they are absent from the SEC ticker
registry.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Company:
    """A listed company, real or invented.

    Attributes:
        ticker: The exchange ticker, for example ``AAPL``.
        name: The full legal name, for example ``Apple Inc.``.
        short: The name used in headlines, for example ``Apple``.
        sector: The GICS sector.
    """

    ticker: str
    name: str
    short: str
    sector: str


REAL_COMPANIES: tuple[Company, ...] = (
    Company("AAPL", "Apple Inc.", "Apple", "Information Technology"),
    Company(
        "MSFT", "Microsoft Corporation", "Microsoft", "Information Technology"
    ),
    Company("NVDA", "NVIDIA Corporation", "NVIDIA", "Information Technology"),
    Company("AMZN", "Amazon.com, Inc.", "Amazon", "Consumer Discretionary"),
    Company("GOOGL", "Alphabet Inc.", "Alphabet", "Communication Services"),
    Company("META", "Meta Platforms, Inc.", "Meta", "Communication Services"),
    Company("AVGO", "Broadcom Inc.", "Broadcom", "Information Technology"),
    Company("TSLA", "Tesla, Inc.", "Tesla", "Consumer Discretionary"),
    Company("JPM", "JPMorgan Chase & Co.", "JPMorgan", "Financials"),
    Company("LLY", "Eli Lilly and Company", "Eli Lilly", "Health Care"),
    Company("V", "Visa Inc.", "Visa", "Financials"),
    Company("XOM", "Exxon Mobil Corporation", "Exxon Mobil", "Energy"),
    Company("UNH", "UnitedHealth Group Inc.", "UnitedHealth", "Health Care"),
    Company("MA", "Mastercard Incorporated", "Mastercard", "Financials"),
    Company(
        "COST", "Costco Wholesale Corporation", "Costco", "Consumer Staples"
    ),
    Company("WMT", "Walmart Inc.", "Walmart", "Consumer Staples"),
    Company("JNJ", "Johnson & Johnson", "Johnson & Johnson", "Health Care"),
    Company(
        "PG",
        "The Procter & Gamble Company",
        "Procter & Gamble",
        "Consumer Staples",
    ),
    Company(
        "HD", "The Home Depot, Inc.", "Home Depot", "Consumer Discretionary"
    ),
    Company("ORCL", "Oracle Corporation", "Oracle", "Information Technology"),
)

FAKE_COMPANIES: tuple[Company, ...] = (
    Company(
        "QVXH", "Quantavex Holdings Inc.", "Quantavex", "Information Technology"
    ),
    Company("BRLQ", "Borealiq Therapeutics Corp.", "Borealiq", "Health Care"),
    Company("ZNTRA", "Zentrality Energy Ltd.", "Zentrality", "Energy"),
    Company(
        "KLVM",
        "Kalvimo Semiconductor Inc.",
        "Kalvimo",
        "Information Technology",
    ),
    Company("PXWD", "Praxwood Financial Group", "Praxwood", "Financials"),
    Company("UMBX", "Umbrix Robotics Corp.", "Umbrix", "Industrials"),
)

# The vendor's usual (reputable, in the simulation) outlets. RFC 2606 domains.
TRUSTED_DOMAINS: tuple[str, ...] = (
    "wire.vendornews.example",
    "markets.dailybrief.example",
    "newsdesk.finwire.example",
    "press.marketline.example",
)

# Low-quality outlets the vendor uses to pad the feed.
LOW_QUALITY_DOMAINS: tuple[str, ...] = (
    "stockbuzz-alerts.example",
    "pennyrocket.example",
    "hot-tickers.example",
)

# Lookalikes of real outlets: always on the reserved .test TLD.
SPOOFED_DOMAINS: tuple[str, ...] = (
    "reuters-news.test",
    "bloomberg-markets.test",
    "cnbc-alerts.test",
    "wsj-finance.test",
)
