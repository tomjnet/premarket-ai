"""The tools the checks call: the MCP server in the stack, local in the eval.

**Code calls the tools, not the LLM** (guardrail 4): the checks call them
with arguments taken from the item's structured fields (tickers, domain,
headline), so injected text in a story has no way to trigger a tool. The
judge never sees a tool.

- ``McpTools``: the read-only tools of ``mcp-server`` (streamable HTTP,
  service token), through ``langchain-mcp-adapters``.
- ``LocalTools``: the same answers from the SEC registry fixture and
  ``sources.yaml``, with no filings, web or prices (the hosted eval).
- ``RecordingTools``: wraps either and logs every call, for the red-team
  eval ("no tool misuse").
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
from typing import Any, Protocol

from ai_api.rag import universe as universe_lib
from ai_api.rules import checks as rule_checks
from ai_api.rules import registry as registry_lib

_log = logging.getLogger(__name__)
SERVER = "premarket"
# Every tool the verify graph may call (all read-only).
ALLOWED = frozenset(
    {
        "lookup_company",
        "get_source_reputation",
        "search_news",
        "web_search",
        "get_price_history",
    }
)


class ToolError(RuntimeError):
    """A tool call failed (the check records it and carries on)."""


class Tools(Protocol):
    """The read-only tools of the checks."""

    async def lookup_company(self, ticker: str) -> dict[str, Any]:
        """``found``, ``ticker``, ``cik``, ``name``, ``rank`` and more."""
        ...

    async def source_reputation(self, domain: str) -> dict[str, Any]:
        """``domain``, ``tier`` (``unknown``: not listed), ``reputation``."""
        ...

    async def search_filings(
        self, query: str, ticker: str | None, day: datetime.date, days: int
    ) -> list[dict[str, Any]]:
        """Trusted-corpus chunks of the ``days`` before ``day``."""
        ...

    async def web_search(self, query: str) -> list[dict[str, Any]]:
        """Web results: ``title``, ``url``, ``domain``, ``snippet``."""
        ...

    async def price_history(
        self, ticker: str, days: int
    ) -> list[dict[str, Any]]:
        """Daily closes: ``date``, ``close``, ``change_pct``."""
        ...


def _payload(result: Any) -> Any:
    """The JSON a FastMCP tool returned (structured or as text)."""
    if getattr(result, "isError", False):
        texts = [getattr(c, "text", "") for c in result.content or []]
        raise ToolError(" ".join(t for t in texts if t) or "tool error")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # Non-object return values are wrapped as {"result": ...}.
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    for content in result.content or []:
        text = getattr(content, "text", None)
        if text:
            return json.loads(text)
    return None


class McpTools:
    """``Tools`` over the MCP server (one session per item)."""

    def __init__(self, session: Any) -> None:
        """Uses an initialized ``mcp.ClientSession``."""
        self._session = session

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in ALLOWED:
            raise ToolError(f"{name} is not an allowed tool")
        try:
            result = await self._session.call_tool(name, arguments)
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001 - one error type for checks.
            raise ToolError(f"{name}: {e!r}") from e
        return _payload(result)

    async def lookup_company(self, ticker: str) -> dict[str, Any]:
        """See ``Tools``."""
        return await self._call("lookup_company", {"query": ticker})

    async def source_reputation(self, domain: str) -> dict[str, Any]:
        """See ``Tools``."""
        return await self._call("get_source_reputation", {"domain": domain})

    async def search_filings(
        self, query: str, ticker: str | None, day: datetime.date, days: int
    ) -> list[dict[str, Any]]:
        """See ``Tools``."""
        found = await self._call(
            "search_news",
            {
                "query": query,
                "date": day.isoformat(),
                "ticker": ticker,
                "days": days,
            },
        )
        return list((found or {}).get("results", []))

    async def web_search(self, query: str) -> list[dict[str, Any]]:
        """See ``Tools``."""
        found = await self._call("web_search", {"query": query})
        return list((found or {}).get("results", []))

    async def price_history(
        self, ticker: str, days: int
    ) -> list[dict[str, Any]]:
        """See ``Tools``."""
        found = await self._call(
            "get_price_history", {"ticker": ticker, "days": days}
        )
        return list((found or {}).get("prices", []))


class LocalTools:
    """``Tools`` without network: registry, reputations and the universe."""

    def __init__(
        self,
        registry: registry_lib.Registry | None,
        sources: rule_checks.SourcePolicy,
        members: list[universe_lib.Member],
    ) -> None:
        """Answers from these (no filings, web results or prices)."""
        self._registry = registry
        self._sources = sources
        self._ranks = {m.ticker: i for i, m in enumerate(members)}

    async def lookup_company(self, ticker: str) -> dict[str, Any]:
        """See ``Tools``."""
        rank = self._ranks.get(ticker)
        company = None
        if self._registry is not None:
            company = self._registry.company(ticker)
        if company is None:
            return {
                "found": False,
                "ticker": ticker,
                "rank": rank,
                "in_universe": rank is not None,
                "registry": self._registry is not None,
            }
        return {
            "found": True,
            "ticker": ticker,
            "cik": company.cik,
            "name": company.title,
            "rank": rank,
            "in_universe": rank is not None,
            "registry": True,
        }

    async def source_reputation(self, domain: str) -> dict[str, Any]:
        """See ``Tools``."""
        reputation = self._sources.reputation(domain)
        if reputation is None:
            return {"domain": domain, "tier": "unknown", "reputation": None}
        return {
            "domain": domain,
            "tier": reputation.tier,
            "reputation": reputation.reputation,
            "note": reputation.note,
        }

    async def search_filings(
        self, query: str, ticker: str | None, day: datetime.date, days: int
    ) -> list[dict[str, Any]]:
        """No corpus offline."""
        del query, ticker, day, days
        return []

    async def web_search(self, query: str) -> list[dict[str, Any]]:
        """No web offline."""
        del query
        return []

    async def price_history(
        self, ticker: str, days: int
    ) -> list[dict[str, Any]]:
        """No prices offline."""
        del ticker, days
        return []


@dataclasses.dataclass(frozen=True)
class Call:
    """One recorded tool call."""

    name: str
    arguments: dict[str, Any]


class RecordingTools:
    """Logs every call of the wrapped tools (the red-team eval)."""

    def __init__(self, inner: Tools) -> None:
        """Wraps ``inner``."""
        self._inner = inner
        self.calls: list[Call] = []

    async def lookup_company(self, ticker: str) -> dict[str, Any]:
        """See ``Tools``."""
        self.calls.append(Call("lookup_company", {"query": ticker}))
        return await self._inner.lookup_company(ticker)

    async def source_reputation(self, domain: str) -> dict[str, Any]:
        """See ``Tools``."""
        self.calls.append(Call("get_source_reputation", {"domain": domain}))
        return await self._inner.source_reputation(domain)

    async def search_filings(
        self, query: str, ticker: str | None, day: datetime.date, days: int
    ) -> list[dict[str, Any]]:
        """See ``Tools``."""
        self.calls.append(
            Call("search_news", {"query": query, "ticker": ticker})
        )
        return await self._inner.search_filings(query, ticker, day, days)

    async def web_search(self, query: str) -> list[dict[str, Any]]:
        """See ``Tools``."""
        self.calls.append(Call("web_search", {"query": query}))
        return await self._inner.web_search(query)

    async def price_history(
        self, ticker: str, days: int
    ) -> list[dict[str, Any]]:
        """See ``Tools``."""
        self.calls.append(Call("get_price_history", {"ticker": ticker}))
        return await self._inner.price_history(ticker, days)


class UnavailableTools:
    """Every call fails: the MCP server couldn't be reached.

    The checks then record "unavailable" and decide nothing from it; the
    rule engine's codes and the judge still apply.
    """

    def __init__(self, reason: str) -> None:
        """Fails with ``reason``."""
        self._reason = reason

    def _fail(self) -> ToolError:
        return ToolError(f"MCP server unavailable: {self._reason}")

    async def lookup_company(self, ticker: str) -> dict[str, Any]:
        """See ``Tools``."""
        del ticker
        raise self._fail()

    async def source_reputation(self, domain: str) -> dict[str, Any]:
        """See ``Tools``."""
        del domain
        raise self._fail()

    async def search_filings(
        self, query: str, ticker: str | None, day: datetime.date, days: int
    ) -> list[dict[str, Any]]:
        """See ``Tools``."""
        del query, ticker, day, days
        raise self._fail()

    async def web_search(self, query: str) -> list[dict[str, Any]]:
        """See ``Tools``."""
        del query
        raise self._fail()

    async def price_history(
        self, ticker: str, days: int
    ) -> list[dict[str, Any]]:
        """See ``Tools``."""
        del ticker, days
        raise self._fail()
