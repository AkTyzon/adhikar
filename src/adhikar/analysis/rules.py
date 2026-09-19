"""Evaluator for the catalogue's condition language.

The clause catalogue expresses detection as data -- ``any``/``all``/``none``/
``near`` over regular expressions.  This module is the only place that language
is interpreted, which keeps the semantics in one testable unit and means a rule
author can reason about behaviour without reading the analysis engine.

Every evaluation returns the byte ranges that caused it, not just a boolean.
That is what allows a risk finding to cite the words that triggered it: a user
who is told "your liability is uncapped" can see *which* eleven words said so.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from adhikar.errors import CatalogError


@dataclass(frozen=True, slots=True)
class Near:
    """Two patterns that must both appear within a character window."""

    left: re.Pattern[str]
    right: re.Pattern[str]
    window: int


@dataclass(frozen=True, slots=True)
class ConditionMatch:
    """Why a condition held, with evidence ranges into the evaluated text."""

    ranges: tuple[tuple[int, int], ...]
    #: Ids of the sub-clauses that fired, for explaining a rule in the UI.
    reasons: tuple[str, ...] = ()

    def merged_ranges(self) -> tuple[tuple[int, int], ...]:
        """Overlapping evidence ranges coalesced, so highlights do not stack."""
        if not self.ranges:
            return ()
        ordered = sorted(self.ranges)
        merged: list[tuple[int, int]] = [ordered[0]]
        for start, end in ordered[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return tuple(merged)


@dataclass(frozen=True, slots=True)
class Condition:
    """A compiled condition from the catalogue.

    An empty condition never matches. That is deliberate: a rule whose ``when``
    block was mistyped into nothing should detect nothing, rather than firing on
    every clause in every contract.
    """

    any_of: tuple[re.Pattern[str], ...] = ()
    all_of: tuple[re.Pattern[str], ...] = ()
    none_of: tuple[re.Pattern[str], ...] = ()
    near: Near | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.any_of or self.all_of or self.none_of or self.near)

    def evaluate(self, text: str) -> ConditionMatch | None:
        """Return the evidence if the condition holds, otherwise ``None``."""
        if self.is_empty:
            return None

        ranges: list[tuple[int, int]] = []
        reasons: list[str] = []

        # `none_of` is a veto: check it first and cheaply.
        for pattern in self.none_of:
            if pattern.search(text):
                return None

        if self.any_of:
            hits = [m for pattern in self.any_of for m in _first(pattern, text)]
            if not hits:
                return None
            ranges.extend(hits)
            reasons.append("any")

        for pattern in self.all_of:
            match = pattern.search(text)
            if match is None:
                return None
            ranges.append((match.start(), match.end()))
        if self.all_of:
            reasons.append("all")

        if self.near is not None:
            near_hit = _evaluate_near(self.near, text)
            if near_hit is None:
                return None
            ranges.extend(near_hit)
            reasons.append("near")

        # A condition consisting only of `none_of` holds vacuously when nothing
        # is vetoed; report the whole text as its evidence since the finding is
        # about an *absence*.
        if not ranges:
            ranges.append((0, min(len(text), 200)))
            reasons.append("absence")

        return ConditionMatch(ranges=tuple(ranges), reasons=tuple(reasons))


def _first(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    match = pattern.search(text)
    return [(match.start(), match.end())] if match else []


def _evaluate_near(near: Near, text: str) -> list[tuple[int, int]] | None:
    """Find a left/right pair within the window.

    The evidence returned is the single passage spanning both matches, not the
    two fragments. The point of a proximity rule is that these words appear
    *together*, so highlighting the text between them is what shows the reader
    why the rule fired.
    """
    for left in near.left.finditer(text):
        window_start = max(0, left.start() - near.window)
        window_end = min(len(text), left.end() + near.window)
        right = near.right.search(text, window_start, window_end)
        if right is not None:
            return [(min(left.start(), right.start()), max(left.end(), right.end()))]
    return None


def compile_condition(raw: Any, *, context: str) -> Condition:
    """Compile a condition block from the catalogue.

    Raises:
        CatalogError: the block is malformed or contains an invalid regex.
    """
    if raw is None:
        return Condition()
    if not isinstance(raw, dict):
        raise CatalogError(f"{context}: condition must be a mapping, got {type(raw).__name__}")

    unknown = set(raw) - {"any", "all", "none", "near"}
    if unknown:
        raise CatalogError(f"{context}: unknown condition key(s) {sorted(unknown)}")

    near: Near | None = None
    if "near" in raw:
        block = raw["near"]
        missing = {"left", "right"} - set(block)
        if missing:
            raise CatalogError(f"{context}: 'near' is missing {sorted(missing)}")
        near = Near(
            left=_compile(block["left"], context),
            right=_compile(block["right"], context),
            window=int(block.get("window", 200)),
        )

    return Condition(
        any_of=tuple(_compile(p, context) for p in raw.get("any", ())),
        all_of=tuple(_compile(p, context) for p in raw.get("all", ())),
        none_of=tuple(_compile(p, context) for p in raw.get("none", ())),
        near=near,
    )


def _compile(pattern: str, context: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE | re.DOTALL)
    except re.error as exc:
        raise CatalogError(f"{context}: invalid regex {pattern!r}: {exc}") from exc


def score_markers(patterns: Sequence[re.Pattern[str]], text: str) -> float:
    """Fraction of favourable markers present, used for baseline comparison."""
    if not patterns:
        return 0.0
    return sum(1 for pattern in patterns if pattern.search(text)) / len(patterns)


def coverage_ranges(matches: Iterable[ConditionMatch]) -> tuple[tuple[int, int], ...]:
    """All evidence ranges from several matches, coalesced."""
    combined = ConditionMatch(ranges=tuple(r for m in matches for r in m.ranges))
    return combined.merged_ranges()
