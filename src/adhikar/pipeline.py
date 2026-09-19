"""Analysis orchestration.

Every user-facing operation is a sequence of stages here, and every sequence
produces an audit record.  Keeping the order in one file means the security
properties are *readable*: you can see that redaction happens before any model
call, that quarantine happens before analysis, and that nothing reaches a
response without passing the verification gate.

Stage order for ingestion, which is the part that matters most:

1. Extract text and concealment artifacts from the bytes.
2. Scan for embedded instructions; quarantine above the block threshold.
3. Strip invisible characters -- downstream stages read sanitised text.
4. Redact PII, keeping an offset map so spans stay meaningful.
5. Segment into clauses.

Redaction sits *after* segmentation would be easier, and is wrong: the whole
point is that no personal data reaches a model, and the model is called with
document text.  So redaction happens first and every span the model produces is
mapped back through the offset map before the user sees it.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from adhikar.analysis import compare as compare_module
from adhikar.analysis import obligations as obligations_module
from adhikar.analysis import risk as risk_module
from adhikar.analysis.catalog import ClauseCatalog, get_catalog
from adhikar.analysis.schemas import AnswerDraft
from adhikar.config import Settings
from adhikar.domain import Claim, Contradiction, Document, Finding, VerifiedAnswer
from adhikar.errors import DocumentQuarantinedError
from adhikar.ingest.extract import extract as extract_document
from adhikar.ingest.segment import segment
from adhikar.llm.base import DocumentContext, ModelProvider, ModelRequest, Task, Usage
from adhikar.llm.prompts import versions as prompt_versions
from adhikar.security.audit import AuditChain, AuditRecord, StageTiming, start_record
from adhikar.security.injection import InjectionReport, InjectionScanner
from adhikar.security.redaction import RedactionResult, Redactor
from adhikar.security.upl import ResponseMode, ScopeDecision, ScopeGate
from adhikar.verify.anchor import anchor_quotes
from adhikar.verify.gate import GateResult, VerificationGate


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """A document that passed ingestion, with everything learned on the way in."""

    document: Document
    injection: InjectionReport
    redaction: RedactionResult
    audit: AuditRecord
    #: The text as uploaded, before redaction. Held in memory for the session only
    #: so the user can be shown their own document; never sent to a model.
    original_text: str

    @property
    def warned(self) -> bool:
        return bool(self.injection.signals)


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """The result of a full document analysis."""

    document_id: str
    risk: risk_module.RiskReport
    obligations: obligations_module.ObligationSet
    contradictions: tuple[Contradiction, ...]
    audit: AuditRecord

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self.risk.by_severity()


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    """An answered question, with what was withheld and why."""

    answer: VerifiedAnswer
    scope: ScopeDecision
    audit: AuditRecord
    usage: Usage = field(default_factory=Usage)


class _Timer:
    """Collects per-stage timings for the audit record."""

    def __init__(self) -> None:
        self.timings: list[StageTiming] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        box: dict[str, Any] = {}
        try:
            yield box
        finally:
            self.timings.append(
                StageTiming(
                    stage=name,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    input_tokens=box.get("input_tokens"),
                    output_tokens=box.get("output_tokens"),
                    cached_input_tokens=box.get("cached_input_tokens"),
                )
            )


class Pipeline:
    """The orchestrator. One instance per process; safe for concurrent use."""

    def __init__(
        self,
        settings: Settings,
        provider: ModelProvider,
        *,
        audit_chain: AuditChain | None = None,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._audit = audit_chain or AuditChain()
        knowledge = settings.knowledge_path
        self._catalog: ClauseCatalog = get_catalog(knowledge / "clauses.yaml")
        self._scanner = InjectionScanner.from_catalogue(knowledge / "injection_signatures.yaml")
        self._redactor = Redactor.from_catalogue(knowledge / "pii_patterns.yaml")
        self._scope = ScopeGate.from_catalogue(knowledge / "upl_policy.yaml")
        self._gate = VerificationGate(provider, threshold=settings.verification_threshold)

    @property
    def audit_chain(self) -> AuditChain:
        return self._audit

    @property
    def catalog(self) -> ClauseCatalog:
        return self._catalog

    # ------------------------------------------------------------------ ingest
    def ingest(self, data: bytes, filename: str) -> IngestOutcome:
        """Take raw bytes to an analysable document, or refuse them.

        Raises:
            IngestError: the document could not be read or exceeded a limit.
            DocumentQuarantinedError: embedded-instruction score exceeded the
                block threshold.
        """
        timer = _Timer()
        digest = hashlib.sha256(data).hexdigest()
        document_id = uuid.uuid4().hex[:16]

        with timer.stage("extract"):
            extraction = extract_document(data, self._settings, filename)

        with timer.stage("injection_scan"):
            report = self._scanner.scan(extraction.text, extraction.artifacts)

        if report.score >= self._settings.injection_block_threshold:
            record = self._seal(
                start_record(
                    "ingest.quarantine",
                    document_sha256=digest,
                    engine=self._provider.name,
                    model=self._provider.model_id,
                    injection_score=report.score,
                    injection_signal_ids=tuple(s.id for s in report.top_signals(10)),
                    timings=tuple(timer.timings),
                )
            )
            raise DocumentQuarantinedError(
                f"document scored {report.score:.2f} for embedded instructions",
                context={"run_id": record.run_id, "score": report.score},
            )

        # Downstream stages read the sanitised text: invisible characters are
        # removed so a model never sees a payload a human could not.
        clean_text = report.sanitised_text or extraction.text

        with timer.stage("redaction"):
            redaction = (
                self._redactor.redact(clean_text)
                if self._settings.redact_pii
                else self._redactor.redact("")
            )
            analysis_text = redaction.text if self._settings.redact_pii else clean_text

        with timer.stage("segmentation"):
            clauses = segment(
                analysis_text, document_id, self._settings.knowledge_path / "segmentation.yaml"
            )

        document = Document(
            id=document_id,
            filename=filename,
            media_type=extraction.media_type,
            content_sha256=digest,
            text=analysis_text,
            clauses=clauses,
            page_count=extraction.page_count,
            ingested_at=datetime.now(UTC),
        )

        record = self._seal(
            start_record(
                "ingest",
                document_sha256=digest,
                engine=self._provider.name,
                model=self._provider.model_id,
                injection_score=report.score,
                injection_signal_ids=tuple(s.id for s in report.top_signals(10)),
                redaction_counts=redaction.counts_by_type(),
                timings=tuple(timer.timings),
            )
        )
        return IngestOutcome(
            document=document,
            injection=report,
            redaction=redaction,
            audit=record,
            original_text=clean_text,
        )

    # ------------------------------------------------------------------ analyse
    def analyse(self, document: Document) -> AnalysisOutcome:
        """Run risk, obligation and contradiction analysis. No model required."""
        timer = _Timer()

        with timer.stage("risk"):
            risk = risk_module.analyse(document, self._catalog)

        with timer.stage("obligations"):
            extracted = obligations_module.extract(document)

        with timer.stage("contradictions"):
            contradictions = obligations_module.find_contradictions(
                extracted.obligations, (document,)
            )

        record = self._seal(
            start_record(
                "analyse",
                document_sha256=document.content_sha256,
                engine=self._provider.name,
                model=self._provider.model_id,
                timings=tuple(timer.timings),
            )
        )
        return AnalysisOutcome(
            document_id=document.id,
            risk=risk,
            obligations=extracted,
            contradictions=contradictions,
            audit=record,
        )

    # ------------------------------------------------------------------ ask
    async def ask(self, document: Document, question: str) -> QuestionOutcome:
        """Answer a question about a document, verifying before returning.

        The scope gate runs first and can end the request without any model call
        at all -- a question asking for a prediction is refused on the way in, not
        answered and then filtered.
        """
        timer = _Timer()
        decision = self._scope.classify(question)

        if decision.mode is ResponseMode.REFER_OUT:
            record = self._seal(
                start_record(
                    "ask.refer_out",
                    document_sha256=document.content_sha256,
                    engine=self._provider.name,
                    model=self._provider.model_id,
                    scope_intent=decision.intent.value,
                    scope_mode=decision.mode.value,
                    timings=tuple(timer.timings),
                )
            )
            return QuestionOutcome(
                answer=VerifiedAnswer(
                    question=question,
                    admitted=(),
                    withheld=(),
                    abstained=True,
                    abstain_reason=decision.boundary_notice,
                ),
                scope=decision,
                audit=record,
            )

        with timer.stage("generate") as box:
            draft, usage = await self._draft_answer(document, question, decision)
            box.update(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
            )

        with timer.stage("anchor"):
            claims, anchor_failures = self._anchor(draft, document)

        with timer.stage("verify") as box:
            result: GateResult = await self._gate.verify(
                question, claims, document, boundary_notice=decision.boundary_notice
            )
            box.update(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_input_tokens=result.usage.cached_input_tokens,
            )

        total = usage + result.usage
        record = self._seal(
            start_record(
                "ask",
                document_sha256=document.content_sha256,
                engine=self._provider.name,
                model=self._provider.model_id,
                prompt_versions=prompt_versions("system", "answer", "verify"),
                scope_intent=decision.intent.value,
                scope_mode=decision.mode.value,
                claims_admitted=len(result.answer.admitted),
                claims_withheld=len(result.answer.withheld),
                span_integrity_failures=len(result.integrity_failures) + anchor_failures,
                timings=tuple(timer.timings),
            )
        )
        return QuestionOutcome(answer=result.answer, scope=decision, audit=record, usage=total)

    async def _draft_answer(
        self, document: Document, question: str, decision: ScopeDecision
    ) -> tuple[AnswerDraft, Usage]:
        guidance = decision.policy.description
        request = ModelRequest(
            task=Task.ANSWER,
            instruction=question,
            documents=(
                DocumentContext(
                    document_id=document.id, title=document.filename, text=document.text
                ),
            ),
            params={"question": question, "mode_guidance": guidance},
            cacheable=True,
        )
        response = await self._provider.generate(request, AnswerDraft)
        return response.output, response.usage

    def _anchor(self, draft: AnswerDraft, document: Document) -> tuple[list[Claim], int]:
        """Turn quoted evidence into verified spans, dropping what does not resolve."""
        claims: list[Claim] = []
        failures = 0
        for item in draft.claims:
            resolved = anchor_quotes(item.quotes, document.id, document.text)
            failures += len(resolved.failures)
            if resolved.spans:
                claims.append(Claim(text=item.text, spans=resolved.spans))
        return claims, failures

    # ------------------------------------------------------------------ compare
    def compare(self, left: Document, right: Document) -> compare_module.ComparisonResult:
        """Align two documents clause by clause."""
        typed_left = left.model_copy(
            update={"clauses": risk_module.type_clauses(left.clauses, self._catalog)}
        )
        typed_right = right.model_copy(
            update={"clauses": risk_module.type_clauses(right.clauses, self._catalog)}
        )
        return compare_module.compare(typed_left, typed_right)

    # ------------------------------------------------------------------ helpers
    def _seal(self, record: AuditRecord) -> AuditRecord:
        return self._audit.append(record)


def lawyer_questions(
    findings: Sequence[Finding], *, limit: int = 12
) -> tuple[tuple[str, str], ...]:
    """Curated questions for the findings in a document, most severe first.

    Drawn from the clause catalogue rather than generated, so the questions are
    ones a practitioner wrote. Deduplicated, because several findings legitimately
    raise the same question and a repeated item wastes a consultation.
    """
    from adhikar.domain import severity_rank

    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for finding in sorted(findings, key=lambda f: -severity_rank(f.severity)):
        for question in finding.questions_for_lawyer:
            key = question.casefold()
            if key in seen:
                continue
            seen.add(key)
            pairs.append((question, finding.title))
            if len(pairs) >= limit:
                return tuple(pairs)
    return tuple(pairs)
