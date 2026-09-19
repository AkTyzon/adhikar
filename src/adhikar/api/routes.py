"""JSON API.

Response models are explicit rather than serialising domain objects directly.
Domain objects carry things the wire should not -- the redaction vault, raw
document text -- and a schema that is defined separately cannot leak them by
accident when a field is added upstream.

Every response that contains a statement also contains its evidence and what was
withheld. That is not a debugging affordance; it is the product.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from adhikar.api.app import enforce_rate_limit, get_app_settings, get_documents, get_pipeline
from adhikar.config import Settings
from adhikar.domain import Document, Finding, VerifiedAnswer
from adhikar.errors import IngestError
from adhikar.pipeline import IngestOutcome, Pipeline, lawyer_questions
from adhikar.security.audit import verify_chain

router = APIRouter(prefix="/api", tags=["analysis"])


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


class SpanOut(BaseModel):
    start: int
    end: int
    text: str


class EvidenceMixin(BaseModel):
    @staticmethod
    def spans_out(spans: Any, document: Document) -> list[SpanOut]:
        return [SpanOut(start=s.start, end=s.end, text=s.resolve(document.text)) for s in spans]


class InjectionSignalOut(BaseModel):
    id: str
    category: str
    explanation: str
    evidence: str
    start: int
    end: int


class UploadOut(BaseModel):
    document_id: str
    filename: str
    clause_count: int
    page_count: int | None
    character_count: int
    injection_score: float = Field(
        description="0 means nothing suspicious; 1 means near-certain embedded instructions."
    )
    injection_signals: list[InjectionSignalOut]
    redaction_counts: dict[str, int]
    audit_run_id: str


class FindingOut(BaseModel):
    id: str
    severity: str
    title: str
    plain_language: str
    why_it_matters: str
    clause_type: str
    evidence: list[SpanOut]
    expected_baseline: str | None = None
    baseline_direction: str | None = None
    questions_for_lawyer: list[str] = Field(default_factory=list)


class ObligationOut(BaseModel):
    obligor: str
    action: str
    trigger: str
    trigger_event: str | None
    period_days: int | None
    due_date: str | None
    condition: str | None
    evidence: list[SpanOut]


class AnalysisOut(BaseModel):
    document_id: str
    risk_score: float
    severity_counts: dict[str, int]
    findings: list[FindingOut]
    obligations: list[ObligationOut]
    unresolved_anchors: list[str] = Field(
        description="Events whose dates the document never states, so deadlines "
        "depending on them were not computed rather than guessed."
    )
    contradictions: list[dict[str, Any]]
    missing_clause_types: list[str]
    questions_for_lawyer: list[dict[str, str]]
    audit_run_id: str


class ClaimOut(BaseModel):
    text: str
    verdict: str
    confidence: float
    reason: str
    evidence: list[SpanOut]


class AnswerOut(BaseModel):
    question: str
    intent: str
    mode: str
    abstained: bool
    notice: str | None
    #: Statements that passed both checks.
    answer: list[ClaimOut]
    #: Statements that did not, and why. Deliberately part of the response: a
    #: system that silently drops output cannot be distinguished from one that
    #: never produced it.
    withheld: list[ClaimOut]
    support_rate: float
    audit_run_id: str


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.post("/documents", response_model=UploadOut, status_code=201)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File(description="PDF, DOCX or plain text.")],
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
    documents: Annotated[Any, Depends(get_documents)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> UploadOut:
    """Ingest a document: extract, scan for embedded instructions, redact, segment.

    A document scoring above the block threshold is quarantined and never
    analysed, returning 422.
    """
    enforce_rate_limit(request, upload=True)

    # Read with a hard ceiling rather than trusting Content-Length, which is
    # client-supplied. An oversized body is refused before it is buffered whole.
    data = await _read_limited(file, settings.max_upload_bytes)
    outcome = pipeline.ingest(data, _safe_filename(file.filename))
    await documents.put(outcome)
    await request.app.state.audit.append(outcome.audit)

    return _upload_out(outcome)


@router.get("/documents/{document_id}/analysis", response_model=AnalysisOut)
async def analyse_document(
    request: Request,
    document_id: str,
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
    documents: Annotated[Any, Depends(get_documents)],
) -> AnalysisOut:
    """Risks, obligations and contradictions. Runs entirely without a model."""
    enforce_rate_limit(request)
    outcome: IngestOutcome = await documents.get(document_id)
    document = outcome.document
    analysis = pipeline.analyse(document)
    await request.app.state.audit.append(analysis.audit)

    return AnalysisOut(
        document_id=document_id,
        risk_score=analysis.risk.score,
        severity_counts=analysis.risk.counts(),
        findings=[_finding_out(f, document) for f in analysis.findings],
        obligations=[
            ObligationOut(
                obligor=o.obligor,
                action=o.action,
                trigger=o.trigger_kind.value,
                trigger_event=o.trigger_event,
                period_days=o.offset_days,
                due_date=o.computed_due.isoformat() if o.computed_due else None,
                condition=o.condition,
                evidence=EvidenceMixin.spans_out(o.spans, document),
            )
            for o in analysis.obligations.obligations
        ],
        unresolved_anchors=list(analysis.obligations.unresolved_anchors),
        contradictions=[
            {
                "kind": c.kind,
                "explanation": c.explanation,
                "left": c.left.action,
                "right": c.right.action,
            }
            for c in analysis.contradictions
        ],
        missing_clause_types=list(analysis.risk.missing_clause_types),
        questions_for_lawyer=[
            {"question": q, "prompted_by": why} for q, why in lawyer_questions(analysis.findings)
        ],
        audit_run_id=analysis.audit.run_id,
    )


@router.post("/documents/{document_id}/questions", response_model=AnswerOut)
async def ask_question(
    request: Request,
    document_id: str,
    question: Annotated[str, Form(min_length=3, max_length=500)],
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
    documents: Annotated[Any, Depends(get_documents)],
) -> AnswerOut:
    """Answer a question, returning only statements that passed verification."""
    enforce_rate_limit(request)
    outcome: IngestOutcome = await documents.get(document_id)
    document = outcome.document

    result = await pipeline.ask(document, question)
    await request.app.state.audit.append(result.audit)
    return _answer_out(result.answer, result.scope, document, result.audit.run_id)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    request: Request,
    document_id: str,
    documents: Annotated[Any, Depends(get_documents)],
) -> None:
    """Drop a document from memory immediately, without waiting for its TTL."""
    enforce_rate_limit(request)
    await documents.delete(document_id)


@router.get("/audit")
async def audit_log(request: Request, limit: int = 25) -> dict[str, Any]:
    """The audit trail, with a live integrity check of its hash chain."""
    enforce_rate_limit(request)
    pipeline: Pipeline = request.app.state.pipeline
    records = pipeline.audit_chain.records()
    verification = verify_chain(records)
    return {
        "chain_valid": verification.valid,
        "records_checked": verification.checked,
        "head": pipeline.audit_chain.head,
        "records": [
            {
                "run_id": r.run_id,
                "operation": r.operation,
                "created_at": r.created_at.isoformat(),
                "engine": r.engine,
                "model": r.model,
                "document_sha256": r.document_sha256[:16],
                "scope_mode": r.scope_mode,
                "injection_score": r.injection_score,
                "claims_admitted": r.claims_admitted,
                "claims_withheld": r.claims_withheld,
                "duration_ms": r.total_duration_ms,
                "cached_input_tokens": r.cache_hit_tokens,
                "prompt_versions": dict(r.prompt_versions),
                "record_hash": r.record_hash[:16],
            }
            for r in records[-limit:][::-1]
        ],
    }


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Liveness and configuration summary. No secrets."""
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "engine": settings.resolved_engine.value,
        "model": request.app.state.provider.model_id,
        "clause_types": len(request.app.state.pipeline.catalog),
        "documents_in_memory": request.app.state.documents.size,
        "pii_redaction": settings.redact_pii,
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Read an upload, refusing anything over the limit without buffering it all."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise IngestError(f"upload exceeds the {limit}-byte limit")
        chunks.append(chunk)
    if not chunks:
        raise IngestError("the uploaded file is empty")
    return b"".join(chunks)


