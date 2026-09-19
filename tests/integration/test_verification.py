"""The verification gate end to end.

These are the tests that pin the product's central claim: nothing reaches a user
that has not been checked against a passage which provably exists in their
document.
"""

from __future__ import annotations

import pytest

from adhikar.domain import Claim, Document, Span, Verdict
from adhikar.llm.base import ModelProvider
from adhikar.verify.anchor import anchor_quotes
from adhikar.verify.gate import VerificationGate, lexical_entailment


class TestQuoteAnchoring:
    def test_an_exact_quote_resolves(self, document: Document) -> None:
        quote = "The Client shall pay each invoice within thirty (30) days of receipt."
        result = anchor_quotes([quote], document.id, document.text)

        assert result.ok
        assert result.spans[0].resolve(document.text) == quote

    def test_a_quote_spanning_a_line_break_resolves(self, document: Document) -> None:
        """Extraction wraps lines unpredictably; a real quote must still anchor."""
        quote = (
            "The Provider shall indemnify the Client against any and all claims "
            "arising out of this agreement"
        )
        result = anchor_quotes([quote], document.id, document.text)
        assert result.ok

    def test_a_fabricated_quote_is_rejected(self, document: Document) -> None:
        """The check that makes citation hallucination detectable in code."""
        result = anchor_quotes(
            ["The Client shall pay each invoice within ninety (90) days of receipt."],
            document.id,
            document.text,
        )
        assert not result.ok
        assert "does not appear" in result.failures[0].reason

    def test_a_plausible_paraphrase_is_rejected(self, document: Document) -> None:
        """A quote that differs in wording is not a quote."""
        result = anchor_quotes(
            ["The Client must settle invoices within one month of receiving them."],
            document.id,
            document.text,
        )
        assert not result.ok

    def test_a_quote_too_short_to_identify_a_passage_is_rejected(self, document: Document) -> None:
        assert not anchor_quotes(["the Client"], document.id, document.text).ok

    def test_regex_metacharacters_in_a_quote_are_literal(self, document: Document) -> None:
        """Contracts are full of parentheses; they must not alter the search."""
        result = anchor_quotes(["within thirty (30) days of receipt"], document.id, document.text)
        assert result.ok


class TestLexicalEntailment:
    def test_a_restatement_is_supported(self) -> None:
        judgement = lexical_entailment(
            "The Client must pay each invoice within thirty days of receipt.",
            "The Client shall pay each invoice within thirty (30) days of receipt.",
        )
        assert judgement.verdict is Verdict.SUPPORTED

    def test_a_changed_number_is_not_fully_supported(self) -> None:
        judgement = lexical_entailment(
            "The Client must pay each invoice within sixty days.",
            "The Client shall pay each invoice within thirty (30) days of receipt.",
        )
        assert judgement.verdict is not Verdict.SUPPORTED

    def test_negation_mismatch_is_contradiction(self) -> None:
        """High word overlap with inverted meaning is the dangerous case."""
        judgement = lexical_entailment(
            "The Provider shall not be liable for consequential damages.",
            "The Provider shall be liable for consequential damages.",
        )
        assert judgement.verdict is Verdict.CONTRADICTED

    def test_unrelated_evidence_is_unsupported(self) -> None:
        judgement = lexical_entailment(
            "The agreement grants exclusive worldwide distribution rights.",
            "The Client shall pay each invoice within thirty (30) days of receipt.",
        )
        assert judgement.verdict is Verdict.UNSUPPORTED

    def test_confidence_never_reaches_certainty(self) -> None:
        """A lexical check cannot recognise paraphrase and must not claim to."""
        judgement = lexical_entailment("identical text here", "identical text here")
        assert judgement.confidence < 1.0


class TestVerificationGate:
    @pytest.fixture
    def gate(self, provider: ModelProvider) -> VerificationGate:
        return VerificationGate(provider, threshold=0.7)

    async def test_a_supported_claim_is_admitted(
        self, gate: VerificationGate, document: Document
    ) -> None:
        quote = "The Client shall pay each invoice within thirty (30) days of receipt."
        start = document.text.index(quote)
        claim = Claim(
            text=quote,
            spans=(Span.over(document.id, document.text, start, start + len(quote)),),
        )
        result = await gate.verify("When is payment due?", [claim], document)

        assert len(result.answer.admitted) == 1
        assert result.answer.support_rate == 1.0

    async def test_a_claim_unsupported_by_its_own_evidence_is_withheld(
        self, gate: VerificationGate, document: Document
    ) -> None:
        """The claim cites a real passage that does not establish it.

        This is the failure a citation-only system cannot catch: the link is
        valid, the reference exists, and the statement is still wrong.
        """
        quote = "The Client shall pay each invoice within thirty (30) days of receipt."
        start = document.text.index(quote)
        claim = Claim(
            text="The Client may terminate this agreement at any time without notice.",
            spans=(Span.over(document.id, document.text, start, start + len(quote)),),
        )
        result = await gate.verify("Can I terminate?", [claim], document)

        assert not result.answer.admitted
        assert len(result.answer.withheld) == 1

    async def test_a_claim_citing_a_tampered_span_fails_integrity(
        self, gate: VerificationGate, document: Document
    ) -> None:
        """Deterministic check: no model opinion involved, and no tolerance."""
        quote = "The Client shall pay each invoice within thirty (30) days of receipt."
        start = document.text.index(quote)
        span = Span.over(document.id, document.text, start, start + len(quote))

        altered = document.model_copy(
            update={"text": document.text.replace("thirty (30)", "ninety (90)")}
        )
        claim = Claim(text="Payment is due in thirty days.", spans=(span,))
        result = await gate.verify("When is payment due?", [claim], altered)

        assert result.integrity_failures
        assert not result.answer.admitted

    async def test_a_span_from_another_document_is_refused(
        self, gate: VerificationGate, document: Document
    ) -> None:
        foreign = Span.over("other-document", document.text, 0, 30)
        claim = Claim(text="Something about another file.", spans=(foreign,))
        result = await gate.verify("?", [claim], document)

        assert result.integrity_failures
        assert "different document" in result.integrity_failures[0].detail

    async def test_withheld_claims_are_reported_not_silently_dropped(
        self, gate: VerificationGate, document: Document
    ) -> None:
        """A filter you cannot see is indistinguishable from a model that stayed quiet."""
        quote = "The Client shall pay each invoice within thirty (30) days of receipt."
        start = document.text.index(quote)
        span = Span.over(document.id, document.text, start, start + len(quote))
        claims = [
            Claim(text=quote, spans=(span,)),
            Claim(text="The Provider owns all customer data in perpetuity.", spans=(span,)),
        ]
        result = await gate.verify("?", claims, document)

        assert len(result.answer.admitted) == 1
        assert len(result.answer.withheld) == 1
        assert result.answer.support_rate == 0.5

    async def test_no_admissible_claims_produces_an_abstention(
        self, gate: VerificationGate, document: Document
    ) -> None:
        result = await gate.verify("?", [], document)
        assert result.answer.abstained
        assert result.answer.abstain_reason
