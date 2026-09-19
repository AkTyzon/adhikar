"""The provenance invariant.

Span is the atom the whole system rests on: if a span can silently point at text
it did not originally cover, every citation in the product is unreliable. These
tests pin that down.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adhikar.domain import Claim, Severity, Span, severity_rank
from adhikar.errors import SpanResolutionError

TEXT = "The Client shall pay each invoice within thirty (30) days of receipt."


class TestSpan:
    def test_resolves_to_the_text_it_covers(self) -> None:
        span = Span.over("d1", TEXT, 4, 10)
        assert span.resolve(TEXT) == "Client"

    def test_rejects_a_range_outside_the_document(self) -> None:
        with pytest.raises(ValueError, match="does not lie within"):
            Span.over("d1", TEXT, 0, len(TEXT) + 1)

    def test_rejects_an_inverted_range(self) -> None:
        with pytest.raises(ValueError, match="does not lie within"):
            Span.over("d1", TEXT, 10, 4)

    def test_refuses_to_resolve_against_changed_text(self) -> None:
        """The core guarantee: a span cannot silently cite different text."""
        span = Span.over("d1", TEXT, 4, 10)
        altered = TEXT.replace("Client", "Vendor")

        with pytest.raises(SpanResolutionError, match="no longer matches"):
            span.resolve(altered)

    def test_refuses_to_resolve_against_a_truncated_document(self) -> None:
        span = Span.over("d1", TEXT, 50, 60)
        with pytest.raises(SpanResolutionError, match="exceeds document length"):
            span.resolve(TEXT[:30])

    def test_detects_a_same_length_substitution(self) -> None:
        """Length-preserving edits are the case a bounds check alone would miss."""
        start = TEXT.index("thirty")
        span = Span.over("d1", TEXT, start, start + len("thirty"))
        tampered = TEXT.replace("thirty", "ninety")

        assert len(tampered) == len(TEXT)
        with pytest.raises(SpanResolutionError):
            span.resolve(tampered)

    def test_is_immutable(self) -> None:
        span = Span.over("d1", TEXT, 0, 3)
        with pytest.raises(ValidationError):
            span.start = 5  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [((0, 10), (5, 15), True), ((0, 10), (10, 20), False), ((0, 5), (6, 9), False)],
    )
    def test_overlap_detection(
        self, left: tuple[int, int], right: tuple[int, int], expected: bool
    ) -> None:
        a = Span.over("d1", TEXT, *left)
        b = Span.over("d1", TEXT, *right)
        assert a.overlaps(b) is expected

    def test_spans_in_different_documents_never_overlap(self) -> None:
        a = Span.over("d1", TEXT, 0, 10)
        b = Span.over("d2", TEXT, 0, 10)
        assert a.overlaps(b) is False


class TestClaim:
    def test_a_claim_must_cite_something(self) -> None:
        """A claim with no provenance is exactly what this system exists to prevent."""
        with pytest.raises(ValidationError, match="at least one span"):
            Claim(text="The contract is fair.", spans=())

    def test_accepts_a_claim_with_evidence(self) -> None:
        claim = Claim(text="Payment is due in 30 days.", spans=(Span.over("d1", TEXT, 0, 20),))
        assert len(claim.spans) == 1


class TestSeverity:
    def test_ordering_is_ascending_by_seriousness(self) -> None:
        levels = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        ranks = [severity_rank(level) for level in levels]
        assert ranks == sorted(ranks)

    def test_every_level_has_a_rank(self) -> None:
        for level in Severity:
            assert isinstance(severity_rank(level), int)
