"""Evidence: why a check flagged (or cleared) an item, with its source.

Every check of the verify graph returns a ``Finding``: reason codes plus
evidence. The aggregate step numbers the evidence E1, E2... for the LLM
judge, which must cite those ids; the same list is stored in
``ai.evidence`` and shown on the news detail page.
"""

from __future__ import annotations

import dataclasses
from typing import Any

# Reason codes (see "Verdicts" in the plan). The rules of increment 2 and
# the AI run of increment 3 add their own; these are increment 4's.
FABRICATED_CLAIM = "FABRICATED_CLAIM"
CONTRADICTED_BY_FILING = "CONTRADICTED_BY_FILING"
NUMBER_MISMATCH = "NUMBER_MISMATCH"
SENSATIONAL_HEADLINE = "SENSATIONAL_HEADLINE"
NO_CORROBORATION = "NO_CORROBORATION"
CONFLICTING_VERSION = "CONFLICTING_VERSION"

# Every code an item can carry, in display order.
REASON_ORDER = (
    "FAKE_COMPANY",
    "FAKE_TICKER",
    "SPOOFED_SOURCE",
    FABRICATED_CLAIM,
    CONTRADICTED_BY_FILING,
    NUMBER_MISMATCH,
    "STALE",
    CONFLICTING_VERSION,
    SENSATIONAL_HEADLINE,
    NO_CORROBORATION,
    "INJECTION_ATTEMPT",
    "UNSUPPORTED_LANGUAGE",
)


def ordered(codes: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    """Codes in ``REASON_ORDER`` (unknown codes last, sorted)."""
    known = [c for c in REASON_ORDER if c in codes]
    return known + sorted(set(codes) - set(REASON_ORDER))


@dataclasses.dataclass(frozen=True)
class Evidence:
    """One finding.

    Attributes:
        check: The check that found it: ``entity``, ``source``,
            ``corroboration``, ``claim``, ``style``, ``rules``, ``ai``,
            ``guard``, ``language``, ``ml``, ``judge`` or ``review``.
        code: The reason code it supports, or None for context.
        message: A plain-text explanation.
        source: Where it came from: ``registry``, ``reputation``,
            ``filing``, ``web``, ``prices``, ``rules``, ``model``...
        url: A link (a filing or a web result), when there is one.
        title: The link's title.
    """

    check: str
    code: str | None
    message: str
    source: str = ""
    url: str | None = None
    title: str | None = None

    def to_json(self) -> dict[str, Any]:
        """The evidence as the graph state and the API carry it."""
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Evidence:
        """Rebuilds evidence stored by ``to_json`` (or by the rules)."""
        return cls(
            check=str(data["check"]),
            code=data.get("code"),
            message=str(data["message"]),
            source=str(data.get("source") or ""),
            url=data.get("url"),
            title=data.get("title"),
        )


@dataclasses.dataclass(frozen=True)
class Finding:
    """Reason codes and evidence of one check on one item."""

    codes: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """The finding as the graph state carries it."""
        return {
            "codes": list(self.codes),
            "evidence": [e.to_json() for e in self.evidence],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Finding:
        """Rebuilds a finding stored by ``to_json``; None is empty."""
        if not data:
            return cls()
        return cls(
            tuple(data.get("codes", ())),
            tuple(Evidence.from_json(e) for e in data.get("evidence", ())),
        )
