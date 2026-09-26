"""The LangGraph ``verify_news`` graph: one run per unique item.

::

    load -> sanitize -> extract -> ┬ entity_check  ┐
                                   ├ source_check  │
                                   ├ corroboration │
                                   ├ claim_check   ├-> aggregate -> enrich
                                   ├ style_signals │        |
                                   └ ml_check      ┘        v
                         finalize <- review (interrupt) <- persist
                            ^                                |
                            +------ (no review needed) ------+

- ``sanitize`` / ``extract`` reuse increment 3: the item is sanitized
  again (guard layer 1) and the stored extraction is read, not recomputed.
- The six checks run in parallel; code calls the tools (the item's
  ``Tools`` come in the run's context, one MCP session per item).
- ``aggregate``: hard rules, the FABRICATED rule, the LLM judge (local,
  cloud when uncertain), the combined verdict, and the review reasons.
- ``enrich`` comes before the review (not after, as first planned): the
  review queue is ordered by market impact, so the impact must be known
  when the item enters the queue.
- ``persist`` stores the verdict (PENDING_REVIEW or DONE) and counts it.
- ``review`` calls ``interrupt()``: the graph stops, its state stays in
  the Postgres checkpointer, and ``POST /review/{id}`` resumes it with the
  analyst's decision (``finalize`` stores it).

Every node returns JSON-safe values, because the state is checkpointed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import dataclasses
import datetime
import logging
from typing import Any, Protocol, TypedDict

from langgraph import graph as lg
from langgraph import runtime as lg_runtime
from langgraph import types as lg_types

from ai_api.guard import language
from ai_api.guard import llama_guard
from ai_api.guard import sanitize
from ai_api.llm import tracing
from ai_api.ml import models as ml_models
from ai_api.verify import checks
from ai_api.verify import events as events_lib
from ai_api.verify import evidence as ev
from ai_api.verify import judge as judge_lib
from ai_api.verify import policy
from ai_api.verify import prompts
from ai_api.verify import repository
from ai_api.verify import tools as tools_lib

_log = logging.getLogger(__name__)
CHECK_NODES = (
    "entity_check",
    "source_check",
    "corroboration",
    "claim_check",
    "style_signals",
    "ml_check",
)
REVIEW_STATUS = {
    "approve": "APPROVED",
    "override": "OVERRIDDEN",
    "expire": "EXPIRED",
}
_INJECTION_FOR_JUDGE = (
    "Instruction-like text was removed from the item before any model saw "
    "it (INJECTION_ATTEMPT)."
)


class State(TypedDict, total=False):
    """The checkpointed state of one item's graph."""

    run_id: int
    news_id: int
    thread_id: str
    guard: dict[str, Any]
    item: dict[str, Any]
    clean: dict[str, Any]
    english: bool
    names: dict[str, str]
    entity: dict[str, Any]
    source: dict[str, Any]
    corroboration: dict[str, Any]
    claims: dict[str, Any]
    style: dict[str, Any]
    ml: dict[str, Any] | None
    decision: dict[str, Any]
    evidence: list[dict[str, Any]]
    reasons: list[str]
    impact: dict[str, Any]
    progress: dict[str, Any]
    review: dict[str, Any] | None


@dataclasses.dataclass
class Context:
    """Per-run objects that are not checkpointed.

    Attributes:
        tools: The read-only tools for this item (an MCP session).
    """

    tools: tools_lib.Tools | None = None


class Repository(Protocol):
    """What the graph reads and writes (``repository.VerifyRepository``)."""

    async def load_item(self, news_id: int) -> dict[str, Any] | None:
        """The item with its rule and AI results."""
        ...

    async def save(self, verdict: repository.Verdict) -> repository.Progress:
        """Stores a verdict; counts the item once."""
        ...

    async def finish_run(self, run_id: int) -> dict[str, Any] | None:
        """Marks the run DONE when every item is counted."""
        ...

    async def finish_review(
        self, news_id: int, status: str, verdict: str, entry: ev.Evidence
    ) -> bool:
        """Stores the analyst's decision; False when already stored."""
        ...


class Predictor(Protocol):
    """The classic ML baseline (``ml.models.Baseline``)."""

    async def predict(
        self, headline: str, body: str
    ) -> tuple[ml_models.Prediction, ml_models.Prediction | None]:
        """FinBERT's sentiment and the classifier's verdict."""
        ...


