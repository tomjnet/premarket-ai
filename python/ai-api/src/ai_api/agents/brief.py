"""The briefing agent: the pre-market brief that replaces the legacy PDF.

One ``brief.write`` job per brief (``POST /briefs``, ``ai-api brief``; the
scheduler of increment 6 queues the 07:15 and 09:00 editions):

1. **Collect** (code, never a model): the day's verified items. What goes
   in is a hard rule:
   - VERIFIED items (final: not waiting for review), highest market impact
     first: the top stories, then every one of them by GICS sector;
   - "Unconfirmed - watch": high-impact UNVERIFIED items (they may be real
     breaking news), clearly labeled;
   - MISLEADING, FAKE, failed and pending-review items never go in; the
     brief only counts them ("6 items pending review").
   The refresh edition (09:00) marks the items that weren't in the
   morning edition (reviewed since 07:15) as new.
2. **Write** (the Brief Writer, with the ``premarket-brief-format`` skill):
   a short overview of the top VERIFIED items, citing their numbers. It is
   written by the cloud model (``BRIEF_MODEL``, OpenAI by default) while the
   monthly budget allows, else by the local model.
3. **Check**: citations must point to the brief's verified items; advice
   (buy, sell, hold, price targets) is refused. One rewrite, then the
   deterministic overview. Llama Guard runs on the overview; like on news,
   its verdict is recorded, and blocks only with GUARD_NEWS_REVIEW=true.
4. **Store** it in ``ai.brief``.

Progress streams to ``brief:{id}:events`` (``status``, ``sections``, then
``brief.done`` or ``brief.failed``); ``GET /briefs/today`` forwards it to
the page. The overview is sent once it passed the checks, never token by
token: the brief is the day's official document, and a model's unchecked
words must not be shown and then taken back. (A call's cost also only
comes back from the gateway for a whole answer.)
"""

from __future__ import annotations

from collections.abc import Sequence
import dataclasses
import datetime
import logging
import re
import time
from typing import Any, Protocol

from langchain_core import language_models

from ai_api.agents import prompts
from ai_api.agents import skills as skills_lib
from ai_api.guard import llama_guard
from ai_api.guard import output
from ai_api.guard import sanitize
from ai_api.guard import spotlight
from ai_api.llm import budget as budget_lib
from ai_api.llm import tracing
from ai_api.rag import universe
from ai_api.verify import events as events_lib

_log = logging.getLogger(__name__)
SKILL = "premarket-brief-format"
EDITIONS = ("morning", "refresh")
TOP_MAX = 8
WATCH_MAX = 5
# Items the model reads for the overview (the highest impact first).
OVERVIEW_ITEMS = 10
OTHER_SECTOR = "Other"
_COST_HEADER = "x-litellm-response-cost"
_CITATION = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_SUMMARY_CHARS = 280
_OVERVIEW_MAX_CHARS = 1200


# --- 1. collect ---------------------------------------------------------------


def _item(row: dict[str, Any], sector: str) -> dict[str, Any]:
    published = row["published_at"]
    return {
        "news_id": row["news_id"],
        "vendor_item_id": row["vendor_item_id"],
        "headline": row["headline"],
        "summary": row.get("summary"),
        "sentiment": row.get("sentiment"),
        "tickers": list(row["tickers"] or []),
        "sector": sector,
        "source_domain": row["source_domain"],
        "published_at": (
            published.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        ),
        "verdict": row["verdict"],
        "confidence": (
            None if row["confidence"] is None else float(row["confidence"])
        ),
        "review_status": row.get("review_status"),
        "impact": row.get("impact"),
        "impact_score": float(row.get("impact_score") or 0),
        "filing_url": row.get("filing_url"),
        "filing_title": row.get("filing_title"),
    }


def _order(row: dict[str, Any]) -> tuple[float, float, int]:
    return (
        -float(row.get("impact_score") or 0),
        -row["published_at"].timestamp(),
        row["news_id"],
    )


