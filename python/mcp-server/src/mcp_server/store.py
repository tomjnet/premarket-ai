"""The tools' Postgres reads (a read-only role, read-only transactions).

- The SEC ticker registry (``ai.ticker_registry``) and the lab universe
  (``universe.yaml``, for a company's size rank).
- Source reputations (``ai.source_reputation``).
- Verdicts and their evidence (``ai.verification``, ``ai.evidence``).
- A day's verified items and its pre-market brief (``ai.brief``,
  increment 5).
"""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import re
from typing import Any, Protocol

from psycopg import rows
from psycopg_pool import AsyncConnectionPool
import yaml

_TICKER = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
_VENDOR_ID = re.compile(r"^VND-\d{8}-\d{3,5}$")
_MAX_NAME_MATCHES = 5
_MAX_EVIDENCE = 30

_VERIFICATION_SQL = """
SELECT n.id AS news_id, n.feed_date, n.vendor_item_id, r.headline,
       r.source_domain, r.tickers, v.status, v.verdict::text AS verdict,
       v.confidence, v.reason_codes, v.rationale, v.review_status,
       v.rule_verdict::text AS rule_verdict,
       v.judge_verdict::text AS judge_verdict, v.judge_model, v.escalated,
       v.impact, v.verified_at
FROM ai.news_item n
JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)
LEFT JOIN ai.verification v ON v.news_id = n.id
WHERE n.vendor_item_id = %s
"""


# The day's verified unique items, highest market impact first (no bodies:
# get_verification has the evidence of one).
_NEWS_SQL = """
SELECT n.vendor_item_id, r.headline, r.source_domain, r.tickers,
       v.status, v.verdict::text AS verdict, v.confidence, v.reason_codes,
       v.review_status, v.impact
FROM ai.verification v
JOIN ai.news_item n ON n.id = v.news_id
JOIN ai.v_raw_news r USING (feed_date, vendor_item_id)
WHERE n.feed_date = %(day)s
  AND (%(ticker)s::text IS NULL OR %(ticker)s::text = ANY (r.tickers))
  AND (%(verdict)s::text IS NULL OR v.verdict::text = %(verdict)s)
ORDER BY v.impact_score DESC NULLS LAST, n.vendor_item_id
LIMIT %(limit)s
"""
_MAX_NEWS = 25
_VERDICTS = frozenset({"VERIFIED", "UNVERIFIED", "MISLEADING", "FAKE"})
_BRIEF_ITEMS = 40


def sec_ticker(ticker: str) -> str:
    """A ticker as SEC writes it: upper case, ``.`` as ``-`` (BRK-B)."""
    return ticker.strip().upper().replace(".", "-")


@dataclasses.dataclass(frozen=True)
class Member:
    """A lab-universe company and its market-cap rank (0 is the largest)."""

    ticker: str
    name: str
    rank: int


def load_universe(config_dir: pathlib.Path) -> dict[str, Member]:
    """The universe by SEC ticker; empty when the file isn't there."""
    path = config_dir / "universe.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        sec_ticker(str(c["ticker"])): Member(
            str(c["ticker"]), str(c["name"]), i
        )
        for i, c in enumerate(data["companies"])
    }


class Store(Protocol):
    """The reads the tools make (``PostgresStore``)."""

    async def registry_size(self) -> int:
        """Tickers in the registry (0: never downloaded)."""
        ...

    async def company(self, ticker: str) -> dict[str, Any] | None:
        """The registry row of a ticker (SEC form), or None."""
        ...

    async def companies_named(self, name: str) -> list[dict[str, Any]]:
        """Registry rows whose title contains ``name``."""
        ...

    async def reputation(self, domain: str) -> dict[str, Any] | None:
        """The reputation row of exactly ``domain``, or None."""
        ...

    async def verification(self, vendor_item_id: str) -> dict[str, Any] | None:
        """An item and its verdict (null fields when not verified)."""
        ...

    async def evidence(self, news_id: int) -> list[dict[str, Any]]:
        """The verdict's evidence, in order."""
        ...

    async def news(
        self, day: datetime.date, ticker: str | None, verdict: str | None
    ) -> list[dict[str, Any]]:
        """The day's verified unique items (increment 5)."""
        ...

    async def brief(self, day: datetime.date) -> dict[str, Any] | None:
        """The day's newest DONE brief (increment 5), or None."""
        ...


