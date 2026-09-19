"""Clause segmentation.

A contract is a numbered tree, and splitting it on that structure -- rather than
on sentences, paragraphs or a fixed token window -- is what lets the rest of the
system talk about "clause 7.2" instead of "characters 4,100 to 4,600".  Every
downstream stage (risk detection, baseline alignment, obligation extraction,
citation rendering) addresses clauses, so this module's correctness bounds
theirs.

The one invariant enforced here: **clause spans tile the document exactly.**
Every character belongs to at most one clause, clauses are ordered, and no span
extends beyond the text.  :func:`segment` asserts this before returning, because
a silent off-by-one would surface much later as a citation pointing at the wrong
obligation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from adhikar.domain import Clause, Span
from adhikar.errors import CatalogError

#: Fewer than this many headings means the numbering scheme did not match.
_MIN_USEFUL_BOUNDARIES = 2


@dataclass(frozen=True, slots=True)
class HeadingPattern:
    id: str
    regex: re.Pattern[str]
    depth_from: str
    depth: int

    def depth_of(self, label: str) -> int:
        """Nesting depth implied by a heading label."""
        if self.depth_from == "dots":
            return label.count(".")
        return self.depth


@dataclass(frozen=True, slots=True)
class SegmentationRules:
    patterns: tuple[HeadingPattern, ...]
    min_clause_chars: int
    max_clause_chars: int


def load_rules(path: Path) -> SegmentationRules:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"segmentation rules not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"segmentation rules at {path} are not valid YAML: {exc}") from exc

    patterns: list[HeadingPattern] = []
    for entry in raw.get("heading_patterns", []):
        try:
            regex = re.compile(entry["pattern"])
        except re.error as exc:
            raise CatalogError(
                f"heading pattern '{entry.get('id', '?')}' is invalid: {exc}"
            ) from exc
        patterns.append(
            HeadingPattern(
                id=entry["id"],
                regex=regex,
                depth_from=entry.get("depth_from", "fixed"),
                depth=int(entry.get("depth", 0)),
            )
        )
    if not patterns:
        raise CatalogError(f"segmentation rules at {path} define no heading patterns")

    return SegmentationRules(
        patterns=tuple(patterns),
        min_clause_chars=int(raw.get("min_clause_chars", 40)),
        max_clause_chars=int(raw.get("max_clause_chars", 4000)),
    )


@lru_cache(maxsize=4)
def _cached_rules(path: Path) -> SegmentationRules:
    return load_rules(path)


@dataclass(frozen=True, slots=True)
class _Boundary:
    offset: int
    label: str
    depth: int


def segment(text: str, document_id: str, rules_path: Path) -> tuple[Clause, ...]:
    """Split a document into clauses with exact, non-overlapping spans.

    Falls back to paragraph splitting when a document carries no recognisable
    numbering -- an unnumbered terms-of-service page still needs addressable
    units, and returning one clause covering the whole document would make every
    citation useless.
    """
    rules = _cached_rules(rules_path)
    if not text.strip():
        return ()

    boundaries = _find_boundaries(text, rules)
    # One boundary means nothing was found but the document start, so the
    # numbering scheme did not match and paragraphs are the better unit.
    if len(boundaries) < _MIN_USEFUL_BOUNDARIES:
        boundaries = _paragraph_boundaries(text)
    if not boundaries:
        boundaries = [_Boundary(offset=0, label="", depth=0)]

    clauses = _build_clauses(text, document_id, boundaries, rules)
    _assert_tiling(clauses, text)
    return clauses


def _find_boundaries(text: str, rules: SegmentationRules) -> list[_Boundary]:
    """Locate every heading in the document, in order."""
    boundaries: list[_Boundary] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            for pattern in rules.patterns:
                match = pattern.regex.match(line)
                if match:
                    label = match.group(1).strip()
                    boundaries.append(
                        _Boundary(
                            offset=offset,
                            label=label,
                            depth=pattern.depth_of(label),
                        )
                    )
                    break
        offset += len(line)
    return boundaries


def _paragraph_boundaries(text: str) -> list[_Boundary]:
    """Fallback: treat each blank-line-separated block as a unit."""
    boundaries = [_Boundary(offset=0, label="", depth=0)]
    for match in re.finditer(r"\n\s*\n", text):
        boundaries.append(_Boundary(offset=match.end(), label="", depth=0))
    return boundaries


def _build_clauses(
    text: str,
    document_id: str,
    boundaries: list[_Boundary],
    rules: SegmentationRules,
) -> tuple[Clause, ...]:
    """Turn boundaries into clauses, merging fragments and splitting giants."""
    ranges: list[tuple[int, int, str]] = []

    # A preamble before the first heading is itself a clause -- title pages and
    # party definitions live there and carry real obligations.
    if boundaries[0].offset > 0 and text[: boundaries[0].offset].strip():
        ranges.append((0, boundaries[0].offset, ""))

    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].offset if index + 1 < len(boundaries) else len(text)
        if end > boundary.offset:
            ranges.append((boundary.offset, end, boundary.label))

    merged = _merge_fragments(ranges, text, rules.min_clause_chars)
    expanded = [
        piece
        for start, end, label in merged
        for piece in _split_oversized(text, start, end, label, rules.max_clause_chars)
    ]

    clauses: list[Clause] = []
    for index, (start, end, label) in enumerate(expanded):
        body = text[start:end]
        if not body.strip():
            continue
        # Trim trailing whitespace off the span so a citation never highlights a
        # run of blank lines, while keeping the leading offset exact.
        trimmed_end = end - (len(body) - len(body.rstrip()))
        if trimmed_end <= start:
            continue
        clauses.append(
            Clause(
                id=f"{document_id}:c{index}",
                document_id=document_id,
                index=index,
                heading=label or None,
                text=text[start:trimmed_end],
                span=Span.over(document_id, text, start, trimmed_end),
            )
        )
    return tuple(clauses)


def _merge_fragments(
    ranges: list[tuple[int, int, str]], text: str, minimum: int
) -> list[tuple[int, int, str]]:
    """Absorb too-short segments into the following clause.

    A bare heading line ("3. Indemnity") is not a clause; it introduces one. It
    merges forward so the heading and its body form a single citable unit.
    """
    merged: list[tuple[int, int, str]] = []
    pending: tuple[int, int, str] | None = None

    for start, end, label in ranges:
        if pending is None:
            clause_start, clause_label = start, label
        else:
            # The absorbed fragment is usually a bare title; the clause being
            # merged into carries the more specific label, so it wins.
            clause_start, clause_label = pending[0], label or pending[2]
            pending = None

        if len(text[clause_start:end].strip()) < minimum:
            pending = (clause_start, end, clause_label)
            continue
        merged.append((clause_start, end, clause_label))

    if pending is not None:
        if merged:
            last_start, _, last_label = merged[-1]
            merged[-1] = (last_start, pending[1], last_label)
        else:
            merged.append(pending)
    return merged


def _split_oversized(
    text: str, start: int, end: int, label: str, maximum: int
) -> list[tuple[int, int, str]]:
    """Break an over-long clause at paragraph boundaries, preserving offsets."""
    if end - start <= maximum:
        return [(start, end, label)]

    pieces: list[tuple[int, int, str]] = []
    cursor = start
    part = 1
    for match in re.finditer(r"\n\s*\n", text[start:end]):
        boundary = start + match.end()
        if boundary - cursor >= maximum // 2:
            pieces.append((cursor, boundary, f"{label} (part {part})" if label else ""))
            cursor = boundary
            part += 1
    if cursor < end:
        pieces.append((cursor, end, f"{label} (part {part})" if label and part > 1 else label))
    return pieces or [(start, end, label)]


def _assert_tiling(clauses: tuple[Clause, ...], text: str) -> None:
    """Verify the structural invariant every downstream stage relies on.

    Raises:
        CatalogError: segmentation produced overlapping or out-of-range spans,
            which is a defect in this module rather than bad input.
    """
    previous_end = -1
    for clause in clauses:
        span = clause.span
        if span.start < previous_end:
            raise CatalogError(
                f"clause {clause.id} starts at {span.start}, overlapping the "
                f"previous clause which ended at {previous_end}"
            )
        if span.end > len(text):
            raise CatalogError(
                f"clause {clause.id} ends at {span.end}, beyond the {len(text)}-char document"
            )
        # The strongest check available: the recorded quote still resolves.
        span.resolve(text)
        previous_end = span.end