@dataclasses.dataclass
class Deps:
    """What the nodes use (built once per worker process).

    Attributes:
        repo: Reads and writes.
        judge: The LLM judge; None runs the rules alone (the hosted eval).
        tracer: Langfuse configs.
        events: Run events; None publishes nothing.
        ml: The classic ML baseline; None when it isn't available.
        universe_size: Companies in the lab universe (impact).
        min_confidence: HITL_CONFIDENCE_MIN.
        guard_routes: An unsafe Llama Guard verdict sends the item to
            review and skips the judge (GUARD_NEWS_REVIEW); else it is
            evidence only.
    """

    repo: Repository
    judge: judge_lib.Judge | None = None
    tracer: tracing.Tracer = dataclasses.field(
        default_factory=lambda: tracing.Tracer(tracing.TracingConfig())
    )
    events: events_lib.RunEvents | None = None
    ml: Predictor | None = None
    universe_size: int = 50
    min_confidence: float = 0.70
    guard_routes: bool = False


def thread_id(run_id: int, news_id: int) -> str:
    """The checkpoint thread of one item in one run."""
    return f"verify-{run_id}-{news_id}"


def _item_json(row: dict[str, Any]) -> dict[str, Any]:
    """The DB row as JSON-safe state."""
    return {
        "news_id": row["news_id"],
        "feed_date": row["feed_date"].isoformat(),
        "vendor_item_id": row["vendor_item_id"],
        "headline": row["headline"],
        "body": row["body"],
        "source_url": row["source_url"],
        "source_domain": row["source_domain"],
        "tickers": list(row["tickers"]),
        "rule_codes": list(row["rule_codes"]),
        "rule_evidence": list(row["rule_evidence"]),
        "ai_status": row["ai_status"],
        "ai_codes": list(row["ai_codes"]),
        "ai_evidence": list(row["ai_evidence"]),
        "companies": list(row["companies"]),
        "claims": list(row["claims"]),
    }


def _check_item(state: State) -> checks.Item:
    item = state["item"]
    clean = state["clean"]
    return checks.Item(
        news_id=item["news_id"],
        feed_date=datetime.date.fromisoformat(item["feed_date"]),
        vendor_item_id=item["vendor_item_id"],
        headline=clean["headline"],
        body=clean["body"],
        source_url=item["source_url"],
        source_domain=item["source_domain"],
        tickers=tuple(item["tickers"]),
        rule_codes=tuple(item["rule_codes"]),
        company_names=dict(state.get("names") or {}),
    )


def _earlier_evidence(item: dict[str, Any]) -> list[ev.Evidence]:
    """The rule engine's and the AI run's evidence, tagged by origin."""
    found = []
    for entry in item["rule_evidence"]:
        found.append(
            dataclasses.replace(ev.Evidence.from_json(entry), source="rules")
        )
    for entry in item["ai_evidence"]:
        found.append(
            dataclasses.replace(ev.Evidence.from_json(entry), source="ai-run")
        )
    return found


def _for_judge(entry: ev.Evidence) -> ev.Evidence:
    """Evidence as the judge sees it: never a quote of injected text."""
    if entry.code == "INJECTION_ATTEMPT":
        return dataclasses.replace(entry, message=_INJECTION_FOR_JUDGE)
    return entry


def _tools(runtime: lg_runtime.Runtime[Context]) -> tools_lib.Tools:
    context = runtime.context
    if context is None or context.tools is None:
        raise RuntimeError("the verify graph needs its tools in the context")
    return context.tools


Node = Callable[..., Awaitable[dict[str, Any]]]


