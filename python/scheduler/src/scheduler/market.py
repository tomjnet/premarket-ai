"""The market calendar (NYSE, ``XNYS``) and New York time.

Everything is stored in UTC and scheduled in America/New_York. A trading
day is an NYSE session: weekends and holidays are skipped; early-close days
run as normal (the pre-market timeline ends before any early close).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any
import zoneinfo

NEW_YORK = zoneinfo.ZoneInfo("America/New_York")
EXCHANGE = "XNYS"
_WEEKEND = 5

_log = logging.getLogger(__name__)


def now_new_york() -> datetime.datetime:
    """The current time in New York."""
    return datetime.datetime.now(NEW_YORK)


class Calendar:
    """Which days are NYSE sessions (``exchange_calendars``).

    The calendar is loaded on first use (it imports pandas). A date outside
    its range (about a year ahead) falls back to "weekday" with a warning.
    """

    def __init__(self, sessions: Any = None) -> None:
        """Uses ``sessions`` (tests) or loads XNYS on first use.

        Args:
            sessions: An object with ``is_session(date)``, or None.
        """
        self._calendar = sessions

    def _load(self) -> Any:
        if self._calendar is None:
            import exchange_calendars  # noqa: PLC0415 - slow import.

            self._calendar = exchange_calendars.get_calendar(EXCHANGE)
        return self._calendar

    def is_trading_day(self, day: datetime.date) -> bool:
        """True when the NYSE has a session on ``day``.

        Args:
            day: The date (New York).

        Returns:
            Whether it's a trading day.
        """
        try:
            return bool(self._load().is_session(day.isoformat()))
        except Exception as e:  # noqa: BLE001 - out of the calendar's range.
            _log.warning("%s: no XNYS calendar (%r); weekday rule", day, e)
            return day.weekday() < _WEEKEND

    def next_trading_day(self, day: datetime.date) -> datetime.date:
        """The first trading day on or after ``day``."""
        found = day
        for _ in range(15):
            if self.is_trading_day(found):
                return found
            found += datetime.timedelta(days=1)
        return found
