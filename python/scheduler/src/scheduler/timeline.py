"""The daily timeline (America/New_York).

=====  ===========  ========================================================
Time   Job          What
=====  ===========  ========================================================
02:00  retention    delete AI results older than RETENTION_DAYS (every day,
                    both modes)
05:00  corpus       new EDGAR 8-Ks and Fed/SEC releases (SCHEDULER_CORPUS)
05:30  (ingest)     the C++20 ingester's own cron, not the scheduler's
06:00  pipeline     wait for the ingest run, then rules, AI (dedup L3,
                    summaries) and the verify run
06:15  sla-ingest   the ingest run is DONE
06:30  sla-backlog  at most SLA_BACKLOG_MAX verify jobs still queued
07:00  sla-verify   the verify run is DONE
07:15  brief        the morning brief (waits for the verify run until 09:00)
07:30  sla-brief    the morning brief was published by 07:30
09:00  refresh      the refresh edition (items reviewed since 07:15)
09:30  expire       market open: pending reviews expire
09:35  scorecard    the day's vendor scorecard (billable items)
=====  ===========  ========================================================

Every job except ``retention`` runs on NYSE trading days only, and only in
``RUN_MODE=production``. A job whose time has passed when the scheduler
starts runs at once if it is still inside its window (``until``) and
hasn't finished today: a restart at 06:20 still runs the day.
"""

from __future__ import annotations

import dataclasses
import datetime

_T = datetime.time


@dataclasses.dataclass(frozen=True)
class Slot:
    """One scheduled job.

    Attributes:
        job: The job name (``ai.schedule_run.job``).
        at: When it starts (New York).
        until: The end of its catch-up window; None for SLA checks, which
            are only meaningful at their time.
        every_day: Runs on non-trading days too (retention).
        production_only: Only in RUN_MODE=production.
    """

    job: str
    at: datetime.time
    until: datetime.time | None = None
    every_day: bool = False
    production_only: bool = True

    @property
    def is_sla(self) -> bool:
        """True for an SLA check."""
        return self.job.startswith("sla-")


TIMELINE: tuple[Slot, ...] = (
    Slot(
        "retention", _T(2, 0), _T(5, 0), every_day=True, production_only=False
    ),
    Slot("corpus", _T(5, 0), _T(6, 0)),
    Slot("pipeline", _T(6, 0), _T(9, 30)),
    Slot("sla-ingest", _T(6, 15)),
    Slot("sla-backlog", _T(6, 30)),
    Slot("sla-verify", _T(7, 0)),
    Slot("brief", _T(7, 15), _T(9, 0)),
    Slot("sla-brief", _T(7, 30)),
    Slot("refresh", _T(9, 0), _T(9, 30)),
    Slot("expire", _T(9, 30), _T(16, 0)),
    Slot("scorecard", _T(9, 35), _T(23, 0)),
)

JOBS = tuple(slot.job for slot in TIMELINE)


def slot(job: str) -> Slot:
    """The slot of ``job``.

    Raises:
        KeyError: No such job.
    """
    for found in TIMELINE:
        if found.job == job:
            return found
    raise KeyError(job)


def active(production: bool, corpus: bool = True) -> tuple[Slot, ...]:
    """The slots that run in this mode."""
    return tuple(
        s
        for s in TIMELINE
        if (production or not s.production_only)
        and (corpus or s.job != "corpus")
    )


def catch_up(slots: tuple[Slot, ...], now: datetime.time) -> tuple[Slot, ...]:
    """The jobs whose time passed but whose window is still open."""
    return tuple(
        s for s in slots if s.until is not None and s.at <= now < s.until
    )
