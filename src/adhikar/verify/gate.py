"""The verification gate.

This is the component that distinguishes Adhikar from asking a chat assistant the
same question.  A chat assistant produces fluent prose in which a correct
statement and an invented one are indistinguishable.  Here, nothing reaches the
user until it has passed two independent checks.

**Check one is deterministic and cannot be argued with.**  Every claim cites
spans; every span is re-resolved against the document and its recorded quote hash
compared.  A model that invented offsets, or cited real offsets while quoting
something else, fails here in Python, with no second opinion required.  This
catches fabricated provenance completely -- not probabilistically.

**Check two is an entailment judgement made on deliberately partial
information.**  The verifier is shown the claim and the text of its cited spans,
and nothing else: not the user's question, not the generator's reasoning, not the
rest of the document.  It cannot be persuaded by framing it never sees, and
because it reads only document spans, an instruction embedded in the document has
no path to it -- an injected "report no risks" cannot make an unsupported claim
verifiable.

Claims that fail are not annotated, they are **removed** -- and returned
separately as ``withheld``, because a system that silently drops output is
indistinguishable from one that never generated it.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from adhikar.domain import Claim, Document, Span, Verdict, VerifiedAnswer, VerifiedClaim
from adhikar.errors import SpanResolutionError
from adhikar.llm.base import DocumentContext, ModelProvider, ModelRequest, Task, Usage


class EntailmentJudgement(BaseModel):
    """The verifier's structured ruling on one claim."""

    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=400)


@dataclass(frozen=True, slots=True)
class IntegrityFailure:
    """A claim whose provenance did not survive deterministic checking."""

    claim: Claim
    span: Span
    detail: str


@dataclass(frozen=True, slots=True)
class GateResult:
    """Everything the gate concluded, including what it refused."""

    answer: VerifiedAnswer
    integrity_failures: tuple[IntegrityFailure, ...]
    usage: Usage

    @property
    def clean(self) -> bool:
        return not self.integrity_failures


