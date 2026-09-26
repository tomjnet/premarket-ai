"""``web_search``: live web search through the self-hosted SearXNG.

Used for counting only: the verify graph counts how many independent
outlets report a story and keeps their titles and links as evidence.
Outlet text is never stored; results live in the Redis cache for an hour.
"""

from __future__ import annotations

from typing import Any
import urllib.parse

import httpx

_MAX_RESULTS = 10
_SNIPPET_CHARS = 300


class WebSearchError(RuntimeError):
    """SearXNG failed or answered garbage."""


def domain_of(url: str) -> str:
    """The lowercase host of a URL, without ``www.``."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


class WebSearch:
    """Client of SearXNG's JSON API."""

    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        """Talks to SearXNG at ``base_url``."""
        self._base_url = base_url
        self._http = http

    async def search(self, query: str, max_results: int = 8) -> dict[str, Any]:
        """Web results for ``query``.

        Args:
            query: The search text (at most 300 characters are sent).
            max_results: How many results (at most 10).

        Returns:
            ``results``: ``title``, ``url``, ``domain``, ``snippet`` and
            ``published`` (when the engine gives a date).

        Raises:
            WebSearchError: The search failed.
        """
        max_results = max(1, min(max_results, _MAX_RESULTS))
        try:
            response = await self._http.get(
                f"{self._base_url}/search",
                params={
                    "q": query[:300],
                    "format": "json",
                    "language": "en",
                    "safesearch": "1",
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise WebSearchError(f"SearXNG failed: {e!r}") from e
        results = []
        for entry in data.get("results", []):
            url = str(entry.get("url", ""))
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                {
                    "title": str(entry.get("title", ""))[:200],
                    "url": url,
                    "domain": domain_of(url),
                    "snippet": " ".join(str(entry.get("content", "")).split())[
                        :_SNIPPET_CHARS
                    ],
                    "published": entry.get("publishedDate"),
                }
            )
            if len(results) == max_results:
                break
        return {"results": results}
