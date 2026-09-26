"""Companies and sources the synthetic vendor writes about.

The real companies are the lab universe in ``python/config/universe.yaml``
(the 50 largest S&P 500 companies); ``LAB_UNIVERSE_SIZE`` keeps the first N.
FAKE_COMPANIES are invented and absent from the SEC ticker registry, which the
entity check (increment 2) uses to flag them.
"""

from __future__ import annotations

import dataclasses
import functools
import os
import pathlib

import yaml

# src/vendor_sim/companies.py in python/vendor-sim -> python/config.
_REPO_CONFIG_DIR = pathlib.Path(__file__).resolve().parents[3] / "config"
_UNIVERSE_FILE = "universe.yaml"
_MIN_UNIVERSE = 2


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


def config_dir() -> pathlib.Path:
    """The folder with ``universe.yaml``.

    Returns:
        PREMARKET_CONFIG_DIR when set (the container images), else the repo's
        ``python/config``.
    """
    configured = os.environ.get("PREMARKET_CONFIG_DIR", "").strip()
    if configured:
        return pathlib.Path(configured)
    return _REPO_CONFIG_DIR


@functools.cache
def _universe(path: pathlib.Path) -> tuple[Company, ...]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return tuple(
        Company(
            str(entry["ticker"]),
            str(entry["name"]),
            str(entry["short"]),
            str(entry["sector"]),
        )
        for entry in data["companies"]
    )


def real_companies(size: int | None = None) -> tuple[Company, ...]:
    """The lab universe, largest company first.

    Args:
        size: How many companies to keep. None reads LAB_UNIVERSE_SIZE, and
            an empty LAB_UNIVERSE_SIZE keeps them all.

    Returns:
        The first ``size`` companies of ``universe.yaml``.

    Raises:
        ValueError: ``size`` is out of range.
    """
    universe = _universe(config_dir() / _UNIVERSE_FILE)
    if size is None:
        raw = os.environ.get("LAB_UNIVERSE_SIZE", "").strip()
        size = int(raw) if raw else len(universe)
    if not _MIN_UNIVERSE <= size <= len(universe):
        raise ValueError(
            f"LAB_UNIVERSE_SIZE must be in [{_MIN_UNIVERSE}, {len(universe)}],"
            f" got {size}"
        )
    return universe[:size]


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