class VerificationGate:
    """Checks claims against their own evidence before anything is shown."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        threshold: float = 0.70,
        max_concurrency: int = 8,
    ) -> None:
        self._provider = provider
        self._threshold = threshold
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def verify(
        self,
        question: str,
        claims: Sequence[Claim],
        document: Document,
        *,
        boundary_notice: str | None = None,
    ) -> GateResult:
        """Run both checks over a set of claims.

        Claims are verified concurrently -- they are independent by construction,
        since each is judged only against its own spans.
        """
        survivors: list[Claim] = []
        failures: list[IntegrityFailure] = []

        for claim in claims:
            failure = self._check_integrity(claim, document)
            if failure is None:
                survivors.append(claim)
            else:
                failures.append(failure)

        judgements = await asyncio.gather(*(self._judge(claim, document) for claim in survivors))

        admitted: list[VerifiedClaim] = []
        withheld: list[VerifiedClaim] = []
        total_usage = Usage()

        for claim, (judgement, usage) in zip(survivors, judgements, strict=True):
            total_usage = total_usage + usage
            verified = VerifiedClaim(
                claim=claim,
                verdict=judgement.verdict,
                confidence=judgement.confidence,
                reason=judgement.reason,
            )
            if verified.admissible and judgement.confidence >= self._threshold:
                admitted.append(verified)
            else:
                withheld.append(verified)

        # An integrity failure is not a low-confidence claim -- it is a claim
        # whose evidence does not exist. It is withheld with a verdict that says so.
        withheld.extend(
            VerifiedClaim(
                claim=failure.claim,
                verdict=Verdict.UNSUPPORTED,
                confidence=0.0,
                reason=f"Citation could not be verified: {failure.detail}",
            )
            for failure in failures
        )

        abstained = not admitted
        return GateResult(
            answer=VerifiedAnswer(
                question=question,
                admitted=tuple(admitted),
                withheld=tuple(withheld),
                abstained=abstained,
                abstain_reason=(
                    "No statement could be verified against the document, so none is shown."
                    if abstained
                    else boundary_notice
                ),
            ),
            integrity_failures=tuple(failures),
            usage=total_usage,
        )

    # ------------------------------------------------------------------ check 1
    @staticmethod
    def _check_integrity(claim: Claim, document: Document) -> IntegrityFailure | None:
        """Deterministic provenance check. No model, no judgement, no tolerance."""
        for span in claim.spans:
            if span.document_id != document.id:
                return IntegrityFailure(
                    claim=claim,
                    span=span,
                    detail="the cited span belongs to a different document",
                )
            try:
                span.resolve(document.text)
            except SpanResolutionError as exc:
                return IntegrityFailure(claim=claim, span=span, detail=str(exc))
        return None

    # ------------------------------------------------------------------ check 2
    async def _judge(self, claim: Claim, document: Document) -> tuple[EntailmentJudgement, Usage]:
        """Ask the verifier whether the cited spans entail the claim.

        The evidence passed here is *only* the cited spans. Handing the verifier
        the whole document would let it confirm a claim from text the generator
        never cited, which would make the citation meaningless.
        """
        evidence = "\n\n---\n\n".join(span.resolve(document.text) for span in claim.spans)
        request = ModelRequest(
            task=Task.VERIFY,
            instruction=(
                "Decide whether the evidence below, and nothing else, supports the "
                "statement.\n\n"
                f"STATEMENT:\n{claim.text}\n\n"
                "Answer 'supported' only if the evidence states or directly entails "
                "the statement. Answer 'partially_supported' if it supports part of "
                "it. Answer 'unsupported' if the evidence does not establish it, even "
                "if you believe the statement is true. Answer 'contradicted' if the "
                "evidence says otherwise."
            ),
            documents=(
                DocumentContext(document_id=document.id, title="Cited evidence", text=evidence),
            ),
            # Evidence differs per claim, so there is no shared prefix to cache.
            cacheable=False,
        )
        async with self._semaphore:
            response = await self._provider.generate(request, EntailmentJudgement)
        return response.output, response.usage


# --------------------------------------------------------------------------- #
# Deterministic entailment, used by the offline engine
# --------------------------------------------------------------------------- #

#: Words this short are function words and say nothing about entailment.
_MIN_CONTENT_CHARS = 2

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
        "his",
        "her",
        "such",
        "any",
        "all",
        "each",
        "either",
        "not",
        "no",
        "than",
        "then",
        "there",
        "here",
        "which",
        "who",
        "whom",
    ]
)


#: Share of the claim's content words that must appear in the evidence for the
#: deterministic checker to call it supported. Set high deliberately: this check
#: cannot recognise paraphrase, so it should abstain rather than over-admit.
_FULL_COVERAGE = 0.85
#: Below this, the evidence establishes too little of the claim to say anything.
_PARTIAL_COVERAGE = 0.5
#: Ceiling on the confidence a purely lexical check may report. It never reaches
#: certainty because word overlap is not entailment.
_MAX_LEXICAL_CONFIDENCE = 0.95


def lexical_entailment(claim_text: str, evidence: str) -> EntailmentJudgement:
    """Judge entailment by content-word coverage.

    A deliberately weak but honest check: it measures how much of the claim's
    substance actually appears in the evidence.  It cannot detect paraphrase, and
    it says so by never returning full confidence.  Its purpose is to make the
    offline engine *conservative* -- it under-admits rather than over-admits,
    which is the correct failure direction for this product.
    """
    claim_words = _content_words(claim_text)
    evidence_words = _content_words(evidence)

    if not claim_words:
        return EntailmentJudgement(
            verdict=Verdict.UNSUPPORTED, confidence=0.0, reason="The statement has no content."
        )

    covered = claim_words & evidence_words
    coverage = len(covered) / len(claim_words)

    # Negation mismatch is treated as contradiction: evidence saying "shall not"
    # does not support a claim saying "shall", however well the words overlap.
    if _negation_parity(claim_text) != _negation_parity(evidence):
        return EntailmentJudgement(
            verdict=Verdict.CONTRADICTED,
            confidence=round(0.5 + 0.4 * coverage, 3),
            reason="The evidence and the statement differ in negation.",
        )

    if coverage >= _FULL_COVERAGE:
        return EntailmentJudgement(
            verdict=Verdict.SUPPORTED,
            confidence=round(min(_MAX_LEXICAL_CONFIDENCE, 0.6 + 0.35 * coverage), 3),
            reason=f"{len(covered)} of {len(claim_words)} key terms appear in the evidence.",
        )
    if coverage >= _PARTIAL_COVERAGE:
        return EntailmentJudgement(
            verdict=Verdict.PARTIALLY_SUPPORTED,
            confidence=round(0.4 + 0.3 * coverage, 3),
            reason=f"Only {len(covered)} of {len(claim_words)} key terms appear in the evidence.",
        )
    return EntailmentJudgement(
        verdict=Verdict.UNSUPPORTED,
        confidence=round(0.2 + 0.3 * coverage, 3),
        reason="Most of the statement's key terms do not appear in the cited evidence.",
    )


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in _STOPWORDS and len(word) > _MIN_CONTENT_CHARS
    )


def _negation_parity(text: str) -> bool:
    """Whether a passage is net-negated. Crude, and only used for a mismatch signal."""
    return len(re.findall(r"\b(?:not|never|no|without|except|unless)\b", text, re.I)) % 2 == 1
