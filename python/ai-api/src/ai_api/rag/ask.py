"""The "Ask the News" chain: simple RAG with citations.

::

    question -> sanitize -> vector search (20) -> rerank (5)
             + today's vendor items for the tickers it names (unverified)
             -> numbered, spotlighted sources -> main model (streamed)
             -> citations checked against the sources -> no-advice check

The answer streams token by token; the final event carries the checked
text: citation numbers that point to no source are removed, and an answer
that gives investment advice is replaced by a refusal.

Increment 4 adds Llama Guard (guard layer 2) on both ends: an unsafe
question is refused before retrieval, and an unsafe answer is replaced by
the refusal (``guard_blocked`` in the final event).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
import dataclasses
import datetime
import logging
import re
import time
from typing import Any

from langchain_core import language_models

from ai_api.guard import llama_guard
from ai_api.guard import output
from ai_api.guard import sanitize
from ai_api.guard import spotlight
from ai_api.llm import tracing
from ai_api.rag import config
from ai_api.rag import rerank
from ai_api.rag import store as store_lib
from ai_api.rag import universe

_log = logging.getLogger(__name__)
PROMPT_VERSION = "ask-v1"
MAX_QUESTION_CHARS = 500
_VENDOR_PER_TICKER = 2
_VENDOR_MAX = 4
_SNIPPET_CHARS = 280
_CITATION = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_SOURCE_LABELS = {
    "edgar_8k": "SEC filing (8-K)",
    "edgar_ex99": "Company press release filed with the SEC (EX-99.1)",
    "xbrl_facts": "SEC XBRL company facts",
    "fed_press": "Federal Reserve press release",
    "sec_press": "SEC press release",
}

ANSWER_SYSTEM = f"""\
You answer traders' questions about companies and markets, using only the
numbered sources you are given.
{spotlight.DATA_RULES}

Rules:
- Use only facts from the sources. If they don't answer the question, say
  so plainly.
- Cite every fact with its source number in brackets, like [1] or [2][3].
- Trusted sources (SEC filings, company facts, Federal Reserve and SEC
  releases) are primary. Vendor items are unverified claims from a news
  vendor that may be fake: write "the vendor reports" and never present
  them as fact.
