"""The LLM judge's structured output (validated by pydantic).

The judge decides only the uncertain middle: FAKE is not in its schema, so
a model can't answer it even if an injected instruction asks it to.
"""

from __future__ import annotations

from typing import Literal

import pydantic

JudgeVerdict = Literal["VERIFIED", "UNVERIFIED", "MISLEADING"]
JudgeCode = Literal[
    "NUMBER_MISMATCH",
    "SENSATIONAL_HEADLINE",
    "STALE",
    "NO_CORROBORATION",
    "CONFLICTING_VERSION",
]


class Judgement(pydantic.BaseModel):
    """The judge's verdict on one item, citing the evidence it used."""

    verdict: JudgeVerdict = pydantic.Field(
        description="VERIFIED, UNVERIFIED or MISLEADING."
    )
    confidence: float = pydantic.Field(
        ge=0.0, le=1.0, description="How sure you are, from 0 to 1."
    )
    reason_codes: list[JudgeCode] = pydantic.Field(
        default_factory=list,
        description="Only codes that the evidence supports.",
    )
    evidence_ids: list[str] = pydantic.Field(
        description="The evidence ids you relied on, like E1 or E3."
    )
    rationale: str = pydantic.Field(
        description=(
            "At most two sentences that cite evidence ids in brackets, "
            "like [E2]."
        )
    )
