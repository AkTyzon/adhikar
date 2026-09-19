"""Rendering document text with evidence highlights.

This function escapes untrusted document text and wraps ranges of it in markup.
Getting that order wrong is the classic cross-site scripting bug: escape after
inserting tags and the tags are destroyed; insert tags after escaping without
tracking how escaping changed the offsets and the highlights land in the wrong
place, potentially splitting an entity.

The approach here avoids both.  The text is cut into segments at span
boundaries *first*, each segment is escaped independently, and markup is only
ever assembled from escaped pieces.  No escaped string is ever searched or
re-offset, so there is no path by which document content becomes markup.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from markupsafe import Markup

from adhikar.domain import Span


@dataclass(frozen=True, slots=True)
class Highlight:
    """A range to mark, with the accessible label describing why."""

    start: int
    end: int
    label: str
    kind: str = "evidence"
    anchor_id: str | None = None


def highlights_from_spans(
    spans: Sequence[Span], label: str, kind: str = "evidence", anchor_id: str | None = None
) -> list[Highlight]:
    return [
        Highlight(start=s.start, end=s.end, label=label, kind=kind, anchor_id=anchor_id)
        for s in spans
    ]


def render_highlighted(text: str, highlights: Sequence[Highlight]) -> Markup:
    """Escape ``text`` and wrap each highlight in a labelled ``<mark>``.

    Overlapping highlights are resolved by keeping the first at any position:
    nested ``<mark>`` elements are announced inconsistently by screen readers,
    and a doubly-marked passage communicates nothing extra to a sighted reader
    either.
    """
    if not text:
        return Markup("")

    ordered = _resolve_overlaps(highlights, len(text))
    parts: list[str] = []
    cursor = 0

    for highlight in ordered:
        if highlight.start > cursor:
            parts.append(escape(text[cursor : highlight.start]))
        body = escape(text[highlight.start : highlight.end])
        label = escape(highlight.label)
        kind = escape(highlight.kind)
        anchor = f' id="{escape(highlight.anchor_id)}"' if highlight.anchor_id else ""
        parts.append(
            f'<mark class="mark mark--{kind}"{anchor}>'
            # The label is read by assistive technology before the marked text,
            # so the reason for the highlight is available without sight of the
            # colour that conveys it visually.
            f'<span class="visually-hidden">{label}: </span>'
            f"{body}"
            f'<span class="visually-hidden"> (end of highlight)</span>'
            f"</mark>"
        )
        cursor = highlight.end

    if cursor < len(text):
        parts.append(escape(text[cursor:]))

    # Every element of `parts` is either the output of html.escape() or markup
    # this function built from escaped pieces, so wrapping is safe here and
    # only here. See this module's docstring for why the order matters.
    # nosec B704 - every element of `parts` is either the output of
    # html.escape() or markup this function assembled from escaped pieces, so
    # nothing unescaped can reach the browser. Proven by the XSS cases in
    # tests/unit/test_render_and_store.py::TestHighlightRendering.
    return Markup("".join(parts))  # noqa: S704  # nosec B704


def _resolve_overlaps(highlights: Sequence[Highlight], length: int) -> list[Highlight]:
    """Clamp to bounds, drop empties, and keep the first claim on each position."""
    candidates = sorted(
        (
            Highlight(
                start=max(0, h.start),
                end=min(length, h.end),
                label=h.label,
                kind=h.kind,
                anchor_id=h.anchor_id,
            )
            for h in highlights
            if 0 <= h.start < length and h.end > h.start
        ),
        key=lambda h: (h.start, -(h.end - h.start)),
    )

    kept: list[Highlight] = []
    cursor = 0
    for highlight in candidates:
        if highlight.start < cursor:
            continue
        kept.append(highlight)
        cursor = highlight.end
    return kept


def excerpt_around(text: str, span: Span, context: int = 180) -> tuple[str, str, str]:
    """A quoted passage with surrounding context, for showing evidence in place.

    Returns ``(before, quote, after)`` unescaped; the template escapes them.
    Boundaries are nudged to whitespace so the excerpt does not begin or end
    mid-word.
    """
    start = max(0, span.start - context)
    end = min(len(text), span.end + context)

    if start > 0:
        space = text.find(" ", start, span.start)
        if space != -1:
            start = space + 1
    if end < len(text):
        space = text.rfind(" ", span.end, end)
        if space != -1:
            end = space

    prefix = ("…" if start > 0 else "") + text[start : span.start]
    suffix = text[span.end : end] + ("…" if end < len(text) else "")
    return prefix, text[span.start : span.end], suffix
