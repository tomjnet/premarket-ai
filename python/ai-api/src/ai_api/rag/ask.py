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

Increment 5 adds, in this order:

- the semantic answer cache (``rag.cache``): a close enough question of the
  same feed date gets the stored answer at once (``cached`` in ``done``);
- long-term memory: "my watchlist" means the asker's saved tickers;
- the multi-agent team (``agents.supervisor``): before the answer, the
  supervisor asks specialists (Fact-Checker, Market Analyst, Brief Writer),
  whose tool results become more numbered sources. Their progress streams
  as ``step`` events before ``sources``.
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

from ai_api import memory as memory_lib
from ai_api.agents import prompts as agent_prompts
from ai_api.agents import supervisor as supervisor_lib
from ai_api.agents import tools as tools_lib
from ai_api.guard import llama_guard
from ai_api.guard import output
from ai_api.guard import sanitize
from ai_api.guard import spotlight
from ai_api.llm import tracing
from ai_api.rag import cache as cache_lib
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
# What the specialists' tool results are, for the writer.
_TOOL_LABELS = {
    "verification": "premarket-ai verdict and evidence",
    "company": "SEC ticker registry",
    "reputation": "premarket-ai source reputation list",
    "corpus_search": "SEC filings and releases search",
    "prices": "market data (daily closes)",
    "brief": "premarket-ai pre-market brief",
    "web": "web search results, unverified",
    "web_page": "web page, unverified",
}
_WATCHLIST_TICKERS = 3

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

TOOL_SOURCES = """\
Some sources are results of premarket-ai's own tools, gathered for this
question: verdicts and their evidence, market data, the pre-market brief,
the SEC ticker registry. A verdict is the system's assessment and can be
wrong: say "premarket-ai rates it FAKE because...". Web results only show
who else reports a story; they are not facts."""

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
        team: supervisor_lib.Supervisor | None = None,
        cache: cache_lib.AnswerCache | None = None,
        memory: memory_lib.Memory | None = None,
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
            team: The multi-agent team, or None (corpus only).
            cache: The semantic answer cache, or None.
            memory: Users' watchlists, or None.
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
        self._team = team
        self._cache = cache
        self._memory = memory

    async def _watchlist(self, user: str) -> list[str]:
        if self._memory is None:
            return []
        try:
            found = await self._memory.watchlist(user)
        except Exception as e:  # noqa: BLE001 - chat works without it.
            _log.warning("watchlist unavailable: %r", e)
            return []
        return list(found.tickers)

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
        self,
        question: str,
        day: datetime.date,
        tickers: Sequence[str] | None = None,
    ) -> tuple[list[Source], bool]:
        """The numbered sources for a question.

        Args:
            question: The sanitized question.
            day: The feed date of the vendor items.
            tickers: The companies it is about; None finds them in the
                question.

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
        if tickers is None:
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
            if s.kind in _TOOL_LABELS:
                title = f"{s.title} [{_TOOL_LABELS[s.kind]}]"
            elif s.trusted:
                label = _SOURCE_LABELS.get(s.kind, s.kind)
                title = f"{s.title} [trusted: {label}, {s.published_at}]"
            else:
                title = f"{s.title} [vendor item, unverified]"
            blocks.append(spotlight.source_block(s.n, title, s.text))
        if any(s.kind in _TOOL_LABELS for s in sources):
            system = f"{system}\n\n{TOOL_SOURCES}"
        user = "\n\n".join([*blocks, spotlight.question_block(question)])
        return [("system", system), ("human", user)]

    def _team_source(self, n: int, found: tools_lib.Finding) -> Source:
        return Source(
            n=n,
            kind=found.kind,
            trusted=found.trusted,
            title=found.title,
            url=found.url,
            published_at=None,
            ticker=found.ticker,
            snippet=_snippet(found.text),
            text=found.text,
            ref=0,
        )

    async def _tickers(
        self, question: str, user: str
    ) -> tuple[list[str], list[str]]:
        """The companies a question is about, and the asker's watchlist.

        A question that names no company but says "watchlist" is about the
        first tickers of the asker's watchlist (long-term memory).
        """
        watchlist = await self._watchlist(user)
        tickers = universe.tickers_in(question, self._members)
        if not tickers and "watchlist" in question.lower():
            tickers = watchlist[:_WATCHLIST_TICKERS]
        return tickers, watchlist

    async def stream(
        self,
        question: str,
        day: datetime.date,
        user: str,
        with_text: bool = False,
        agents: bool = True,
    ) -> AsyncIterator[Event]:
        """Answers ``question``: sources, then tokens, then the checked text.

        Args:
            question: The trader's question (sanitized here).
            day: The feed date whose vendor items may be cited.
            user: Who asks (trace metadata, the watchlist).
            with_text: Send each source's full text (the eval).
            agents: Ask the multi-agent team (off for the RAG eval, which
                measures the corpus chain of increment 3).

        Yields:
            ``step`` events (the team's progress), ``sources``, ``token``
            events, then ``done``.
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
        tickers, watchlist = await self._tickers(clean, user)
        cacheable = (
            self._cache is not None
            and not with_text
            and not cache_lib.personal(clean)
        )
        vector: list[float] | None = None
        if cacheable:
            found = await self._cache.lookup(clean, day, tickers)
            vector = found["vector"]
            if found["hit"] is not None:
                for event in self._replay(found["hit"], started):
                    yield event
                return
        sources, reranked = await self.retrieve(clean, day, tickers)
        used: list[str] = []
        if self._team is not None and agents:
            async for part in self._team.run(
                clean, day, user, tickers, watchlist
            ):
                if isinstance(part, supervisor_lib.Step):
                    yield Event("step", part.to_json())
                    continue
                sources.append(self._team_source(len(sources) + 1, part))
                if part.agent not in used:
                    used.append(part.agent)
        sources_event = {
            "sources": [s.to_json(with_text) for s in sources],
            "reranked": reranked,
        }
        yield Event("sources", sources_event)
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
        done = self._done(
            answer, cited, sources, refused, started, injection, blocked, used
        )
        if cacheable and vector is not None and cited and not refused:
            await self._cache.store(
                clean,
                day,
                tickers,
                vector,
                {**sources_event, "done": done.data},
            )
        yield done

    def _replay(self, hit: dict[str, Any], started: float) -> list[Event]:
        """A cached answer as the events of a fresh one."""
        done = dict(hit["done"])
        done["cached"] = True
        done["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return [
            Event(
                "sources",
                {"sources": hit["sources"], "reranked": hit["reranked"]},
            ),
            Event("token", {"text": done["answer"]}),
            Event("done", done),
        ]

    def _done(
        self,
        answer: str,
        cited: list[int],
        sources: Sequence[Source],
        refused: bool,
        started: float,
        injection: bool,
        blocked: bool = False,
        agents: Sequence[str] = (),
    ) -> Event:
        trusted = {s.n for s in sources if s.trusted}
        version = PROMPT_VERSION
        if agents:
            version = f"{PROMPT_VERSION}+{agent_prompts.CHAT_PROMPT_VERSION}"
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
                "prompt_version": version,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "agents": list(agents),
                "cached": False,
            },
        )

    async def ask(
        self, question: str, day: datetime.date, user: str = "eval"
    ) -> dict[str, Any]:
        """The whole answer at once (the eval and the smoke check).

        The multi-agent team is off: the RAG eval measures the corpus chain
        of increment 3, so its baseline stays comparable.
        """
        result: dict[str, Any] = {}
        async for event in self.stream(
            question, day, user, with_text=True, agents=False
        ):
            if event.name in ("sources", "done"):
                result.update(event.data)
        return result