class PostgresStore:
    """``Store`` over the read-only pool."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses connections from ``pool``."""
        self._pool = pool

    async def _all(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=rows.dict_row)
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def registry_size(self) -> int:
        """See ``Store``."""
        found = await self._all("SELECT count(*) AS n FROM ai.ticker_registry")
        return int(found[0]["n"])

    async def company(self, ticker: str) -> dict[str, Any] | None:
        """See ``Store``."""
        found = await self._all(
            "SELECT ticker, cik, title FROM ai.ticker_registry"
            " WHERE upper(ticker) = %s",
            (ticker,),
        )
        return found[0] if found else None

    async def companies_named(self, name: str) -> list[dict[str, Any]]:
        """See ``Store``."""
        pattern = (
            "%"
            + name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        return await self._all(
            "SELECT ticker, cik, title FROM ai.ticker_registry"
            " WHERE title ILIKE %s ORDER BY length(title), ticker LIMIT %s",
            (pattern, _MAX_NAME_MATCHES),
        )

    async def reputation(self, domain: str) -> dict[str, Any] | None:
        """See ``Store``."""
        found = await self._all(
            "SELECT domain, tier, reputation, note FROM ai.source_reputation"
            " WHERE domain = %s",
            (domain,),
        )
        return found[0] if found else None

    async def verification(self, vendor_item_id: str) -> dict[str, Any] | None:
        """See ``Store``."""
        found = await self._all(_VERIFICATION_SQL, (vendor_item_id,))
        return found[0] if found else None

    async def evidence(self, news_id: int) -> list[dict[str, Any]]:
        """See ``Store``."""
        return await self._all(
            'SELECT seq, check_type AS "check", code, message, url'
            " FROM ai.evidence WHERE news_id = %s ORDER BY seq LIMIT %s",
            (news_id, _MAX_EVIDENCE),
        )

    async def news(
        self, day: datetime.date, ticker: str | None, verdict: str | None
    ) -> list[dict[str, Any]]:
        """See ``Store``."""
        return await self._all(
            _NEWS_SQL,
            {
                "day": day,
                "ticker": ticker,
                "verdict": verdict,
                "limit": _MAX_NEWS,
            },
        )

    async def brief(self, day: datetime.date) -> dict[str, Any] | None:
        """See ``Store``."""
        found = await self._all(
            "SELECT feed_date, edition, finished_at, overview, content"
            " FROM ai.brief WHERE feed_date = %s AND status = 'DONE'"
            " ORDER BY finished_at DESC LIMIT 1",
            (day,),
        )
        return found[0] if found else None


class Lookups:
    """The registry, reputation and verdict tools' logic."""

    def __init__(self, store: Store, universe: dict[str, Member]) -> None:
        """Answers from ``store`` and the universe."""
        self._store = store
        self._universe = universe

    async def lookup_company(self, query: str) -> dict[str, Any]:
        """A company by ticker (exact) or by name (contains).

        Args:
            query: A ticker (``AAPL``, ``BRK.B``) or part of a name.

        Returns:
            ``found``, ``ticker``, ``cik``, ``name``, ``rank`` (in the lab
            universe, 0 is the largest), ``in_universe`` and ``registry``
            (False: the registry was never downloaded, so "not found"
            means nothing); for a name, up to 5 ``matches``.
        """
        query = query.strip()[:120]
        loaded = await self._store.registry_size() > 0
        if _TICKER.match(query) and query.upper() == query:
            ticker = sec_ticker(query)
            member = self._universe.get(ticker)
            found = await self._store.company(ticker)
            answer: dict[str, Any] = {
                "found": found is not None,
                "ticker": query,
                "rank": None if member is None else member.rank,
                "in_universe": member is not None,
                "registry": loaded,
            }
            if found is not None:
                answer.update(cik=found["cik"], name=found["title"])
            return answer
        matches = await self._store.companies_named(query)
        return {
            "found": bool(matches),
            "query": query,
            "registry": loaded,
            "matches": [
                {
                    "ticker": m["ticker"],
                    "cik": m["cik"],
                    "name": m["title"],
                    "in_universe": sec_ticker(m["ticker"]) in self._universe,
                }
                for m in matches
            ],
        }

    async def source_reputation(self, domain: str) -> dict[str, Any]:
        """A domain's tier, or its closest listed parent's.

        Args:
            domain: A host name (``news.example.com``).

        Returns:
            ``domain``, ``tier`` (``unknown`` when not listed),
            ``reputation`` (0 to 1) and ``note``.
        """
        host = domain.strip().lower().rstrip(".")[:253]
        labels = host.split(".")
        for i in range(len(labels) - 1):
            found = await self._store.reputation(".".join(labels[i:]))
            if found is not None:
                return {
                    "domain": host,
                    "listed_as": found["domain"],
                    "tier": found["tier"],
                    "reputation": float(found["reputation"]),
                    "note": found["note"],
                }
        return {"domain": host, "tier": "unknown", "reputation": None}

    async def verification(self, vendor_item_id: str) -> dict[str, Any]:
        """An item's verdict and evidence.

        Args:
            vendor_item_id: The vendor's id, ``VND-20260924-012``.

        Returns:
            ``found``; the headline, verdict, confidence, reason codes,
            rationale, review status and evidence when verified.
        """
        ident = vendor_item_id.strip().upper()
        if not _VENDOR_ID.match(ident):
            return {"found": False, "error": "expected VND-YYYYMMDD-NNN"}
        found = await self._store.verification(ident)
        if found is None:
            return {"found": False, "vendor_item_id": ident}
        answer = {
            "found": True,
            "vendor_item_id": ident,
            "feed_date": found["feed_date"].isoformat(),
            "headline": found["headline"],
            "source_domain": found["source_domain"],
            "tickers": list(found["tickers"]),
            "verified": found["verdict"] is not None,
        }
        if found["verdict"] is None:
            return answer
        answer.update(
            verdict=found["verdict"],
            confidence=found["confidence"],
            reason_codes=list(found["reason_codes"]),
            rationale=found["rationale"],
            status=found["status"],
            review_status=found["review_status"],
            rule_verdict=found["rule_verdict"],
            judge_verdict=found["judge_verdict"],
            judge_model=found["judge_model"],
            escalated=found["escalated"],
            impact=found["impact"],
            verified_at=found["verified_at"].isoformat(),
            evidence=[
                {f"E{e['seq']}": e["message"], "check": e["check"]}
                | ({"url": e["url"]} if e["url"] else {})
                for e in await self._store.evidence(found["news_id"])
            ],
        )
        return answer

    async def news(
        self, date: str, ticker: str | None, verdict: str | None
    ) -> dict[str, Any]:
        """The day's verified items, highest market impact first.

        Args:
            date: YYYY-MM-DD.
            ticker: Only items about this ticker.
            verdict: Only this verdict.

        Returns:
            ``date``, ``count`` and ``items`` (vendor id, headline, source,
            tickers, verdict, confidence, reason codes, review status,
            impact), at most 25; or ``error``.
        """
        try:
            day = datetime.date.fromisoformat(date.strip())
        except ValueError:
            return {"error": "expected a date YYYY-MM-DD"}
        if ticker is not None:
            ticker = ticker.strip().upper()
            if not _TICKER.match(ticker):
                return {"error": "not a ticker"}
        if verdict is not None:
            verdict = verdict.strip().upper()
            if verdict not in _VERDICTS:
                return {"error": f"verdict is one of {sorted(_VERDICTS)}"}
        found = await self._store.news(day, ticker, verdict)
        return {
            "date": day.isoformat(),
            "count": len(found),
            "items": [
                {
                    "vendor_item_id": row["vendor_item_id"],
                    "headline": row["headline"],
                    "source_domain": row["source_domain"],
                    "tickers": list(row["tickers"]),
                    "verdict": row["verdict"],
                    "confidence": row["confidence"],
                    "reason_codes": list(row["reason_codes"]),
                    "pending_review": row["status"] == "PENDING_REVIEW",
                    "review_status": row["review_status"],
                    "impact": row["impact"],
                }
                for row in found
            ],
        }

    async def brief(self, date: str) -> dict[str, Any]:
        """The day's pre-market brief (its newest finished edition).

        Args:
            date: YYYY-MM-DD.

        Returns:
            ``found``; the edition, the overview, the counts and the items
            (number, section, vendor id, headline, summary, tickers,
            sector, verdict, impact) when there is one.
        """
        try:
            day = datetime.date.fromisoformat(date.strip())
        except ValueError:
            return {"found": False, "error": "expected a date YYYY-MM-DD"}
        found = await self._store.brief(day)
        if found is None:
            return {"found": False, "date": day.isoformat()}
        content = found["content"] or {}
        items = content.get("items", [])
        return {
            "found": True,
            "date": day.isoformat(),
            "edition": found["edition"],
            "finished_at": found["finished_at"].isoformat(),
            "overview": found["overview"],
            "counts": content.get("counts", {}),
            "items": [
                {
                    k: item.get(k)
                    for k in (
                        "n",
                        "section",
                        "vendor_item_id",
                        "headline",
                        "summary",
                        "tickers",
                        "sector",
                        "verdict",
                        "impact",
                    )
                }
                for item in items[:_BRIEF_ITEMS]
            ],
        }
