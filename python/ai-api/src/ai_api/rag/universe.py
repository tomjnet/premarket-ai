"""The lab universe (``python/config/universe.yaml``): the 50 companies."""

from __future__ import annotations

import dataclasses
import pathlib
import re

import yaml

_UPPER_WORD = re.compile(r"\b[A-Z][A-Z0-9]{0,5}(?:\.[A-Z])?\b")


@dataclasses.dataclass(frozen=True)
class Member:
    """One universe company.

    Attributes:
        ticker: As the vendor writes it (BRK.B).
        name: The legal name.
        short: The name in headlines.
    """

    ticker: str
    name: str
    short: str


def load(config_dir: pathlib.Path) -> list[Member]:
    """The companies of ``universe.yaml``, in rank order."""
    data = yaml.safe_load((config_dir / "universe.yaml").read_text("utf-8"))
    return [
        Member(str(c["ticker"]), str(c["name"]), str(c["short"]))
        for c in data["companies"]
    ]


def tickers_in(text: str, members: list[Member]) -> list[str]:
    """Universe tickers a question mentions, by ticker or by name.

    Args:
        text: The question.
        members: The universe.

    Returns:
        The tickers, in universe order.
    """
    words = set(_UPPER_WORD.findall(text))
    lowered = text.lower()
    found = []
    for member in members:
        if member.ticker in words or re.search(
            rf"\b{re.escape(member.short.lower())}\b", lowered
        ):
            found.append(member.ticker)
    return found