def _nodes(deps: Deps) -> dict[str, Node]:
    """The node functions, closed over the process's dependencies."""

    async def load(state: State) -> dict[str, Any]:
        row = await deps.repo.load_item(state["news_id"])
        if row is None:
            raise LookupError(f"no news item {state['news_id']}")
        return {"item": _item_json(row)}

    async def sanitize_node(state: State) -> dict[str, Any]:
        item = state["item"]
        clean = sanitize.sanitize(item["headline"], item["body"])
        english = "UNSUPPORTED_LANGUAGE" not in item[
            "ai_codes"
        ] and language.is_english(clean.text)
        return {
            "clean": {
                "headline": clean.headline,
                "body": clean.body,
                "injections": list(clean.injections),
            },
            "english": english,
        }

    async def extract(state: State) -> dict[str, Any]:
        # Increment 3's extraction (ai.entity), by ticker.
        names = {
            str(c["ticker"]): str(c["name"])
            for c in state["item"]["companies"]
            if c.get("ticker")
        }
        return {"names": names}

    async def entity_node(
        state: State, runtime: lg_runtime.Runtime[Context]
    ) -> dict[str, Any]:
        found = await checks.entity_check(_tools(runtime), _check_item(state))
        return {
            "entity": {
                "finding": found.finding.to_json(),
                "names": found.names,
                "rank": found.rank,
            }
        }

    async def source_node(
        state: State, runtime: lg_runtime.Runtime[Context]
    ) -> dict[str, Any]:
        found = await checks.source_check(_tools(runtime), _check_item(state))
        return {
            "source": {"finding": found.finding.to_json(), "tier": found.tier}
        }

    async def corroboration_node(
        state: State, runtime: lg_runtime.Runtime[Context]
    ) -> dict[str, Any]:
        found = await checks.corroboration(
            _tools(runtime), _check_item(state), dict(state.get("names") or {})
        )
        return {
            "corroboration": {
                "finding": found.finding.to_json(),
                "primary_source": found.primary_source,
                "independent_sources": found.independent_sources,
                "searched": found.searched,
            }
        }

    async def claim_node(
        state: State, runtime: lg_runtime.Runtime[Context]
    ) -> dict[str, Any]:
        found = await checks.claim_check(_tools(runtime), _check_item(state))
        return {"claims": found.to_json()}

    async def style_node(state: State) -> dict[str, Any]:
        return {"style": checks.style_signals(_check_item(state)).to_json()}

    async def ml_node(state: State) -> dict[str, Any]:
        if deps.ml is None:
            return {"ml": None}
        clean = state["clean"]
        try:
            sentiment, verdict = await deps.ml.predict(
                clean["headline"], clean["body"]
            )
        except Exception as e:  # noqa: BLE001 - evidence only, never fatal.
            _log.warning("classic ML failed: %r", e)
            return {"ml": None}
        return {
            "ml": {
                "sentiment": sentiment.to_json(),
                "verdict": None if verdict is None else verdict.to_json(),
            }
        }

    async def aggregate(state: State) -> dict[str, Any]:
        return await _aggregate(deps, state)

    async def enrich(state: State) -> dict[str, Any]:
        found = policy.impact(
            state["clean"]["headline"],
            state["entity"]["rank"],
            deps.universe_size,
        )
        return {"impact": dataclasses.asdict(found)}

    async def persist(state: State) -> dict[str, Any]:
        decision = state["decision"]
        impact = state["impact"]
        verdict = repository.Verdict(
            news_id=state["news_id"],
            run_id=state["run_id"],
            thread_id=state["thread_id"],
            verdict=decision["verdict"],
            confidence=decision["confidence"],
            reason_codes=tuple(decision["reason_codes"]),
            rationale=decision["rationale"],
            rule_verdict=decision["rule_verdict"],
            rule_confidence=decision["rule_confidence"],
            judge_verdict=decision["judge_verdict"],
            judge_confidence=decision["judge_confidence"],
            judge_model=decision["judge_model"],
            escalated=decision["escalated"],
            review_reasons=tuple(state["reasons"]),
            relevance=impact["relevance"],
            impact=impact["level"],
            impact_score=impact["score"],
            prompt_version=prompts.PROMPT_VERSION,
            evidence=tuple(ev.Evidence.from_json(e) for e in state["evidence"]),
        )
        progress = await deps.repo.save(verdict)
        if progress.counted:
            await after_count(
                deps,
                state["run_id"],
                progress,
                {
                    "news_id": state["news_id"],
                    "vendor_item_id": state["item"]["vendor_item_id"],
                    "verdict": decision["verdict"],
                    "confidence": decision["confidence"],
                    "review": bool(state["reasons"]),
                },
            )
        return {"progress": {"done": progress.done, "total": progress.total}}

    async def review(state: State) -> dict[str, Any]:
        decision = state["decision"]
        answer = lg_types.interrupt(
            {
                "news_id": state["news_id"],
                "verdict": decision["verdict"],
                "confidence": decision["confidence"],
                "reasons": state["reasons"],
            }
        )
        return {"review": dict(answer)}

    async def finalize(state: State) -> dict[str, Any]:
        answer = state.get("review")
        if not answer:
            return {}
        action = str(answer.get("action"))
        status = REVIEW_STATUS[action]
        verdict = state["decision"]["verdict"]
        if action == "override":
            verdict = str(answer["verdict"])
        who = answer.get("reviewer") or "the market open"
        if action == "expire":
            message = (
                "Nobody reviewed it before the market opened: the AI verdict "
                f"{verdict} stands, marked unreviewed."
            )
        elif action == "approve":
            message = f"{who} approved the AI verdict {verdict}."
        else:
            message = (
                f"{who} overrode {state['decision']['verdict']} with "
                f"{verdict}: {answer.get('comment', '')}"
            )
        entry = ev.Evidence("review", None, message, "analyst")
        stored = await deps.repo.finish_review(
            state["news_id"], status, verdict, entry
        )
        if stored and deps.events is not None:
            await deps.events.publish(
                state["run_id"],
                "review",
                {
                    "news_id": state["news_id"],
                    "status": status,
                    "verdict": verdict,
                },
            )
        return {}

    return {
        "load": load,
        "sanitize": sanitize_node,
        "extract": extract,
        "entity_check": entity_node,
        "source_check": source_node,
        "corroboration": corroboration_node,
        "claim_check": claim_node,
        "style_signals": style_node,
        "ml_check": ml_node,
        "aggregate": aggregate,
        "enrich": enrich,
        "persist": persist,
        "review": review,
        "finalize": finalize,
    }


