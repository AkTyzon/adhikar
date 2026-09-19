"""Clause-level risk analysis and baseline comparison.

Two questions, answered separately because they fail differently:

**"What is in this clause?"** is answered by rules from the catalogue.  Rules are
deterministic, cite the words that triggered them, and have a false-negative
profile you can measure.  No model is involved, so this stage cannot hallucinate
a risk and costs nothing to run.

**"Is that normal?"** is answered by comparison against a baseline -- the
balanced version of the same clause, also from the catalogue.  This is the part a
chat interface structurally cannot do: "unlimited liability" is only alarming
relative to the twelve-month cap that comparable agreements carry, and a model
answering from a single uploaded document has nothing to compare against.

A finding's spans are document-absolute.  Rules evaluate against clause-local
text, so every offset is rebased through the clause's own span before a
:class:`~adhikar.domain.Finding` is constructed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from adhikar.analysis.catalog import ClauseCatalog, ClauseType
from adhikar.analysis.rules import score_markers
from adhikar.domain import (
    BaselineDeviation,
    Clause,
    DeviationDirection,
    Document,
    Finding,
    Severity,
    Span,
    severity_rank,
)

#: Contribution of one finding to the document risk score, by severity. These are
#: presentation weights for an ordinal summary, not probabilities.
_SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.INFO: 0.0,
    Severity.LOW: 0.1,
    Severity.MEDIUM: 0.3,
    Severity.HIGH: 0.6,
    Severity.CRITICAL: 1.0,
}

#: A clause whose favourable-marker score is at least this is treated as balanced.
_BALANCED_MARKER_SCORE = 0.5


@dataclass(frozen=True, slots=True)
class RiskReport:
    """Everything the risk stage concluded about one document."""

    findings: tuple[Finding, ...]
    typed_clauses: tuple[Clause, ...]
    #: Clause types the catalogue knows about that this document never mentions.
    #: An absent indemnity clause is itself worth telling a reader about.
    missing_clause_types: tuple[str, ...]

    @property
    def score(self) -> float:
        """Overall risk in [0, 1], saturating rather than summing without bound."""
        if not self.findings:
            return 0.0
        total = sum(_SEVERITY_WEIGHT[f.severity] for f in self.findings)
        # Diminishing returns: the tenth medium finding says less than the first.
        return round(min(1.0, total / (total + 3.0)), 4)

    @property
    def highest_severity(self) -> Severity | None:
        return max((f.severity for f in self.findings), key=severity_rank, default=None)

    def by_severity(self) -> tuple[Finding, ...]:
        return tuple(sorted(self.findings, key=lambda f: -severity_rank(f.severity)))

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        return counts


def type_clauses(clauses: Sequence[Clause], catalog: ClauseCatalog) -> tuple[Clause, ...]:
    """Label each clause with its catalogue type.

    Returns new clauses rather than mutating: domain objects are frozen, so a
    stage that changes something returns a new value the audit record can pin.
    """
    typed: list[Clause] = []
    for clause in clauses:
        clause_type, confidence = catalog.classify(clause.text)
        typed.append(
            clause.model_copy(update={"clause_type": clause_type, "type_confidence": confidence})
        )
    return tuple(typed)


def analyse(document: Document, catalog: ClauseCatalog) -> RiskReport:
    """Run every applicable risk rule over a document's clauses."""
    typed = type_clauses(document.clauses, catalog)
    findings: list[Finding] = []
    seen_types: set[str] = set()

    for clause in typed:
        # Every type whose detectors fire, not only the primary label: a clause
        # headed "Indemnity" that also disclaims a liability cap must be checked
        # against both sets of rules or the second risk is never seen.
        for clause_type, _score in catalog.candidates(clause.text):
            seen_types.add(clause_type.id)
            findings.extend(_findings_for_clause(document, clause, clause_type))

    # Report only the types where absence is itself meaningful -- a clause type
    # with a baseline is one the catalogue has an opinion about.
    missing = tuple(
        clause_type.id
        for clause_type in catalog
        if clause_type.id not in seen_types and clause_type.baseline is not None
    )
    return RiskReport(findings=tuple(findings), typed_clauses=typed, missing_clause_types=missing)


