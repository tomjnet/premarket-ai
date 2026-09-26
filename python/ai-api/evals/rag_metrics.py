"""The RAGAS metrics, computed with an LLM judge through the gateway.

The ``ragas`` package (0.4.3, the newest) doesn't import next to LangChain
1.x: it needs a ``langchain_community`` module that no longer exists. So
the two metrics of the plan are implemented here with RAGAS's definitions:

- **Faithfulness**: the answer is split into atomic statements; each is
  judged supported or not by the retrieved sources. Score = supported /
  statements.
- **Context precision** (with a reference answer): each retrieved source is
  judged useful or not for reaching the reference answer; score = the
  mean of precision@k over the ranks k of the useful sources (so useful
  sources ranked first score higher).

Structured outputs keep the judge's answers parseable; a failed judgment
leaves the question out of that metric (reported as ``judge_failures``).
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core import language_models
import pydantic

from ai_api.guard import spotlight


class _Statement(pydantic.BaseModel):
    statement: str
    supported: bool


class _Statements(pydantic.BaseModel):
    """The answer's atomic statements, each judged against the sources."""

    statements: list[_Statement]


class _Verdict(pydantic.BaseModel):
    n: int
    useful: bool


class _Useful(pydantic.BaseModel):
    """One verdict per numbered source."""

    sources: list[_Verdict]


FAITHFULNESS_SYSTEM = f"""\
You grade an answer against its sources.
{spotlight.DATA_RULES}
Split the answer into short atomic factual statements (ignore citation
markers like [1] and ignore refusals or statements that the sources don't
say something). For each statement, set supported to true only if the
sources state it or directly imply it."""

PRECISION_SYSTEM = f"""\
You grade retrieved sources for a question.
{spotlight.DATA_RULES}
For each numbered source, give its number n and useful: true if it
contains information useful for reaching the reference answer, else false.
Judge every source."""


def _sources(contexts: Sequence[str]) -> str:
    return "\n\n".join(
        spotlight.source_block(i + 1, f"Source {i + 1}", text)
        for i, text in enumerate(contexts)
    )


async def faithfulness(
    judge: language_models.BaseChatModel,
    answer: str,
    contexts: Sequence[str],
) -> float | None:
    """Supported statements / statements (None when there are none)."""
    runnable = judge.with_structured_output(_Statements, method="json_schema")
    user = (
        f"{_sources(contexts)}\n\n<question>\nAnswer to grade:\n{answer}\n"
        "</question>"
    )
    result = await runnable.ainvoke(
        [("system", FAITHFULNESS_SYSTEM), ("human", user)]
    )
    if not result.statements:
        return None
    supported = sum(1 for s in result.statements if s.supported)
    return supported / len(result.statements)


def average_precision(useful: Sequence[bool]) -> float:
    """Mean precision@k over the ranks k of the useful items (RAGAS)."""
    hits = 0
    total = 0.0
    for k, is_useful in enumerate(useful, start=1):
        if is_useful:
            hits += 1
            total += hits / k
    return total / hits if hits else 0.0


async def context_precision(
    judge: language_models.BaseChatModel,
    question: str,
    reference: str,
    contexts: Sequence[str],
) -> float | None:
    """Average precision of the ranked sources against the reference."""
    runnable = judge.with_structured_output(_Useful, method="json_schema")
    user = (
        f"{_sources(contexts)}\n\n<question>\nQuestion: {question}\n"
        f"Reference answer: {reference}\n</question>"
    )
    result = await runnable.ainvoke(
        [("system", PRECISION_SYSTEM), ("human", user)]
    )
    verdicts = {v.n: v.useful for v in result.sources}
    if not verdicts:
        return None
    # A source the judge skipped counts as not useful.
    return average_precision(
        [verdicts.get(i + 1, False) for i in range(len(contexts))]
    )