def _ml_evidence(ml: dict[str, Any] | None) -> list[ev.Evidence]:
    if not ml:
        return []
    sentiment = ml["sentiment"]
    parts = [
        f"FinBERT sentiment: {sentiment['label'].lower()} "
        f"({sentiment['score']:.2f})"
    ]
    if ml.get("verdict") is not None:
        verdict = ml["verdict"]
        parts.append(
            f"DistilBERT classifier: {verdict['label']} "
            f"({verdict['score']:.2f})"
        )
    message = "Classic ML baseline (context only): " + "; ".join(parts) + "."
    return [ev.Evidence("ml", None, message, "model")]


async def _aggregate(deps: Deps, state: State) -> dict[str, Any]:
    """Hard rules, the FABRICATED rule, the judge, the combined verdict."""
    item = state["item"]
    check_item = _check_item(state)
    entity = ev.Finding.from_json(state["entity"]["finding"])
    source = ev.Finding.from_json(state["source"]["finding"])
    corro_state = state["corroboration"]
    corro = checks.CorroborationResult(
        ev.Finding.from_json(corro_state["finding"]),
        corro_state["primary_source"],
        corro_state["independent_sources"],
        corro_state["searched"],
    )
    claims = ev.Finding.from_json(state["claims"])
    style = ev.Finding.from_json(state["style"])
    codes = set(item["rule_codes"]) | set(item["ai_codes"])
    codes |= set(claims.codes) | set(style.codes)
    tier = state["source"]["tier"]
    fabricated = checks.fabricated(check_item, sorted(codes), tier, corro)
    codes |= set(fabricated.codes)
    guard = llama_guard.Verdict.from_json(state.get("guard"))
    guard_unsafe = guard.ran and not guard.safe and deps.guard_routes
    note = ""
    if guard.ran and not guard.safe and not deps.guard_routes:
        note = " Evidence only: the small guard model flags ordinary news too."
    guard_entry = ev.Evidence(
        "guard", None, f"Llama Guard: {guard.describe()}.{note}", "model"
    )
    evidence = [
        *_earlier_evidence(item),
        guard_entry,
        *entity.evidence,
        *source.evidence,
        *corro.finding.evidence,
        *claims.evidence,
        *style.evidence,
        *fabricated.evidence,
        *_ml_evidence(state.get("ml")),
    ]
    english = bool(state["english"])
    signals = policy.Signals(
        codes=frozenset(codes),
        source_tier=tier,
        primary_source=corro.primary_source,
        independent_sources=corro.independent_sources,
        english=english,
    )
    rule = policy.decide(signals)
    result = None
    if (
        deps.judge is not None
        and not rule.hard
        and english
        and not guard_unsafe
    ):
        result, notes = await _judge(deps, state, evidence, rule)
        evidence += notes
    combined = policy.combine(rule, None if result is None else result.view)
    if (
        result is not None
        and deps.judge is not None
        and deps.judge.in_band(combined.decision.confidence)
        and await deps.judge.can_escalate()
    ):
        cloud, notes = await _judge(deps, state, evidence, rule, cloud=True)
        evidence += notes
        if cloud is not None:
            result = cloud
            combined = policy.combine(rule, cloud.view)
    if result is not None:
        view = result.view
        rationale = f" {view.rationale}" if view.rationale else ""
        evidence.append(
            ev.Evidence(
                "judge",
                None,
                f"{result.model}: {view.verdict} (confidence "
                f"{view.confidence:.2f}).{rationale}",
                "model",
            )
        )
    reasons = policy.review_reasons(
        combined,
        deps.min_confidence,
        guard_unsafe=guard_unsafe,
        english=english,
    )
    final = combined.decision
    return {
        "decision": {
            "verdict": final.verdict,
            "confidence": final.confidence,
            "reason_codes": list(final.reason_codes),
            "rationale": final.rationale,
            "rule_verdict": rule.verdict,
            "rule_confidence": rule.confidence,
            "judge_verdict": None if result is None else result.view.verdict,
            "judge_confidence": (
                None if result is None else result.view.confidence
            ),
            "judge_model": None if result is None else result.model,
            "escalated": bool(result is not None and result.escalated),
            "disagree": combined.disagree,
        },
        "evidence": [e.to_json() for e in evidence],
        "reasons": reasons,
    }