def _findings_for_clause(
    document: Document, clause: Clause, clause_type: ClauseType
) -> list[Finding]:
    findings: list[Finding] = []
    deviation = compare_to_baseline(clause, clause_type)

    for rule in clause_type.risks:
        match = rule.condition.evaluate(clause.text)
        if match is None:
            continue
        spans = _rebase_spans(document, clause, match.merged_ranges())
        findings.append(
            Finding(
                id=f"{clause.id}:{rule.id}",
                detector_id=rule.id,
                clause_type=clause_type.id,
                severity=rule.severity,
                title=rule.title,
                plain_language=clause_type.plain_language,
                why_it_matters=rule.why_it_matters,
                spans=spans,
                baseline_deviation=deviation,
                questions_for_lawyer=rule.questions_for_lawyer,
            )
        )
    return findings


def _rebase_spans(
    document: Document, clause: Clause, ranges: Sequence[tuple[int, int]]
) -> tuple[Span, ...]:
    """Translate clause-local match ranges into document-absolute spans.

    Ranges are clamped to the clause: a regex with a generous ``.{0,80}`` can
    legitimately run to the clause's end, and a span that overshot into the next
    clause would highlight text the rule never examined.
    """
    base = clause.span.start
    limit = clause.span.end
    spans: list[Span] = []
    for start, end in ranges:
        absolute_start = min(base + start, limit - 1)
        absolute_end = min(base + end, limit)
        if absolute_end > absolute_start:
            spans.append(Span.over(document.id, document.text, absolute_start, absolute_end))
    # Fall back to the whole clause rather than emitting a finding with no
    # provenance -- an uncitable finding would violate the system's invariant.
    return tuple(spans) or (clause.span,)


def compare_to_baseline(clause: Clause, clause_type: ClauseType) -> BaselineDeviation | None:
    """Compare a clause against the balanced version the catalogue describes.

    The magnitude is the share of favourable markers the clause is *missing*.
    This is a coarse signal and is presented as one: the user sees the expected
    position and the observed text side by side, with the score as ordering
    rather than as a measurement.
    """
    baseline = clause_type.baseline
    if baseline is None:
        return None

    marker_score = score_markers(baseline.favourable_markers, clause.text)
    if not baseline.favourable_markers:
        direction = DeviationDirection.BALANCED
        magnitude = 0.0
    elif marker_score >= _BALANCED_MARKER_SCORE:
        direction = DeviationDirection.BALANCED
        magnitude = round(1.0 - marker_score, 4)
    else:
        direction = DeviationDirection.FAVOURS_COUNTERPARTY
        magnitude = round(1.0 - marker_score, 4)

    return BaselineDeviation(
        baseline_id=clause_type.id,
        baseline_title=clause_type.title,
        expected=baseline.expected,
        observed=_excerpt(clause.text),
        direction=direction,
        magnitude=magnitude,
    )


def missing_clause_finding(document: Document, clause_type: ClauseType) -> Finding | None:
    """A finding for a clause type the document never addresses.

    Only produced for types with a baseline, and always at ``medium`` -- absence
    is a prompt to check, not a defect in itself.
    """
    if clause_type.baseline is None or not document.clauses:
        return None
    return Finding(
        id=f"{document.id}:missing:{clause_type.id}",
        detector_id="missing_clause",
        clause_type=clause_type.id,
        severity=Severity.MEDIUM,
        title=f"No {clause_type.title.lower()} clause found",
        plain_language=clause_type.plain_language,
        why_it_matters=(
            f"This agreement does not appear to address {clause_type.title.lower()}. "
            f"Comparable agreements usually do: {clause_type.baseline.expected}"
        ),
        # The document's opening is cited as the anchor: the finding is about the
        # document as a whole, and every finding must carry provenance.
        spans=(document.clauses[0].span,),
        baseline_deviation=BaselineDeviation(
            baseline_id=clause_type.id,
            baseline_title=clause_type.title,
            expected=clause_type.baseline.expected,
            observed="Not present in this document.",
            direction=DeviationDirection.ABSENT,
            magnitude=1.0,
        ),
    )


def _excerpt(text: str, limit: int = 240) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
