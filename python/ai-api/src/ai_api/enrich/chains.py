"""The extract and summarize steps (LangChain, structured output).

Each step sends a system prompt plus one spotlighted item and parses the
answer into a pydantic model. A failed parse is retried once. A summary is
checked for investment advice (retried once with a reminder); when the
model can't produce a clean one, the item gets the story's lead sentence
instead, marked as a fallback, so every unique item still has a summary.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any, Protocol, TypeVar

from langchain_core import language_models
from langchain_core import runnables
import pydantic

from ai_api.enrich import models
from ai_api.enrich import prompts
from ai_api.guard import output
from ai_api.guard import sanitize

_log = logging.getLogger(__name__)
SUMMARY_MAX_CHARS = 280
MAX_CLAIMS = 5
MAX_COMPANIES = 10
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
# A sentence end: . ! or ? before a capital, a digit, a quote or the end
# ("Apple Inc. (AAPL) said" is one sentence).
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z0-9\"']|\s*$)")
_ABBREVIATIONS = frozenset(
    {"inc", "corp", "co", "ltd", "plc", "llc", "u.s", "mr", "ms", "dr", "st"}
)

T = TypeVar("T", bound=pydantic.BaseModel)


class StructuredOutputError(RuntimeError):
    """The model's answer didn't parse into the schema."""


class StructuredLlm(Protocol):
    """Calls a model and parses its answer into ``schema``."""

    async def __call__(
        self,
        schema: type[T],
        system: str,
        user: str,
        config: runnables.RunnableConfig,
    ) -> T:
        """Returns the parsed answer.

        Raises:
            StructuredOutputError: The answer didn't match the schema.
        """
        ...


class LangChainStructured:
    """``StructuredLlm`` over a LangChain chat model (JSON schema output)."""

    def __init__(self, model: language_models.BaseChatModel) -> None:
        """Uses ``model`` (normally the gateway's main alias)."""
        self._model = model

    async def __call__(
        self,
        schema: type[T],
        system: str,
        user: str,
        config: runnables.RunnableConfig,
    ) -> T:
        """Returns the parsed answer (see ``StructuredLlm``)."""
        runnable = self._model.with_structured_output(
            schema, method="json_schema", include_raw=True
        )
        result: dict[str, Any] = await runnable.ainvoke(
            [("system", system), ("human", user)], config=config
        )
        parsed = result.get("parsed")
        if result.get("parsing_error") is not None or parsed is None:
            raise StructuredOutputError(
                f"{schema.__name__}: {result.get('parsing_error')}"
            )
        return parsed


@dataclasses.dataclass(frozen=True)
class SummaryResult:
    """A summary and where it came from.

    Attributes:
        summary: At most 280 characters.
        sentiment: bullish, neutral or bearish.
        source: ``llm`` or ``fallback`` (the story's lead sentence).
    """

    summary: str
    sentiment: models.Sentiment
    source: str


def trim(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """One line of at most ``limit`` characters, cut at a word."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def lead_summary(item: sanitize.Sanitized) -> str:
    """The fallback summary: the story's first sentence."""
    body = " ".join(item.body.replace(sanitize.REMOVED, "").split())
    lead = body
    for match in _SENTENCE_END.finditer(body):
        words = body[: match.start()].split()
        last = words[-1].lower() if words else ""
        if last not in _ABBREVIATIONS:
            lead = body[: match.end()]
            break
    if not lead:
        lead = item.headline
    return trim(lead)


def clean_extraction(extraction: models.Extraction) -> models.Extraction:
    """Drops malformed tickers, duplicate companies and extra claims."""
    companies = []
    seen = set()
    for company in extraction.companies[:MAX_COMPANIES]:
        name = " ".join(company.name.split())[:120]
        ticker = None
        if company.ticker is not None:
            candidate = company.ticker.strip().strip("()$").upper()
            if _TICKER.match(candidate):
                ticker = candidate
        key = (name.lower(), ticker)
        if name and key not in seen:
            seen.add(key)
            companies.append(models.Company(name=name, ticker=ticker))
    claims = [
        " ".join(claim.split())[:300]
        for claim in extraction.claims
        if claim.strip()
    ][:MAX_CLAIMS]
    return models.Extraction(companies=companies, claims=claims)


class Enricher:
    """Extraction and summaries of sanitized items."""

    def __init__(self, llm: StructuredLlm) -> None:
        """Uses ``llm`` for every call."""
        self._llm = llm

    async def _call(
        self,
        schema: type[T],
        system: str,
        user: str,
        config: runnables.RunnableConfig,
    ) -> T:
        try:
            return await self._llm(schema, system, user, config)
        except StructuredOutputError as e:
            _log.info("retrying %s once: %s", schema.__name__, e)
            return await self._llm(schema, system, user, config)

    async def extract(
        self,
        item: sanitize.Sanitized,
        item_id: str,
        config: runnables.RunnableConfig,
    ) -> models.Extraction:
        """Companies, tickers and claims of one item.

        Raises:
            StructuredOutputError: Two answers in a row didn't parse.
        """
        user = prompts.item_message(item.headline, item.body, item_id)
        extraction = await self._call(
            models.Extraction, prompts.EXTRACT_SYSTEM, user, config
        )
        return clean_extraction(extraction)

    async def summarize(
        self,
        item: sanitize.Sanitized,
        item_id: str,
        config: runnables.RunnableConfig,
    ) -> SummaryResult:
        """A summary and sentiment; never investment advice.

        Returns:
            The model's summary, or the lead sentence (``fallback``,
            sentiment neutral) when two answers failed the checks.
        """
        user = prompts.item_message(item.headline, item.body, item_id)
        system = prompts.SUMMARY_SYSTEM
        for _attempt in range(2):
            try:
                answer = await self._call(models.Summary, system, user, config)
            except StructuredOutputError as e:
                _log.warning("summary of %s failed: %s", item_id, e)
                break
            summary = trim(answer.summary)
            advice = output.investment_advice(summary)
            if summary and not advice:
                return SummaryResult(summary, answer.sentiment, "llm")
            _log.warning("summary of %s gave advice: %s", item_id, advice)
            system = f"{prompts.SUMMARY_SYSTEM}\n\n{prompts.ADVICE_REMINDER}"
        return SummaryResult(lead_summary(item), "neutral", "fallback")
