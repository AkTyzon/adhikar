"""Clause-level comparison between two documents.

Text diffing two contracts is close to useless: renumbering one clause shifts
everything after it, and a reworded-but-equivalent paragraph shows as wholly
changed.  What a reader needs is the *semantic* pairing -- "your indemnity clause
versus theirs" -- and then the difference between the pair.

Alignment is mutual-best-match over clause type plus lexical similarity, which is
deterministic, explainable, and needs no embedding model.  Clauses that pair with
nothing are reported as added or removed, which is usually where the important
change is: a clause the counterparty quietly dropped from the last round.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from adhikar.domain import Clause, Document

#: Below this similarity two clauses are not the same clause. Set high enough
#: that "the indemnity clause" and "the confidentiality clause" never pair merely
#: because both are legal prose.
_PAIR_THRESHOLD = 0.30

#: Matching clause types is strong evidence of correspondence, so it contributes
#: directly to the pairing score alongside lexical similarity.
_TYPE_BONUS = 0.35

#: How many differing words to surface per clause pair. Enough to see what
#: changed at a glance, few enough to stay scannable.
_DISTINCTIVE_TERMS = 8

#: Words this short carry no signal for similarity scoring.
_MIN_TERM_CHARS = 2

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "by",
        "within",
        "from",
        "at",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "shall",
        "must",
        "will",
        "may",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "their",
        "such",
        "any",
        "all",
        "each",
        "either",
        "not",
        "no",
        "party",
        "parties",
        "agreement",
        "clause",
        "section",
        "hereof",
        "herein",
    ]
)


class ChangeKind(StrEnum):
    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class ClausePairing:
    """One aligned pair, or an unpaired clause on either side."""

    kind: ChangeKind
    left: Clause | None
    right: Clause | None
    similarity: float
    #: Words present on one side only, which is what a reader actually scans for.
    added_terms: tuple[str, ...] = ()
    removed_terms: tuple[str, ...] = ()

    @property
    def clause_type(self) -> str | None:
        for clause in (self.left, self.right):
            if clause is not None and clause.clause_type:
                return clause.clause_type
        return None

    @property
    def significant(self) -> bool:
        """Whether this pairing is worth a reader's attention."""
        return self.kind is not ChangeKind.UNCHANGED


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    left_document: str
    right_document: str
    pairings: tuple[ClausePairing, ...]

    def changes(self) -> tuple[ClausePairing, ...]:
        return tuple(p for p in self.pairings if p.significant)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for pairing in self.pairings:
            counts[pairing.kind.value] = counts.get(pairing.kind.value, 0) + 1
        return counts


def compare(left: Document, right: Document) -> ComparisonResult:
    """Align two documents clause by clause."""
    left_clauses = list(left.clauses)
    right_clauses = list(right.clauses)

    vocabulary = _idf([c.text for c in left_clauses] + [c.text for c in right_clauses])
    scores = [[_score(a, b, vocabulary) for b in right_clauses] for a in left_clauses]

    matched_right: set[int] = set()
    pairings: list[ClausePairing] = []

    for left_index, clause in enumerate(left_clauses):
        best_index, best_score = _best_available(scores, left_index, matched_right)
        if best_index is None or best_score < _PAIR_THRESHOLD:
            pairings.append(
                ClausePairing(
                    kind=ChangeKind.REMOVED,
                    left=clause,
                    right=None,
                    similarity=0.0,
                    removed_terms=_distinctive(clause.text, ""),
                )
            )
            continue

        # Mutual best match: the pairing must be the right clause's best too, or
        # a generic clause would greedily consume a better partner.
        column = [row[best_index] for row in scores]
        if max(column) > best_score + 1e-9:
            pairings.append(
                ClausePairing(
                    kind=ChangeKind.REMOVED,
                    left=clause,
                    right=None,
                    similarity=0.0,
                    removed_terms=_distinctive(clause.text, ""),
                )
            )
            continue

        partner = right_clauses[best_index]
        matched_right.add(best_index)
        identical = _normalise(clause.text) == _normalise(partner.text)
        pairings.append(
            ClausePairing(
                kind=ChangeKind.UNCHANGED if identical else ChangeKind.MODIFIED,
                left=clause,
                right=partner,
                similarity=round(best_score, 4),
                added_terms=() if identical else _distinctive(partner.text, clause.text),
                removed_terms=() if identical else _distinctive(clause.text, partner.text),
            )
        )

    pairings.extend(
        ClausePairing(
            kind=ChangeKind.ADDED,
            left=None,
            right=clause,
            similarity=0.0,
            added_terms=_distinctive(clause.text, ""),
        )
        for index, clause in enumerate(right_clauses)
        if index not in matched_right
    )

    return ComparisonResult(
        left_document=left.id, right_document=right.id, pairings=tuple(pairings)
    )


def _best_available(
    scores: list[list[float]], row: int, taken: set[int]
) -> tuple[int | None, float]:
    best_index: int | None = None
    best_score = 0.0
    for index, score in enumerate(scores[row]):
        if index in taken:
            continue
        if score > best_score:
            best_index, best_score = index, score
    return best_index, best_score


def _score(left: Clause, right: Clause, idf: dict[str, float]) -> float:
    """Cosine similarity over TF-IDF, plus a bonus for a shared clause type."""
    similarity = _cosine(left.text, right.text, idf)
    if left.clause_type and left.clause_type == right.clause_type:
        similarity = min(1.0, similarity + _TYPE_BONUS)
    return similarity


def _idf(documents: Sequence[str]) -> dict[str, float]:
    total = len(documents) or 1
    frequency: Counter[str] = Counter()
    for document in documents:
        frequency.update(set(_terms(document)))
    return {term: math.log(1 + total / count) for term, count in frequency.items()}


def _cosine(left: str, right: str, idf: dict[str, float]) -> float:
    left_counts = Counter(_terms(left))
    right_counts = Counter(_terms(right))
    if not left_counts or not right_counts:
        return 0.0

    shared = set(left_counts) & set(right_counts)
    numerator = sum(left_counts[t] * right_counts[t] * idf.get(t, 1.0) ** 2 for t in shared)
    left_norm = math.sqrt(sum((c * idf.get(t, 1.0)) ** 2 for t, c in left_counts.items()))
    right_norm = math.sqrt(sum((c * idf.get(t, 1.0)) ** 2 for t, c in right_counts.items()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in _STOPWORDS and len(word) > _MIN_TERM_CHARS
    ]


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _distinctive(text: str, other: str, limit: int = _DISTINCTIVE_TERMS) -> tuple[str, ...]:
    """Content words in ``text`` but not ``other``, longest first.

    Length ordering is a cheap proxy for salience: "indemnification" and
    "perpetual" carry more signal than "each" or "such".
    """
    unique = set(_terms(text)) - set(_terms(other))
    return tuple(sorted(unique, key=lambda w: (-len(w), w))[:limit])
