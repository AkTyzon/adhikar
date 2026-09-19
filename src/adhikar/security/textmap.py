"""Offset mapping across text rewrites.

Redaction replaces ``jane@acme.com`` (13 chars) with ``[[EMAIL_1]]`` (11 chars).
Every character after that point shifts, so an offset produced against the
redacted text no longer means the same thing in the original.  Silently ignoring
this is how provenance systems end up citing the wrong sentence -- the citation
still "resolves", just to text a few characters off, and nobody notices until a
user reads a highlighted clause that does not say what the answer claimed.

:class:`OffsetMap` makes the rewrite explicit and invertible.  It is built once
during redaction and carried alongside the rewritten text, so any offset the
model returns can be translated back into the coordinate system of the document
the user actually uploaded.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True, slots=True)
class Replacement:
    """One substitution: ``original[start:end]`` became ``replacement``."""

    start: int
    end: int
    replacement: str

    @property
    def original_length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class _Segment:
    """A run of the rewritten text and where it came from."""

    new_start: int
    new_end: int
    old_start: int
    old_end: int
    is_replacement: bool


class OffsetMap:
    """Bidirectional offset translation between an original and rewritten text.

    Build with :meth:`apply`, which performs the rewrite and records the map in
    one pass.  Translation is O(log n) via binary search over segment starts.
    """

    __slots__ = ("_new_starts", "_segments", "new_length", "original_length")

    def __init__(self, segments: list[_Segment], original_length: int, new_length: int) -> None:
        self._segments = segments
        self._new_starts = [segment.new_start for segment in segments]
        self.original_length = original_length
        self.new_length = new_length

    @classmethod
    def identity(cls, length: int) -> OffsetMap:
        """A map for text that was not rewritten at all."""
        segments = [_Segment(0, length, 0, length, is_replacement=False)] if length else []
        return cls(segments, length, length)

    @classmethod
    def apply(cls, text: str, replacements: list[Replacement]) -> tuple[str, OffsetMap]:
        """Rewrite ``text`` and return the new text alongside its offset map.

        Replacements must not overlap; they are sorted here, and an overlap is a
        programming error rather than something to paper over.
        """
        ordered = sorted(replacements, key=lambda r: r.start)
        for previous, current in pairwise(ordered):
            if current.start < previous.end:
                raise ValueError(
                    f"overlapping replacements: [{previous.start},{previous.end}) "
                    f"and [{current.start},{current.end})"
                )

        parts: list[str] = []
        segments: list[_Segment] = []
        cursor = 0  # position in the original
        new_cursor = 0  # position in the rewritten text

        for replacement in ordered:
            if replacement.start > cursor:
                run = text[cursor : replacement.start]
                parts.append(run)
                segments.append(
                    _Segment(
                        new_start=new_cursor,
                        new_end=new_cursor + len(run),
                        old_start=cursor,
                        old_end=replacement.start,
                        is_replacement=False,
                    )
                )
                new_cursor += len(run)

            parts.append(replacement.replacement)
            segments.append(
                _Segment(
                    new_start=new_cursor,
                    new_end=new_cursor + len(replacement.replacement),
                    old_start=replacement.start,
                    old_end=replacement.end,
                    is_replacement=True,
                )
            )
            new_cursor += len(replacement.replacement)
            cursor = replacement.end

        if cursor < len(text):
            run = text[cursor:]
            parts.append(run)
            segments.append(
                _Segment(
                    new_start=new_cursor,
                    new_end=new_cursor + len(run),
                    old_start=cursor,
                    old_end=len(text),
                    is_replacement=False,
                )
            )
            new_cursor += len(run)

        return "".join(parts), cls(segments, len(text), new_cursor)

    # ------------------------------------------------------------------ lookup
    def _segment_for_new(self, offset: int) -> _Segment | None:
        if not self._segments:
            return None
        index = bisect.bisect_right(self._new_starts, offset) - 1
        if index < 0:
            return None
        segment = self._segments[index]
        return segment if offset < segment.new_end else None

    def to_original(self, offset: int) -> int:
        """Translate a rewritten-text offset into the original coordinate system.

        An offset landing inside a replacement maps to the *start* of the text it
        replaced: a placeholder has no interior in the original, so pointing at
        the whole redacted value is the only honest answer.
        """
        if offset >= self.new_length:
            return self.original_length
        segment = self._segment_for_new(offset)
        if segment is None:
            return min(offset, self.original_length)
        if segment.is_replacement:
            return segment.old_start
        return segment.old_start + (offset - segment.new_start)

    def to_original_range(self, start: int, end: int) -> tuple[int, int]:
        """Translate a half-open range, widening to cover any replacement it touches.

        Widening rather than narrowing is deliberate: an answer citing part of a
        redacted value should highlight the entire value, never a fragment that
        reads as though it means something else.
        """
        if start >= end:
            raise ValueError(f"range start {start} must precede end {end}")
        original_start = self.to_original(start)
        last = max(start, end - 1)
        segment = self._segment_for_new(last)
        if segment is not None and segment.is_replacement:
            original_end = segment.old_end
        else:
            original_end = self.to_original(last) + 1
        return original_start, max(original_end, original_start + 1)