def compose(
    rows: Sequence[dict[str, Any]],
    members: Sequence[universe.Member],
    previous: set[int] | None = None,
    top_max: int = TOP_MAX,
    watch_max: int = WATCH_MAX,
) -> dict[str, Any]:
    """Which items go in, numbered, with sections and counts.

    Args:
        rows: The day's verified items (``BriefRepository.items``).
        members: The universe (sectors).
        previous: News ids of the morning edition (refresh only): the
            other items are marked ``new``.
        top_max: Top stories at most.
        watch_max: "Unconfirmed - watch" items at most.

    Returns:
        ``items`` (each with ``n``, ``section`` and ``new``), ``top``,
        ``sectors`` (``name`` and item numbers, most important first),
        ``watch`` and ``counts``.
    """
    sector_of = {m.ticker: m.sector for m in members if m.sector}
    final = [r for r in rows if r["status"] == "DONE"]
    verified = sorted(
        (r for r in final if r["verdict"] == "VERIFIED"), key=_order
    )
    watch = sorted(
        (
            r
            for r in final
            if r["verdict"] == "UNVERIFIED" and r.get("impact") == "high"
        ),
        key=_order,
    )[:watch_max]
    items: list[dict[str, Any]] = []
    sectors: dict[str, list[int]] = {}
    for i, row in enumerate([*verified, *watch]):
        sector = next(
            (sector_of[t] for t in row["tickers"] or [] if t in sector_of),
            OTHER_SECTOR,
        )
        entry = _item(row, sector)
        entry["n"] = i + 1
        if i < len(verified):
            entry["section"] = "top" if i < top_max else "sector"
            sectors.setdefault(sector, []).append(entry["n"])
        else:
            entry["section"] = "watch"
        entry["new"] = previous is not None and row["news_id"] not in previous
        items.append(entry)
    counts = {
        "verified": len(verified),
        "unconfirmed": len(watch),
        "unverified": sum(1 for r in final if r["verdict"] == "UNVERIFIED"),
        "pending_review": sum(
            1 for r in rows if r["status"] == "PENDING_REVIEW"
        ),
        "misleading": sum(1 for r in final if r["verdict"] == "MISLEADING"),
        "fake": sum(1 for r in final if r["verdict"] == "FAKE"),
        "failed": sum(1 for r in rows if r["status"] == "FAILED"),
        "new": sum(1 for i in items if i["new"]),
    }
    return {
        "items": items,
        "top": [i["n"] for i in items if i["section"] == "top"],
        "sectors": [
            {"name": name, "items": numbers}
            for name, numbers in sectors.items()
        ],
        "watch": [i["n"] for i in items if i["section"] == "watch"],
        "counts": counts,
    }


