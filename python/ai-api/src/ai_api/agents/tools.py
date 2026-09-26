"""The chat specialists' tools and what they found.

The tools are the MCP server's (langchain-mcp-adapters turns each one into
a LangChain tool); each specialist gets only its allowlist, and every tool
is read-only. There are no write tools anywhere.

Every tool result becomes a ``Finding``: a numbered source of the answer.
The writer cites tool results, never a specialist's own words, so every
fact in an answer points to data. Results are sanitized (they can carry
vendor text: headlines, web snippets) and cut to 2,000 characters.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from ai_api.guard import sanitize

_MAX_TEXT = 2000
_MAX_ARG = 80

# Tool -> (source kind, trusted, title). "Trusted" sources are
# premarket-ai's own checks and market data; web results only show who
# else reports a story.
KINDS: dict[str, tuple[str, bool, str]] = {
    "list_news": ("verification", True, "premarket-ai verdicts"),
    "get_verification": ("verification", True, "premarket-ai verification"),
    "lookup_company": ("company", True, "SEC ticker registry"),
    "get_source_reputation": ("reputation", True, "Source reputation"),
    "search_news": ("corpus_search", True, "SEC filings and releases"),
    "get_price_history": ("prices", True, "Price history (Yahoo Finance)"),
    "get_brief": ("brief", True, "premarket-ai pre-market brief"),
    "web_search": ("web", False, "Web search results"),
    "fetch_url": ("web_page", False, "Web page"),
}


@dataclasses.dataclass(frozen=True)
class Finding:
    """One tool result a specialist got.

    Attributes:
        agent: The specialist.
        tool: The tool's name.
        kind: The source kind (``KINDS``).
        trusted: False for web results.
        title: What it is, with its main argument.
        text: The result as text (sanitized, at most 2,000 characters).
        url: A link: the page ``fetch_url`` read, else empty.
        ticker: The ticker it was about, when it had one.
    """

    agent: str
    tool: str
    kind: str
    trusted: bool
    title: str
    text: str
    url: str = ""
    ticker: str | None = None

    def to_json(self) -> dict[str, Any]:
        """JSON-safe (the supervisor graph's state)."""
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Finding:
        """The inverse of ``to_json``."""
        return cls(**data)


def content_text(content: Any) -> str:
    """A tool message's content as one string (text blocks joined)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    return str(content)


def _compact(text: str) -> str:
    """JSON re-dumped on one line (shorter for the model), else the text."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    return json.dumps(data, ensure_ascii=False, separators=(", ", ": "))


def describe_args(args: dict[str, Any]) -> str:
    """Tool arguments for a progress line (plain text, short)."""
    parts = []
    for name, value in args.items():
        shown = " ".join(str(value).split())[:_MAX_ARG]
        parts.append(f"{name}={shown}")
    return ", ".join(parts)


def finding(
    agent: str, tool: str, args: dict[str, Any], content: Any
) -> Finding:
    """The ``Finding`` of one tool call.

    Args:
        agent: The specialist that called it.
        tool: The tool's name.
        args: Its arguments.
        content: The tool message's content.

    Returns:
        The finding.
    """
    kind, trusted, label = KINDS.get(tool, ("tool", False, tool))
    main = next(
        (
            str(args[k])
            for k in ("vendor_item_id", "ticker", "query", "domain", "url")
            if args.get(k)
        ),
        str(args.get("date", "")),
    )
    title = label if not main else f"{label}: {main[:_MAX_ARG]}"
    clean = sanitize.sanitize(title, _compact(content_text(content)))
    ticker = args.get("ticker")
    return Finding(
        agent=agent,
        tool=tool,
        kind=kind,
        trusted=trusted,
        title=clean.headline,
        text=clean.body[:_MAX_TEXT],
        url=str(args.get("url", "")) if tool == "fetch_url" else "",
        ticker=None if not ticker else str(ticker).upper()[:12],
    )
