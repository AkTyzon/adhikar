"""Core domain types.

The whole system is built around one invariant: **every statement Adhikar shows a
user is traceable to a byte range in a document the user supplied.**  :class:`Span`
is that atom.  A span is not a citation label the model wrote -- it is a pair of
character offsets that can be re-resolved against the source text at any later
time, which is what makes fabricated provenance detectable in code rather than by
asking a model to be honest.

Everything here is immutable (``frozen=True``).  Analysis stages take domain
objects and return new ones; nothing is mutated in place, so an audit record can
hold a reference to the exact value a stage produced.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


class Span(BaseModel):
    """A half-open character range ``[start, end)`` into a document's normalised text.

    ``quote_sha256`` pins the text that occupied the range when the span was
    created.  :meth:`resolve` re-reads the range from the live document and
    refuses to return text whose hash has drifted, which turns "the model cited
    something that isn't there" from a silent failure into a raised exception.
    """

    model_config = {"frozen": True}

    document_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError(f"span start {self.start} must precede end {self.end}")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start

    @staticmethod
    def hash_quote(text: str) -> str:
        """Hash of the exact characters a span covers."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @classmethod
    def over(cls, document_id: str, text: str, start: int, end: int) -> Span:
        """Build a span over ``text[start:end]``, pinning the quote hash."""
        if not 0 <= start < end <= len(text):
            raise ValueError(f"range [{start}, {end}) does not lie within {len(text)} chars")
        return cls(
            document_id=document_id,
            start=start,
            end=end,
            quote_sha256=cls.hash_quote(text[start:end]),
        )

    def resolve(self, text: str) -> str:
        """Return the covered text, or raise if the document no longer matches.

        Raises:
            SpanResolutionError: the range is out of bounds or its contents changed.
        """
        from adhikar.errors import SpanResolutionError

        if self.end > len(text):
            raise SpanResolutionError(
                f"span [{self.start}, {self.end}) exceeds document length {len(text)}"
            )
        quoted = text[self.start : self.end]
        if self.hash_quote(quoted) != self.quote_sha256:
            raise SpanResolutionError(
                f"span [{self.start}, {self.end}) no longer matches its recorded quote"
            )
        return quoted

    def overlaps(self, other: Span) -> bool:
        return (
            self.document_id == other.document_id
            and self.start < other.end
            and other.start < self.end
        )


# --------------------------------------------------------------------------- #
# Documents and clauses
# --------------------------------------------------------------------------- #


class Severity(StrEnum):
    """Risk severity.

    Ordered low to critical; :func:`severity_rank` gives the sort key.  Never
    rendered as colour alone in the UI -- each level carries a text label and a
    distinct shape, so the encoding survives greyscale and colour blindness.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_ORDER[severity]


class Clause(BaseModel):
    """A segmented unit of a contract, carrying its own offsets.

    ``clause_type`` is a key into the runtime clause catalogue (see
    :mod:`adhikar.analysis.catalog`) -- never a hardcoded literal in analysis code.
    """

    model_config = {"frozen": True}

    id: str
    document_id: str
    index: int = Field(ge=0)
    heading: str | None
    text: str
    span: Span
    clause_type: str | None = None
    type_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Document(BaseModel):
    """An ingested document plus everything derived deterministically from it."""

    model_config = {"frozen": True}

    id: str
    filename: str
    media_type: str
    content_sha256: str
    text: str
    clauses: tuple[Clause, ...] = ()
    page_count: int | None = None
    ingested_at: datetime

    def clause_at(self, offset: int) -> Clause | None:
        """The clause containing ``offset``, if any."""
        return next((c for c in self.clauses if c.span.start <= offset < c.span.end), None)

    def clause_by_id(self, clause_id: str) -> Clause | None:
        return next((c for c in self.clauses if c.id == clause_id), None)


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


class Verdict(StrEnum):
    """Outcome of checking one claim against only the spans it cites."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class Claim(BaseModel):
    """One atomic assertion bound to the spans that are supposed to support it.

    Generation stages emit claims, never prose.  Prose is assembled *after*
    verification from the claims that survived, which is why an unsupported
    sentence can be removed rather than merely flagged.
    """

    model_config = {"frozen": True}

    text: str = Field(min_length=1)
    spans: tuple[Span, ...]

    @model_validator(mode="after")
    def _requires_provenance(self) -> Self:
        if not self.spans:
            raise ValueError("a claim must cite at least one span")
        return self


