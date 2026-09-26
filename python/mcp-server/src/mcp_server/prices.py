"""``get_price_history``: daily closes from yfinance.

Lab only: yfinance reads Yahoo Finance under personal-use terms (Alpha
Vantage or Polygon for anything beyond the lab). The verify graph uses it
to check claims such as "shares jumped 20%" against real moves.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_MAX_DAYS = 60


class PriceError(RuntimeError):
    """No prices for the ticker, or Yahoo failed."""


def yahoo_symbol(ticker: str) -> str:
    """Yahoo writes share classes with ``-`` (BRK.B is BRK-B).

    Raises:
        PriceError: Not a ticker.
    """
    ticker = ticker.strip().upper()
    if not _TICKER.match(ticker):
        raise PriceError(f"{ticker!r} is not a ticker")
    return ticker.replace(".", "-")


def closes_with_changes(rows: list[tuple[str, float]]) -> list[dict[str, Any]]:
    """Daily closes with the percent change from the day before."""
    found = []
    previous = None
    for day, close in rows:
        change = None
        if previous:
            change = round((close - previous) / previous * 100, 2)
        found.append(
            {"date": day, "close": round(close, 4), "change_pct": change}
        )
        previous = close
    return found


def _history(symbol: str, days: int) -> list[tuple[str, float]]:
    import yfinance  # noqa: PLC0415 - slow to import; the tool may not run.

    frame = yfinance.Ticker(symbol).history(
        period=f"{days + 7}d", interval="1d", auto_adjust=False
    )
    return [
        (index.date().isoformat(), float(close))
        for index, close in frame["Close"].dropna().items()
    ][-(days + 1) :]


async def price_history(ticker: str, days: int = 10) -> dict[str, Any]:
    """The last ``days`` trading days of a ticker.

    Args:
        ticker: A US ticker (``AAPL``, ``BRK.B``).
        days: Trading days (at most 60).

    Returns:
        ``ticker``, ``symbol`` and ``prices``: ``date``, ``close`` and
        ``change_pct``, oldest first.

    Raises:
        PriceError: No prices (an unknown ticker) or Yahoo failed.
    """
    days = max(1, min(days, _MAX_DAYS))
    symbol = yahoo_symbol(ticker)
    try:
        rows = await asyncio.to_thread(_history, symbol, days)
    except Exception as e:  # noqa: BLE001 - yfinance raises many kinds.
        raise PriceError(f"price history of {symbol} failed: {e!r}") from e
    if not rows:
        raise PriceError(f"no prices for {symbol}")
    return {
        "ticker": ticker.strip().upper(),
        "symbol": symbol,
        "prices": closes_with_changes(rows)[1:],
    }