- Answer in English, in at most 150 words.
- Never give investment advice: no buy, sell or hold recommendations and no
  price targets. You may describe sentiment and what the sources say."""

GUARD_REFUSAL = (
    "I can't help with that request. Ask about companies, filings or the "
    "day's news instead."
)

ADVICE_QUESTION = (
    "The question asks for investment advice. Start your answer with: "
    '"I can\'t give investment advice." Then say what the sources report.'
)


@dataclasses.dataclass(frozen=True)
class Source:
    """A numbered source of an answer.

    Attributes:
        n: Its citation number.
        kind: edgar_8k, edgar_ex99, xbrl_facts, fed_press, sec_press or
            vendor.
        trusted: False for vendor items.
        title: Its title.
        url: Its link (a vendor item links to its news detail page).
        published_at: ISO date, when known.
        ticker: The company, when it has one.
        snippet: The start of the text.
        text: The text the model reads.
        ref: The ``ai.chunk`` id, or the vendor item's news id.
    """

    n: int
    kind: str
    trusted: bool
    title: str
    url: str
    published_at: str | None
    ticker: str | None
    snippet: str
    text: str
    ref: int

    def to_json(self, with_text: bool = False) -> dict[str, Any]:
        """The source as sent to the browser (the eval adds the text)."""
        data = {
            "n": self.n,
            "kind": self.kind,
            "trusted": self.trusted,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "ticker": self.ticker,
            "snippet": self.snippet,
        }
        if with_text:
            data["text"] = self.text
        return data


@dataclasses.dataclass(frozen=True)
class Event:
    """One server-sent event: ``sources``, ``token`` or ``done``."""

    name: str
    data: dict[str, Any]


VendorLookup = Callable[
    [datetime.date, Sequence[str]], Awaitable[list[dict[str, Any]]]
]


def check_citations(
    text: str, sources: Sequence[Source]
) -> tuple[str, list[int]]:
    """Removes citations to missing sources.

    Args:
        text: The model's answer.
        sources: The sources it was given.

    Returns:
        The cleaned text and the cited source numbers, in first-use order.
    """
    valid = {s.n for s in sources}
    cited: list[int] = []

    def keep(match: re.Match[str]) -> str:
        numbers = [int(n) for n in match.group(1).split(",")]
        good = [n for n in numbers if n in valid]
        for n in good:
            if n not in cited:
                cited.append(n)
        return "".join(f"[{n}]" for n in good)

    cleaned = _CITATION.sub(keep, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), cited


def _snippet(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= _SNIPPET_CHARS:
        return text
    return text[: _SNIPPET_CHARS - 1].rstrip() + "…"


class AskService:
    """Answers questions from the trusted corpus and the day's news."""

    def __init__(
        self,
        store: store_lib.CorpusStore,
        reranker: rerank.Reranker,
        model: language_models.BaseChatModel,
        tracer: tracing.Tracer,
        cfg: config.RagConfig,
        members: list[universe.Member],
        vendor_lookup: VendorLookup | None = None,
        model_name: str = "",
        guard: llama_guard.Guard | None = None,
    ) -> None:
        """Wires the chain.

        Args:
            store: The trusted corpus.
            reranker: The cross-encoder.
            model: The main chat model (streaming).
            tracer: Langfuse configs.
            cfg: top_k and top_n.
            members: The universe (tickers named in a question).
            vendor_lookup: The day's items for some tickers, or None.
            model_name: The gateway alias, for the answer metadata.
            guard: Llama Guard on the question and the answer, or None.
        """
        self._store = store
        self._reranker = reranker
        self._model = model
        self._tracer = tracer
        self._cfg = cfg
        self._members = members
        self._vendor_lookup = vendor_lookup
        self._model_name = model_name
        self._guard = guard

    async def _unsafe_question(self, question: str) -> bool:
        if self._guard is None or not self._guard.enabled:
            return False
        found = await self._guard.check_question(question)
        if found.blocks_question():
            _log.warning("Llama Guard refused a question: %s", found.describe())
        return found.blocks_question()

    async def _unsafe_answer(self, question: str, answer: str) -> bool:
        if self._guard is None or not self._guard.enabled:
            return False
        found = await self._guard.check_answer(question, answer)
        if not found.safe:
            _log.warning("Llama Guard blocked an answer: %s", found.describe())
        return not found.safe

    async def retrieve(
        self, question: str, day: datetime.date
    ) -> tuple[list[Source], bool]:
        """The numbered sources for a question.

        Returns:
            The sources (trusted first) and whether they were reranked.
        """
        hits = await self._store.search(question, self._cfg.top_k)
        ranked = await self._reranker.rank(question, [h.text for h in hits])
        reranked = ranked is not None
        if ranked is None:
            order = list(range(len(hits)))
        else:
            order = [index for index, _ in ranked if index < len(hits)]
        sources = []
        for index in order[: self._cfg.top_n]:
            hit = hits[index]
            meta = hit.metadata
            kind = str(meta.get("source", "edgar_8k"))
            sources.append(
                Source(
                    n=len(sources) + 1,
                    kind=kind,
                    trusted=True,
                    title=str(meta.get("title", "")),
                    url=str(meta.get("url", "")),
                    published_at=meta.get("published_at"),
                    ticker=meta.get("ticker"),
                    snippet=_snippet(hit.text),
                    text=hit.text,
                    ref=hit.chunk_id,
                )
            )
        tickers = universe.tickers_in(question, self._members)
        if self._vendor_lookup is not None and tickers:
            items = await self._vendor_lookup(day, tickers)
            for item in items[:_VENDOR_MAX]:
                clean = sanitize.sanitize(item["headline"], item["body"])
                sources.append(
                    Source(
                        n=len(sources) + 1,
                        kind="vendor",
                        trusted=False,
                        title=f"Vendor item {item['vendor_item_id']}: "
                        f"{clean.headline}",
                        url=f"/news/{item['id']}",
                        published_at=item["feed_date"].isoformat(),
                        ticker=(item["tickers"] or [None])[0],
                        snippet=_snippet(clean.body),
                        text=clean.body,
                        ref=item["id"],
                    )
                )
        return sources, reranked

    def _messages(
        self, question: str, sources: Sequence[Source]
    ) -> list[tuple[str, str]]:
        system = ANSWER_SYSTEM
        if output.asks_for_advice(question):
            system = f"{system}\n\n{ADVICE_QUESTION}"
        blocks = []
        for s in sources:
            if s.trusted:
                label = _SOURCE_LABELS.get(s.kind, s.kind)
                title = f"{s.title} [trusted: {label}, {s.published_at}]"
            else:
                title = f"{s.title} [vendor item, unverified]"
            blocks.append(spotlight.source_block(s.n, title, s.text))
        user = "\n\n".join([*blocks, spotlight.question_block(question)])
        return [("system", system), ("human", user)]

    async def stream(
        self,
        question: str,
        day: datetime.date,
        user: str,
        with_text: bool = False,
    ) -> AsyncIterator[Event]:
        """Answers ``question``: sources, then tokens, then the checked text.

        Args:
            question: The trader's question (sanitized here).
            day: The feed date whose vendor items may be cited.
            user: Who asks (trace metadata).
            with_text: Send each source's full text (the eval).

        Yields:
            ``sources``, then ``token`` events, then ``done``.
        """
        started = time.monotonic()
        clean = sanitize.clean_text(question)[:MAX_QUESTION_CHARS]
        injection = bool(sanitize.injection_sentences(clean))
        if await self._unsafe_question(clean):
            yield Event("sources", {"sources": [], "reranked": False})
            yield Event("token", {"text": GUARD_REFUSAL})
            yield self._done(
                GUARD_REFUSAL, [], [], True, started, injection, blocked=True
            )
            return
        sources, reranked = await self.retrieve(clean, day)
        yield Event(
            "sources",
            {
                "sources": [s.to_json(with_text) for s in sources],
                "reranked": reranked,
            },
        )
        if not sources:
            text = "I found no sources that answer this question."
            yield Event("token", {"text": text})
            yield self._done(text, [], sources, False, started, injection)
            return
        config = self._tracer.config(
            "ask",
            tags=[PROMPT_VERSION],
            metadata={"user": user, "feed_date": day.isoformat()},
        )
        parts = []
        async for chunk in self._model.astream(
            self._messages(clean, sources), config=config
        ):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                parts.append(text)
                yield Event("token", {"text": text})
        answer, cited = check_citations("".join(parts), sources)
        refused = False
        blocked = False
        advice = output.investment_advice(answer)
        if advice:
            _log.warning("answer gave investment advice: %s", advice)
            answer, cited, refused = output.REFUSAL, [], True
        elif await self._unsafe_answer(clean, answer):
            answer, cited, refused, blocked = GUARD_REFUSAL, [], True, True
        yield self._done(
            answer, cited, sources, refused, started, injection, blocked
        )

    def _done(
        self,
        answer: str,
        cited: list[int],
        sources: Sequence[Source],
        refused: bool,
        started: float,
        injection: bool,
        blocked: bool = False,
    ) -> Event:
        trusted = {s.n for s in sources if s.trusted}
        return Event(
            "done",
            {
                "answer": answer,
                "citations": cited,
                "cites_trusted": any(n in trusted for n in cited),
                "refused": refused,
                "injection_flagged": injection,
                "guard_blocked": blocked,
                "model": self._model_name,
                "prompt_version": PROMPT_VERSION,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )

    async def ask(
        self, question: str, day: datetime.date, user: str = "eval"
    ) -> dict[str, Any]:
        """The whole answer at once (the eval and the smoke check)."""
        result: dict[str, Any] = {}
        async for event in self.stream(question, day, user, True):
            if event.name in ("sources", "done"):
                result.update(event.data)
        return result