class VerifiedClaim(BaseModel):
    """A claim after the entailment gate has ruled on it."""

    model_config = {"frozen": True}

    claim: Claim
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @property
    def admissible(self) -> bool:
        """Whether this claim may be shown to the user as fact."""
        return self.verdict is Verdict.SUPPORTED


class VerifiedAnswer(BaseModel):
    """The output of any generation path: what survived, and what did not.

    ``withheld`` is deliberately part of the public payload.  A system that
    silently drops unsupported claims is indistinguishable from one that never
    generated them; showing the user what was removed is the difference between
    a filter and an audit.
    """

    model_config = {"frozen": True}

    question: str
    admitted: tuple[VerifiedClaim, ...]
    withheld: tuple[VerifiedClaim, ...]
    abstained: bool = False
    abstain_reason: str | None = None

    @property
    def support_rate(self) -> float:
        total = len(self.admitted) + len(self.withheld)
        return len(self.admitted) / total if total else 0.0


# --------------------------------------------------------------------------- #
# Findings and obligations
# --------------------------------------------------------------------------- #


class DeviationDirection(StrEnum):
    FAVOURS_COUNTERPARTY = "favours_counterparty"
    FAVOURS_YOU = "favours_you"
    BALANCED = "balanced"
    ABSENT = "absent"


class BaselineDeviation(BaseModel):
    """How a clause compares with the market-norm baseline it was matched against."""

    model_config = {"frozen": True}

    baseline_id: str
    baseline_title: str
    expected: str
    observed: str
    direction: DeviationDirection
    magnitude: float = Field(ge=0.0, le=1.0)


class Finding(BaseModel):
    """A risk identified in a clause, with its evidence and plain-language gloss."""

    model_config = {"frozen": True}

    id: str
    detector_id: str
    clause_type: str
    severity: Severity
    title: str
    plain_language: str
    why_it_matters: str
    spans: tuple[Span, ...]
    baseline_deviation: BaselineDeviation | None = None
    questions_for_lawyer: tuple[str, ...] = ()


class TriggerKind(StrEnum):
    """How an obligation's deadline is anchored.

    Only ``ABSOLUTE`` carries a date the document states outright.  Everything
    else is *computed* by :mod:`adhikar.analysis.deadlines` -- the model extracts
    the offset and the anchor, arithmetic happens in Python.
    """

    ABSOLUTE = "absolute"
    RELATIVE_TO_EVENT = "relative_to_event"
    RECURRING = "recurring"
    ON_CONDITION = "on_condition"
    NONE = "none"


class Obligation(BaseModel):
    """Who owes what to whom, and when -- as structured data rather than prose."""

    model_config = {"frozen": True}

    id: str
    obligor: str
    obligee: str | None
    action: str
    trigger_kind: TriggerKind
    trigger_event: str | None = None
    offset_days: int | None = None
    business_days: bool = False
    stated_date: date | None = None
    computed_due: date | None = None
    recurrence: str | None = None
    condition: str | None = None
    spans: tuple[Span, ...]
    document_id: str


class Contradiction(BaseModel):
    """Two obligations that cannot both be satisfied."""

    model_config = {"frozen": True}

    id: str
    kind: str
    explanation: str
    left: Obligation
    right: Obligation
    spans: tuple[Span, ...]


def spans_of(items: Sequence[Finding | Obligation | Claim]) -> tuple[Span, ...]:
    """Flatten the spans of a sequence of evidence-carrying objects."""
    return tuple(span for item in items for span in item.spans)
