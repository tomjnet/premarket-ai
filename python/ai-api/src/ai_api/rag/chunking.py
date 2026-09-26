"""Splits documents into overlapping chunks for retrieval.

Paragraphs are packed into chunks of about ``size`` characters; a paragraph
longer than that is split at sentences. Each chunk after the first starts
with the end of the previous one (``overlap`` characters, at a sentence or
word boundary), so a fact that spans a boundary is still found.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MIN_CHUNK_CHARS = 40


def _pieces(text: str, size: int) -> list[str]:
    pieces = []
    for raw in re.split(r"\n\s*\n", text):
        paragraph = " ".join(raw.split())
        if not paragraph:
            continue
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            rest = sentence
            while len(rest) > size:
                cut = rest.rfind(" ", 0, size)
                if cut <= 0:
                    cut = size
                pieces.append(rest[:cut])
                rest = rest[cut:].lstrip()
            if rest:
                pieces.append(rest)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    for boundary in (". ", " "):
        at = tail.find(boundary)
        if 0 <= at < len(tail) - 1:
            return tail[at + len(boundary) :]
    return tail


def split(text: str, size: int = 1500, overlap: int = 200) -> list[str]:
    """Chunks of about ``size`` characters.

    Args:
        text: The document text (paragraphs separated by blank lines).
        size: Target chunk size.
        overlap: Characters carried over from the previous chunk.

    Returns:
        The chunks, in order; tiny leftovers are dropped.
    """
    chunks: list[str] = []
    current = ""
    for piece in _pieces(text, size):
        if current and len(current) + 1 + len(piece) > size:
            chunks.append(current)
            carried = _tail(current, overlap)
            current = f"{carried} {piece}".strip() if carried else piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= _MIN_CHUNK_CHARS]