def _safe_filename(name: str | None) -> str:
    """Strip any path component from a client-supplied filename.

    The name is only ever displayed, never used to open a file -- but it is
    attacker-controlled and ends up in a template, so it is sanitised at the
    boundary rather than relying on every later use being careful.
    """
    if not name:
        return "document"
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*')
    return cleaned[:120] or "document"


def _upload_out(outcome: IngestOutcome) -> UploadOut:
    document = outcome.document
    return UploadOut(
        document_id=document.id,
        filename=document.filename,
        clause_count=len(document.clauses),
        page_count=document.page_count,
        character_count=len(document.text),
        injection_score=outcome.injection.score,
        injection_signals=[
            InjectionSignalOut(
                id=s.id,
                category=s.category,
                explanation=s.explanation,
                evidence=s.evidence[:200],
                start=s.start,
                end=s.end,
            )
            for s in outcome.injection.top_signals(10)
        ],
        redaction_counts=outcome.redaction.counts_by_type(),
        audit_run_id=outcome.audit.run_id,
    )


def _finding_out(finding: Finding, document: Document) -> FindingOut:
    deviation = finding.baseline_deviation
    return FindingOut(
        id=finding.id,
        severity=finding.severity.value,
        title=finding.title,
        plain_language=finding.plain_language,
        why_it_matters=finding.why_it_matters,
        clause_type=finding.clause_type,
        evidence=EvidenceMixin.spans_out(finding.spans, document),
        expected_baseline=deviation.expected if deviation else None,
        baseline_direction=deviation.direction.value if deviation else None,
        questions_for_lawyer=list(finding.questions_for_lawyer),
    )


def _answer_out(answer: VerifiedAnswer, scope: Any, document: Document, run_id: str) -> AnswerOut:
    def claim_out(verified: Any) -> ClaimOut:
        return ClaimOut(
            text=verified.claim.text,
            verdict=verified.verdict.value,
            confidence=verified.confidence,
            reason=verified.reason,
            evidence=EvidenceMixin.spans_out(verified.claim.spans, document),
        )

    return AnswerOut(
        question=answer.question,
        intent=scope.intent.value,
        mode=scope.mode.value,
        abstained=answer.abstained,
        notice=answer.abstain_reason or scope.boundary_notice,
        answer=[claim_out(c) for c in answer.admitted],
        withheld=[claim_out(c) for c in answer.withheld],
        support_rate=round(answer.support_rate, 4),
        audit_run_id=run_id,
    )