async def _judge(
    deps: Deps,
    state: State,
    evidence: list[ev.Evidence],
    rule: policy.Decision,
    *,
    cloud: bool = False,
) -> tuple[judge_lib.JudgeResult | None, list[ev.Evidence]]:
    """One judge call; a failure is evidence, never an exception."""
    if deps.judge is None:
        return None, []
    item = state["item"]
    clean = state["clean"]
    numbered = [(f"E{i + 1}", _for_judge(e)) for i, e in enumerate(evidence)]
    config = deps.tracer.config(
        "verify.judge.cloud" if cloud else "verify.judge",
        tags=[prompts.PROMPT_VERSION, f"run:{state['run_id']}"],
        metadata={
            "news_id": state["news_id"],
            "vendor_item_id": item["vendor_item_id"],
            "rule_verdict": rule.verdict,
        },
    )
    sanitized = sanitize.Sanitized(clean["headline"], clean["body"])
    try:
        result = await deps.judge.judge(
            sanitized, item["vendor_item_id"], numbered, config, cloud=cloud
        )
    except (judge_lib.JudgeError, ValueError) as e:
        _log.warning("judge of %s failed: %s", item["vendor_item_id"], e)
        which = "cloud judge" if cloud else "judge"
        note = ev.Evidence(
            "judge",
            None,
            f"The {which} gave no usable answer ({e}); the rules decide alone.",
            "model",
        )
        return None, [note]
    except Exception as e:  # noqa: BLE001 - the gateway may be down.
        _log.warning("judge of %s unavailable: %r", item["vendor_item_id"], e)
        note = ev.Evidence(
            "judge",
            None,
            "The judge model is unavailable; the rules decide alone.",
            "model",
        )
        return None, [note]
    notes = []
    low, high = deps.judge.band
    if cloud:
        notes.append(
            ev.Evidence(
                "judge",
                None,
                f"Uncertain (combined confidence {low:.2f} to {high:.2f}): "
                f"escalated to {result.model} (${result.cost_usd:.4f}).",
                "model",
            )
        )
    return result, notes


async def after_count(
    deps: Deps,
    run_id: int,
    progress: repository.Progress,
    item: dict[str, Any] | None,
) -> None:
    """Publishes an item's progress and finishes the run after the last."""
    if deps.events is not None and item is not None:
        await deps.events.publish(
            run_id,
            "item",
            {**item, "done": progress.done, "total": progress.total},
        )
    if progress.done >= progress.total:
        run = await deps.repo.finish_run(run_id)
        if run is not None and deps.events is not None:
            await deps.events.publish(run_id, "run.done", run_summary(run))


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    """The JSON of a finished run's counts (the ``run.done`` event)."""
    keys = (
        "run_id",
        "total",
        "done",
        "failed",
        "verified",
        "unverified",
        "misleading",
        "fake",
        "pending_review",
        "escalated",
        "total_ms",
    )
    summary = {key: run.get(key) for key in keys}
    summary["status"] = run.get("status")
    return summary


def build(deps: Deps, checkpointer: Any = None) -> Any:
    """The compiled graph.

    Args:
        deps: The node dependencies.
        checkpointer: A LangGraph checkpointer (Postgres in the stack,
            in memory in tests and the eval); required for the review
            interrupt.

    Returns:
        The compiled graph; invoke it with ``context=Context(tools)``.
    """
    nodes = _nodes(deps)
    builder = lg.StateGraph(State, context_schema=Context)
    for name, node in nodes.items():
        builder.add_node(name, node)
    builder.add_edge(lg.START, "load")
    builder.add_edge("load", "sanitize")
    builder.add_edge("sanitize", "extract")
    for name in CHECK_NODES:
        builder.add_edge("extract", name)
        builder.add_edge(name, "aggregate")
    builder.add_edge("aggregate", "enrich")
    builder.add_edge("enrich", "persist")
    builder.add_conditional_edges(
        "persist",
        lambda state: "review" if state["reasons"] else "finalize",
        ["review", "finalize"],
    )
    builder.add_edge("review", "finalize")
    builder.add_edge("finalize", lg.END)
    return builder.compile(checkpointer=checkpointer, name="verify_news")
