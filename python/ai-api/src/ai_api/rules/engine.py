"""The rule engine: every deterministic check on one feed date's items.

No LLM, no network per item: the duplicate check (Redis), the SEC registry
(loaded once per run), the source policy and dated text. Storage is the
caller's job (``repository`` in the stack, in-memory in the eval).
"""

from __future__ import annotations

import collections
from collections.abc import Sequence
import dataclasses
import datetime

from ai_api.dedup import normalize
from ai_api.dedup import service
from ai_api.rules import checks
from ai_api.rules import registry as registry_lib

RULES_VERSION = "rules-v1"
# Reason codes in display order; an item lists them in this order.
REASON_ORDER = (
    checks.FAKE_COMPANY,
    checks.FAKE_TICKER,
    checks.SPOOFED_SOURCE,
    checks.STALE,
)
_LEVEL_NAMES = {
    "L0": "Same article URL (L0)",
    "L1": "Exact copy (L1)",
    "L2": "Near duplicate (L2)",
}


@dataclasses.dataclass(frozen=True)
class RawItem:
    """One vendor item of ``ai.v_raw_news`` with its ``ai.news_item`` id.

    Attributes:
        news_id: The ``ai.news_item`` id.
        feed_date: The feed date.
        vendor_item_id: The vendor's id.
        headline: The headline.
        body: The body.
        source_url: The source link.
        source_domain: The domain the vendor names.
        tickers: The tickers.
    """

    news_id: int
    feed_date: datetime.date
    vendor_item_id: str
    headline: str
    body: str
    source_url: str
    source_domain: str
    tickers: tuple[str, ...]

    def dedup_item(self) -> service.DedupItem:
        """The fields the duplicate check needs."""
        return service.DedupItem(
            news_id=self.news_id,
            feed_date=self.feed_date,
            vendor_item_id=self.vendor_item_id,
            headline=self.headline,
            body=self.body,
            source_url=self.source_url,
            tickers=self.tickers,
        )


@dataclasses.dataclass(frozen=True)
class ItemResult:
    """What the rules found for one item.

    Attributes:
        item: The item.
        reason_codes: Its reason codes, in ``REASON_ORDER``.
        evidence: Why, one entry per finding.
        duplicate: The earlier item it copies, or None.
    """

    item: RawItem
    reason_codes: tuple[str, ...]
    evidence: tuple[checks.Evidence, ...]
    duplicate: service.DedupMatch | None


@dataclasses.dataclass(frozen=True)
class DaySummary:
    """Counts for the run log and ``ai.rule_run``.

    Attributes:
        items: Items checked.
        duplicates: Items that copy an earlier item.
        by_type: Duplicates per match type (url, exact, near).
        stale: Items flagged STALE.
        flagged: Items with at least one reason code.
        reason_counts: Items per reason code.
    """

    items: int
    duplicates: int
    by_type: dict[str, int]
    stale: int
    flagged: int
    reason_counts: dict[str, int]

    @classmethod
    def of(cls, results: Sequence[ItemResult]) -> DaySummary:
        """Counts ``results``."""
        by_type = collections.Counter(
            r.duplicate.dup_type for r in results if r.duplicate is not None
        )
        reasons = collections.Counter(
            code for r in results for code in r.reason_codes
        )
        return cls(
            items=len(results),
            duplicates=sum(by_type.values()),
            by_type=dict(sorted(by_type.items())),
            stale=reasons.get(checks.STALE, 0),
            flagged=sum(1 for r in results if r.reason_codes),
            reason_counts={code: reasons[code] for code in REASON_ORDER},
        )

    def line(self) -> str:
        """``100 received -> 83 unique, 17 dup (exact 7, near 6, url 4)...``."""
        types = ", ".join(f"{k} {v}" for k, v in self.by_type.items())
        reasons = ", ".join(f"{k} {v}" for k, v in self.reason_counts.items())
        return (
            f"{self.items} received -> {self.items - self.duplicates} unique, "
            f"{self.duplicates} dup ({types or 'none'}); flagged "
            f"{self.flagged}: {reasons}"
        )


def _dedup_evidence(match: service.DedupMatch) -> checks.Evidence:
    detail = ""
    if match.level == "L2":
        detail = (
            f" (SimHash distance {match.score:.0f}, "
            f"{match.word_edits} words differ)"
        )
    text = (
        f"{_LEVEL_NAMES[match.level]}{detail} of "
        f"{match.canonical_vendor_item_id} from "
        f"{match.canonical_feed_date.isoformat()}"
    )
    if match.stale:
        return checks.Evidence(
            "dedup", checks.STALE, f"{text}: re-served old news."
        )
    return checks.Evidence("dedup", None, f"{text}.")


class RuleEngine:
    """Runs every check on a feed date's items, in order."""

    def __init__(
        self,
        dedup: service.DedupService,
        registry: registry_lib.Registry | None,
        sources: checks.SourcePolicy,
        stale_max_age_days: int = 30,
    ) -> None:
        """Wires the checks.

        Args:
            dedup: The duplicate check.
            registry: The SEC registry, or None when it isn't available
                (the entity check is then skipped, never guessed).
            sources: Reputations and brands.
            stale_max_age_days: Dated text older than this is STALE.
        """
        self._dedup = dedup
        self._registry = registry
        self._sources = sources
        self._stale_max_age_days = stale_max_age_days

    async def check_items(self, items: Sequence[RawItem]) -> list[ItemResult]:
        """Checks items in order (earliest feed date, then vendor id).

        Args:
            items: The items, sorted by the caller.

        Returns:
            One result per item.
        """
        return [await self._check(item) for item in items]

    async def _check(self, item: RawItem) -> ItemResult:
        match = await self._dedup.check(item.dedup_item())
        _, body = normalize.strip_boilerplate(item.headline, item.body)
        findings = [
            checks.check_entities(item.tickers, body, self._registry),
            self._sources.check(item.source_url, item.source_domain),
            checks.check_dates(body, item.feed_date, self._stale_max_age_days),
        ]
        codes = {code for finding in findings for code in finding.codes}
        evidence = [e for finding in findings for e in finding.evidence]
        if match is not None:
            dedup = _dedup_evidence(match)
            evidence.insert(0, dedup)
            if dedup.code is not None:
                codes.add(dedup.code)
        return ItemResult(
            item=item,
            reason_codes=tuple(c for c in REASON_ORDER if c in codes),
            evidence=tuple(evidence),
            duplicate=match,
        )
