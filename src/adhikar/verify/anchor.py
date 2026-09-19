"""Resolving model-supplied quotes to document spans.

A model is asked to copy the passage it relied on.  This module finds that
passage in the document and converts it into a :class:`~adhikar.domain.Span`.
Everything hinges on the search being strict enough that a fabricated quote
fails, and tolerant enough that a real quote is not rejected over whitespace.

The tolerance ladder, in order:

1. **Exact match.**  The overwhelming majority of real quotes.
2. **Whitespace-insensitive match.**  Extraction collapses newlines
   inconsistently across PDF layouts; a quote spanning a line break is genuine
   even when its spacing differs. Matching is done against a normalised copy of
   the document and the offsets mapped back, so the span still covers the real
   characters.

There is deliberately no fuzzy or semantic fallback.  A quote that differs in
*wording* is not a quote, and accepting it would reintroduce exactly the
unverifiable citation this system exists to eliminate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from adhikar.domain import Span

#: Quotes shorter than this are not evidence -- "the Client" appears everywhere
#: and anchoring to the first occurrence would be arbitrary.
MIN_QUOTE_CHARS = 12


@dataclass(frozen=True, slots=True)
class AnchorFailure:
    """A quote that could not be located in the document."""

    quote: str
    reason: str


@dataclass(frozen=True, slots=True)
class AnchorResult:
    spans: tuple[Span, ...]
    failures: tuple[AnchorFailure, ...]

    @property
    def ok(self) -> bool:
        return bool(self.spans) and not self.failures


def anchor_quotes(
    quotes: Sequence[str], document_id: str, text: str, *, search_from: int = 0
) -> AnchorResult:
    """Locate each quote in ``text`` and return spans for those that resolve."""
    spans: list[Span] = []
    failures: list[AnchorFailure] = []

    for quote in quotes:
        cleaned = quote.strip()
        if len(cleaned) < MIN_QUOTE_CHARS:
            failures.append(
                AnchorFailure(quote=quote, reason="quote is too short to identify a passage")
            )
            continue

        located = _locate(cleaned, text, search_from)
        if located is None:
            failures.append(
                AnchorFailure(quote=quote, reason="passage does not appear in the document")
            )
            continue
        start, end = located
        spans.append(Span.over(document_id, text, start, end))

    return AnchorResult(spans=tuple(spans), failures=tuple(failures))


def _locate(quote: str, text: str, search_from: int) -> tuple[int, int] | None:
    """Find a quote, preferring an exact match and falling back to whitespace folding."""
    index = text.find(quote, search_from)
    if index == -1 and search_from:
        index = text.find(quote)
    if index != -1:
        return index, index + len(quote)
    return _locate_whitespace_insensitive(quote, text)


def _locate_whitespace_insensitive(quote: str, text: str) -> tuple[int, int] | None:
    """Match ignoring whitespace differences, mapping offsets back to the original.

    A regex built from the quote's non-space characters, joined by ``\\s+``, finds
    the passage wherever its line breaks fall. The quote is escaped first, so a
    quote containing regex metacharacters -- brackets and parentheses are common
    in contracts -- cannot alter the pattern.
    """
    tokens = [re.escape(token) for token in quote.split()]
    if not tokens:
        return None
    pattern = re.compile(r"\s+".join(tokens))
    match = pattern.search(text)
    return (match.start(), match.end()) if match else None
