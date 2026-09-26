"""Structured outputs: every model answer is parsed into these models.

The JSON schema of each model is sent with the request (the gateway turns
it into Ollama's output grammar), and pydantic validates what comes back.
The limits are loose on purpose; the enricher trims and checks after
parsing, so a slightly long answer isn't a failure.
"""

from __future__ import annotations

from typing import Literal

import pydantic

Sentiment = Literal["bullish", "neutral", "bearish"]


class Company(pydantic.BaseModel):
    """A company the item names."""

    name: str = pydantic.Field(
        description="The company name as written in the item."
    )
    ticker: str | None = pydantic.Field(
        default=None,
        description="The stock ticker only if the item states it, else null.",
    )


class Extraction(pydantic.BaseModel):
    """Companies, tickers and atomic claims of one news item."""

    companies: list[Company] = pydantic.Field(
        description="Every company the item names."
    )
    claims: list[str] = pydantic.Field(
        description=(
            "Up to 5 atomic factual claims, one sentence each, with numbers "
            "copied exactly."
        )
    )


class Summary(pydantic.BaseModel):
    """A short neutral summary and the sentiment for the company's stock."""

    summary: str = pydantic.Field(
        description="One or two neutral sentences, at most 280 characters."
    )
    sentiment: Sentiment = pydantic.Field(
        description="What the item means for the named company's stock."
    )