def _one_line(text: str, limit: int = _SUMMARY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fallback_overview(content: dict[str, Any], day: datetime.date) -> str:
    """The deterministic overview (no model, or the model's failed checks).

    Args:
        content: ``compose``'s result.
        day: The feed date.

    Returns:
        Plain text citing the top items by number.
    """
    counts = content["counts"]
    verified = [i for i in content["items"] if i["section"] != "watch"]
    if not verified:
        return (
            f"No story is verified for {day.isoformat()} yet. "
            f"{counts['pending_review']} items are pending review."
        )
    parts = [
        f"{counts['verified']} stories are verified for {day.isoformat()}; "
        f"{counts['unconfirmed']} unconfirmed stories are worth watching, "
        f"and {counts['pending_review']} items are pending review."
    ]
    for item in verified[:3]:
        text = (
            item["summary"] or sanitize.sanitize(item["headline"], "").headline
        )
        parts.append(f"{_one_line(text, 200)} [{item['n']}]")
    return " ".join(parts)


# --- 2./3. write and check ----------------------------------------------------


def check_overview(
    text: str, valid: set[int]
) -> tuple[str | None, list[int], str]:
    """The overview after the checks, or None when it fails them.

    Args:
        text: The model's overview.
        valid: The numbers of the verified items.

    Returns:
        (text or None, the cited numbers, why it failed or "").
    """
    text = " ".join(text.split())
    if output.investment_advice(text):
        return None, [], "advice"
    cited: list[int] = []
    unknown = False
    for match in _CITATION.finditer(text):
        for number in (int(n) for n in match.group(1).split(",")):
            if number not in valid:
                unknown = True
            elif number not in cited:
                cited.append(number)
    if unknown:
        return None, [], "unknown citation"
    if not cited:
        return None, [], "no citation"
    return text[:_OVERVIEW_MAX_CHARS], cited, ""


@dataclasses.dataclass(frozen=True)
class Overview:
    """The written overview.

    Attributes:
        text: The overview.
        source: ``llm`` or ``fallback``.
        citations: The item numbers it cites.
        model: The gateway alias that wrote it (None: fallback only).
        cloud: Written by the cloud model.
        cost_usd: What the cloud calls cost.
        notes: What happened (checks failed, cloud fell back, guard).
    """

    text: str
    source: str
    citations: tuple[int, ...]
    model: str | None
    cloud: bool = False
    cost_usd: float = 0.0
    notes: tuple[str, ...] = ()


def _cost(message: Any) -> float:
    headers = (getattr(message, "response_metadata", None) or {}).get(
        "headers"
    ) or {}
    try:
        return float(headers.get(_COST_HEADER, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


class Writer:
    """The Brief Writer: the overview with the brief-format skill."""

    def __init__(
        self,
        local: language_models.BaseChatModel,
        local_name: str,
        library: skills_lib.Library,
        tracer: tracing.Tracer,
        cloud: language_models.BaseChatModel | None = None,
        cloud_name: str = "",
        budget: budget_lib.CloudBudget | None = None,
        guard: llama_guard.Guard | None = None,
        guard_blocks: bool = False,
    ) -> None:
        """Wires the writer.

        Args:
            local: The local main model.
            local_name: Its alias.
            library: The skills (the brief format).
            tracer: Langfuse configs.
            cloud: The cloud model (BRIEF_MODEL), or None.
            cloud_name: Its alias.
            budget: The monthly cloud budget (None: never cloud).
            guard: Llama Guard on the overview, or None.
            guard_blocks: An unsafe overview is replaced by the
                deterministic one (GUARD_NEWS_REVIEW).
        """
        self._local = local
        self._local_name = local_name
        self._skills = library
        self._tracer = tracer
        self._cloud = cloud
        self._cloud_name = cloud_name
        self._budget = budget
        self._guard = guard
        self._guard_blocks = guard_blocks

    async def model_name(self) -> str:
        """The alias the next overview will be written with."""
        if await self._cloud_allowed():
            return self._cloud_name
        return self._local_name

    async def _cloud_allowed(self) -> bool:
        return (
            self._cloud is not None
            and self._budget is not None
            and await self._budget.allows()
        )

    def _messages(
        self, content: dict[str, Any], day: datetime.date
    ) -> list[tuple[str, str]]:
        skill = self._skills.body(SKILL) or ""
        system = prompts.BRIEF_SYSTEM.replace("{skill}", skill)
        blocks = []
        verified = [i for i in content["items"] if i["section"] != "watch"]
        for item in verified[:OVERVIEW_ITEMS]:
            clean = sanitize.sanitize(item["headline"], item["summary"] or "")
            text = (
                f"Tickers: {', '.join(item['tickers']) or 'none'}. "
                f"Sector: {item['sector']}. Market impact: {item['impact']}. "
                f"Sentiment: {item['sentiment'] or 'unknown'}.\n"
                f"Summary: {clean.body or 'none'}"
            )
            blocks.append(
                spotlight.source_block(item["n"], clean.headline, text)
            )
        counts = content["counts"]
        user = (
            f"Feed date: {day.isoformat()}. {counts['verified']} VERIFIED "
            f"stories, {counts['unconfirmed']} unconfirmed high-impact "
            f"stories, {counts['pending_review']} items pending review.\n\n"
            + "\n\n".join(blocks)
            + "\n\nWrite the Overview."
        )
        return [("system", system), ("human", user)]

    async def _ask(
        self,
        model: language_models.BaseChatModel,
        messages: list[tuple[str, str]],
        day: datetime.date,
    ) -> tuple[str, float]:
        config = self._tracer.config(
            "brief",
            tags=[prompts.BRIEF_PROMPT_VERSION],
            metadata={"feed_date": day.isoformat()},
        )
        answer = await model.ainvoke(messages, config=config)
        text = answer.content if isinstance(answer.content, str) else ""
        return text, _cost(answer)

    async def _attempts(
        self,
        model: language_models.BaseChatModel,
        messages: list[tuple[str, str]],
        valid: set[int],
        day: datetime.date,
        notes: list[str],
    ) -> tuple[str | None, list[int], float]:
        cost = 0.0
        for attempt in range(2):
            text, spent = await self._ask(model, messages, day)
            cost += spent
            checked, cited, why = check_overview(text, valid)
            if checked is not None:
                return checked, cited, cost
            notes.append(f"attempt {attempt + 1} failed the checks: {why}")
            messages = [
                *messages,
                ("ai", text),
                ("human", prompts.BRIEF_ADVICE_RETRY),
            ]
        return None, [], cost

    async def overview(
        self, content: dict[str, Any], day: datetime.date
    ) -> Overview:
        """Writes and checks the overview (see the module docstring).

        Args:
            content: ``compose``'s result.
            day: The feed date.

        Returns:
            The overview (the deterministic one when no model passed).
        """
        valid = {i["n"] for i in content["items"] if i["section"] != "watch"}
        fallback = fallback_overview(content, day)
        if not valid:
            return Overview(fallback, "fallback", (), None)
        messages = self._messages(content, day)
        notes: list[str] = []
        choices: list[tuple[language_models.BaseChatModel, str, bool]] = []
        if await self._cloud_allowed():
            choices.append((self._cloud, self._cloud_name, True))
        choices.append((self._local, self._local_name, False))
        cost = 0.0
        for model, name, cloud in choices:
            try:
                text, cited, spent = await self._attempts(
                    model, messages, valid, day, notes
                )
            except Exception as e:  # noqa: BLE001 - the next model, then code.
                _log.warning("brief: %s failed: %r", name, e)
                notes.append(f"{name} failed: {type(e).__name__}")
                continue
            cost += spent
            if cloud and self._budget is not None:
                await self._budget.add(spent)
            if text is None:
                continue
            if await self._unsafe(text):
                notes.append("Llama Guard: unsafe; deterministic overview")
                break
            return Overview(
                text, "llm", tuple(cited), name, cloud, cost, tuple(notes)
            )
        return Overview(
            fallback,
            "fallback",
            tuple(content["top"][:3]),
            None,
            False,
            cost,
            tuple(notes),
        )

    async def _unsafe(self, text: str) -> bool:
        if self._guard is None or not self._guard.enabled:
            return False
        found = await self._guard.check_answer("Report today's news.", text)
        if not found.safe:
            _log.warning("brief overview flagged: %s", found.describe())
        return not found.safe and self._guard_blocks


# --- 4. the job ---------------------------------------------------------------


class Repository(Protocol):
    """What the job reads and writes (``briefs.BriefRepository``)."""

    async def start(self, brief_id: int) -> dict[str, Any] | None:
        """QUEUED -> RUNNING; None when it isn't QUEUED."""
        ...

    async def items(self, day: datetime.date) -> list[dict[str, Any]]:
        """The day's verified unique items."""
        ...

    async def morning_ids(self, day: datetime.date) -> set[int] | None:
        """News ids of the day's latest DONE morning brief, or None."""
        ...

    async def finish(
        self,
        brief_id: int,
        content: dict[str, Any],
        written: Overview,
        total_ms: int,
    ) -> None:
        """Stores the brief (DONE)."""
        ...

    async def fail(self, brief_id: int, error: str) -> None:
        """Marks the brief FAILED."""
        ...


class Job:
    """Writes one brief (``brief.write``)."""

    def __init__(
        self,
        repo: Repository,
        writer: Writer,
        events: events_lib.RunEvents | None,
        members: Sequence[universe.Member],
    ) -> None:
        """Wires the job; ``events`` is a ``brief``-prefixed stream."""
        self._repo = repo
        self._writer = writer
        self._events = events
        self._members = list(members)

    async def _publish(self, brief_id: int, kind: str, data: dict) -> None:
        if self._events is not None:
            await self._events.publish(brief_id, kind, data)

    async def run(self, brief_id: int) -> str:
        """Writes the brief.

        Returns:
            ``done``, ``failed`` or ``skipped`` (it wasn't QUEUED: a
            redelivered job).
        """
        started = time.monotonic()
        brief = await self._repo.start(brief_id)
        if brief is None:
            return "skipped"
        day = brief["feed_date"]
        try:
            await self._publish(
                brief_id,
                "status",
                {"detail": "Collecting the verified items"},
            )
            previous = None
            if brief["edition"] == "refresh":
                previous = await self._repo.morning_ids(day)
            rows = await self._repo.items(day)
            content = compose(rows, self._members, previous)
            await self._publish(brief_id, "sections", content)
            name = await self._writer.model_name()
            await self._publish(
                brief_id,
                "status",
                {"detail": f"Writing the overview ({name})"},
            )
            written = await self._writer.overview(content, day)
            total_ms = int((time.monotonic() - started) * 1000)
            await self._repo.finish(brief_id, content, written, total_ms)
        except Exception as e:  # noqa: BLE001 - recorded, the job ends.
            _log.exception("brief %s failed", brief_id)
            await self._repo.fail(brief_id, repr(e)[:2000])
            await self._publish(
                brief_id, "brief.failed", {"error": "The brief failed."}
            )
            return "failed"
        await self._publish(
            brief_id,
            "brief.done",
            {"brief_id": brief_id, "overview_source": written.source},
        )
        _log.info(
            "brief %s (%s %s): %d verified, %d unconfirmed, overview %s",
            brief_id,
            day,
            brief["edition"],
            content["counts"]["verified"],
            content["counts"]["unconfirmed"],
            written.source,
        )
        return "done"
