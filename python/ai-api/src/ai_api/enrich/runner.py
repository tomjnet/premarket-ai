"""``ai-api enrich --date D``: the first AI steps on one feed date.

Runs after the rules (``ai-api rules``), on the items they found unique,
in the vendor's order:

1. Sanitize every item (guard layer 1) and flag injection attempts.
2. Embed them (one batch) and run dedup L3: paraphrases of an earlier
   item are linked and skipped; very similar stories with other facts are
   noted as evidence (a conflicting version, no badge).
3. English only: other languages skip the model and are flagged.
4. Phase-batched model calls (one model stays on the GPU): all
   extractions, then all summaries, two in flight at a time.
5. Replace the date's AI results in one transaction.

The 7 days before D must be in the L3 index; a day whose index expired is
re-indexed from the stored embeddings (``ai.news_embedding``), embedding
only the items that have none.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import dataclasses
import datetime
import logging
import time
from typing import TypeVar

from langchain_core import embeddings as lc_embeddings
import psycopg
from redis import asyncio as aioredis

from ai_api import config
from ai_api.dedup import normalize
from ai_api.dedup import paraphrase
from ai_api.dedup import service
from ai_api.enrich import chains
from ai_api.enrich import prompts
from ai_api.enrich import repository
from ai_api.guard import language
from ai_api.guard import sanitize
from ai_api.llm import factory
from ai_api.llm import tracing
from ai_api.rules import checks
from ai_api.rules import engine
from ai_api.rules import repository as rules_repository

_log = logging.getLogger(__name__)
_QUOTE_CHARS = 120

T = TypeVar("T")


class NotReadyError(RuntimeError):
    """The feed date has no finished rule run yet."""


def _vector_day_key(dims: int, day: datetime.date) -> str:
    return f"dedup:vecday:{dims}:{day.isoformat()}"


def _quote(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > _QUOTE_CHARS:
        text = text[: _QUOTE_CHARS - 1].rstrip() + "…"
    return f'"{text}"'


def _l3_evidence(match: service.DedupMatch) -> checks.Evidence:
    text = (
        f"Paraphrase (L3, cosine {match.score:.2f}, {match.word_edits} words "
        f"differ, same tickers and key facts) of "
        f"{match.canonical_vendor_item_id} from "
        f"{match.canonical_feed_date.isoformat()}"
    )
    if match.stale:
        return checks.Evidence(
            "dedup", checks.STALE, f"{text}: re-served old news."
        )
    return checks.Evidence("dedup", None, f"{text}.")


@dataclasses.dataclass
class Pipeline:
    """The AI steps on items already embedded (the runner and the eval).

    Attributes:
        l3: The paraphrase check (its index holds the earlier items).
        enricher: Extraction and summaries.
        tracer: Run configs (Langfuse when enabled).
        concurrency: Model calls in flight at once.
        run_label: A tag for the traces (the run id).
    """

    l3: paraphrase.ParaphraseCheck
    enricher: chains.Enricher
    tracer: tracing.Tracer
    concurrency: int = 2
    run_label: str = "adhoc"

    async def _phase(
        self,
        items: Sequence[tuple[engine.RawItem, sanitize.Sanitized]],
        call: Callable[[engine.RawItem, sanitize.Sanitized], Awaitable[T]],
    ) -> list[T | BaseException]:
        gate = asyncio.Semaphore(self.concurrency)

        async def one(item: engine.RawItem, clean: sanitize.Sanitized) -> T:
            async with gate:
                return await call(item, clean)

        return await asyncio.gather(
            *(one(item, clean) for item, clean in items),
            return_exceptions=True,
        )

    def _config(self, step: str, item: engine.RawItem) -> dict:
        return self.tracer.config(
            f"enrich.{step}",
            tags=[prompts.PROMPT_VERSION, f"run:{self.run_label}"],
            metadata={
                "news_id": item.news_id,
                "vendor_item_id": item.vendor_item_id,
                "feed_date": item.feed_date.isoformat(),
            },
        )

    async def run(
        self,
        items: Sequence[engine.RawItem],
        vectors: dict[int, list[float]],
        skip_models: bool = False,
    ) -> list[repository.Outcome]:
        """Runs steps 1 to 4 of the module docstring.

        Args:
            items: The unique items, in feed order.
            vectors: Each item's L3 embedding.
            skip_models: Stop after L3 and the language check (the eval of
                the deterministic layers).

        Returns:
            One outcome per item, in the same order.
        """
        outcomes = []
        todo: list[tuple[engine.RawItem, sanitize.Sanitized]] = []
        by_id: dict[int, repository.Outcome] = {}
        for item in items:
            outcome = repository.Outcome(item.news_id)
            outcomes.append(outcome)
            by_id[item.news_id] = outcome
            clean = sanitize.sanitize(item.headline, item.body)
            if clean.injections:
                outcome.reason_codes.append(sanitize.INJECTION_ATTEMPT)
                outcome.evidence.append(
                    checks.Evidence(
                        "guard",
                        sanitize.INJECTION_ATTEMPT,
                        f"Instruction-like text removed before any model saw "
                        f"the item: {_quote(clean.injections[0])}",
                    )
                )
            entry = paraphrase.VectorEntry.of(
                item.dedup_item(), vectors[item.news_id]
            )
            match, conflict = await self.l3.check(entry)
            if match is not None:
                outcome.status = "DUPLICATE"
                outcome.duplicate = match
                evidence = _l3_evidence(match)
                outcome.evidence.insert(0, evidence)
                if evidence.code is not None:
                    outcome.reason_codes.append(evidence.code)
                continue
            if conflict is not None:
                outcome.conflict = True
                outcome.evidence.append(
                    checks.Evidence(
                        "dedup",
                        None,
                        f"Very similar to {conflict.canonical_vendor_item_id}"
                        f" from {conflict.canonical_feed_date.isoformat()} "
                        f"(cosine {conflict.cosine:.2f}), but "
                        f"{conflict.detail}: two versions of one story.",
                    )
                )
            if not language.is_english(clean.text):
                outcome.status = "SKIPPED"
                outcome.reason_codes.append(language.UNSUPPORTED_LANGUAGE)
                outcome.evidence.append(
                    checks.Evidence(
                        "language",
                        language.UNSUPPORTED_LANGUAGE,
                        "Not English: the model steps were skipped.",
                    )
                )
                continue
            todo.append((item, clean))
        if skip_models:
            return outcomes

        extractions = await self._phase(
            todo,
            lambda item, clean: self.enricher.extract(
                clean, item.vendor_item_id, self._config("extract", item)
            ),
        )
        for (item, _), result in zip(todo, extractions, strict=True):
            outcome = by_id[item.news_id]
            if isinstance(result, BaseException):
                outcome.status = "FAILED"
                outcome.error = f"extract: {result!r}"[:500]
                _log.warning(
                    "extract %s failed: %r", item.vendor_item_id, result
                )
            else:
                outcome.extraction = result
        summaries = await self._phase(
            todo,
            lambda item, clean: self.enricher.summarize(
                clean, item.vendor_item_id, self._config("summary", item)
            ),
        )
        for (item, _), result in zip(todo, summaries, strict=True):
            outcome = by_id[item.news_id]
            if isinstance(result, BaseException):
                outcome.status = "FAILED"
                outcome.error = f"summary: {result!r}"[:500]
                _log.warning(
                    "summary %s failed: %r", item.vendor_item_id, result
                )
            else:
                outcome.summary = result
        return outcomes


async def embed_items(
    embedder: lc_embeddings.Embeddings,
    items: Sequence[engine.RawItem],
    stored: dict[int, list[float]],
    prefix: str,
) -> dict[int, list[float]]:
    """L3 embeddings of ``items``: the stored ones, plus new ones.

    Args:
        embedder: The embedding model.
        items: The items.
        stored: Embeddings already in Postgres.
        prefix: The embedding model's task prefix for similarity.

    Returns:
        news id -> embedding for every item.
    """
    missing = [i for i in items if i.news_id not in stored]
    vectors = dict(stored)
    if missing:
        texts = [
            prefix + paraphrase.embed_text(i.headline, i.body) for i in missing
        ]
        new = await embedder.aembed_documents(texts)
        for item, vector in zip(missing, new, strict=True):
            vectors[item.news_id] = vector
    return vectors


def _text_digest(item: engine.RawItem) -> str:
    return normalize.sha256(paraphrase.embed_text(item.headline, item.body))


class _Embeddings:
    """Embeddings with their Postgres cache."""

    def __init__(
        self,
        repo: repository.EnrichRepository,
        embedder: lc_embeddings.Embeddings,
        model: str,
        prefix: str,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._model = model
        self._prefix = prefix

    async def of(
        self, items: Sequence[engine.RawItem]
    ) -> dict[int, list[float]]:
        digests = {i.news_id: _text_digest(i) for i in items}
        stored = await self._repo.embeddings(digests, self._model)
        vectors = await embed_items(self._embedder, items, stored, self._prefix)
        new = [
            (news_id, self._model, digests[news_id], vector)
            for news_id, vector in vectors.items()
            if news_id not in stored
        ]
        if new:
            await self._repo.save_embeddings(new)
        return vectors


async def _prepare_window(
    rules: rules_repository.RulesRepository,
    embeddings: _Embeddings,
    l3: paraphrase.ParaphraseCheck,
    redis: aioredis.Redis,
    dims: int,
    ttl_s: int,
    day: datetime.date,
    window_days: int,
) -> None:
    first = day - datetime.timedelta(days=window_days)
    last = day - datetime.timedelta(days=1)
    for earlier in sorted(await rules.checked_days(first, last)):
        key = _vector_day_key(dims, earlier)
        if await redis.exists(key):
            continue
        unique = await rules.unique_items(earlier)
        vectors = await embeddings.of(unique)
        await l3.index_unique(
            [
                paraphrase.VectorEntry.of(i.dedup_item(), vectors[i.news_id])
                for i in unique
            ]
        )
        await redis.set(key, "1", ex=ttl_s)
        _log.info("L3 index: indexed %s (%d unique)", earlier, len(unique))


async def run(
    settings: config.AiSettings, day: datetime.date
) -> repository.RunCounts:
    """The AI run of ``day`` (see the module docstring).

    Args:
        settings: The settings.
        day: The feed date.

    Returns:
        The run's counts.

    Raises:
        NotReadyError: The day's rule run isn't DONE.
    """
    llm = settings.llm
    tracer = tracing.Tracer(settings.tracing)
    # Binary-safe client for the vectors; the text client for the markers.
    vector_redis = aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        socket_timeout=30,
        socket_connect_timeout=5,
    )
    redis = aioredis.Redis(
        host=settings.redis_host,
        password=settings.redis_password,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=5,
    )
    ttl_s = settings.dedup.ttl_s
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.owner.dsn(), autocommit=True
        ) as conn:
            repo = repository.EnrichRepository(conn)
            rules = rules_repository.RulesRepository(conn)
            status = await repo.rule_status(day)
            if status != "DONE":
                raise NotReadyError(
                    f"the rule run of {day} is {status or 'missing'}; "
                    "run `make -C python rules DATE=...` first"
                )
            index = paraphrase.RedisVectorIndex(
                vector_redis, llm.embed_dims, ttl_s
            )
            await index.create()
            l3 = paraphrase.ParaphraseCheck(index, settings.dedup)
            embeddings = _Embeddings(
                repo,
                factory.embeddings(llm),
                llm.embed_model,
                llm.cluster_prefix,
            )
            await _prepare_window(
                rules,
                embeddings,
                l3,
                redis,
                llm.embed_dims,
                ttl_s,
                day,
                settings.dedup.window_days,
            )
            run_id = await repo.start_run(
                day, llm.main_model, llm.embed_model, prompts.PROMPT_VERSION
            )
            started = time.monotonic()
            try:
                await repo.delete_l3_links(day)
                items = await rules.unique_items(day)
                vectors = await embeddings.of(items)
                pipeline = Pipeline(
                    l3=l3,
                    enricher=chains.Enricher(
                        chains.LangChainStructured(factory.chat_model(llm))
                    ),
                    tracer=tracer,
                    concurrency=llm.concurrency,
                    run_label=str(run_id),
                )
                llm_started = time.monotonic()
                outcomes = await pipeline.run(items, vectors)
                llm_ms = int((time.monotonic() - llm_started) * 1000)
                await repo.save_outcomes(
                    run_id, outcomes, llm.main_model, prompts.PROMPT_VERSION
                )
                await redis.set(
                    _vector_day_key(llm.embed_dims, day), "1", ex=ttl_s
                )
                counts = repository.RunCounts.of(outcomes)
                total_ms = int((time.monotonic() - started) * 1000)
                await repo.finish_run(run_id, counts, llm_ms, total_ms)
            except Exception as e:
                await repo.fail_run(run_id, repr(e))
                raise
    finally:
        tracer.flush()
        await redis.aclose()
        await vector_redis.aclose()
    _log.info("enrich %s: %s (%d ms)", day, counts.line(), total_ms)
    return counts
