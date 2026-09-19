"""Server-rendered pages.

Progressive enhancement is the rule: every action works as a plain form POST
followed by a full page render.  JavaScript improves the experience -- it keeps
focus in place and updates a live region -- but nothing depends on it.  That is
partly an accessibility decision and partly a reliability one: a legal tool that
breaks when a script fails to load is a legal tool that breaks.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from adhikar.analysis.glossary import get_glossary
from adhikar.api.app import enforce_rate_limit, get_app_settings, get_documents, get_pipeline
from adhikar.api.routes import _read_limited, _safe_filename
from adhikar.config import Settings
from adhikar.domain import Severity, severity_rank
from adhikar.errors import AdhikarError
from adhikar.pipeline import IngestOutcome, Pipeline, lawyer_questions
from adhikar.security.audit import verify_chain
from adhikar.web.render import Highlight, excerpt_around, render_highlighted

router = APIRouter(tags=["web"], include_in_schema=False)

#: Text label and shape for each severity. Severity is never communicated by
#: colour alone -- every level carries a word and a distinct glyph, so the
#: encoding survives greyscale printing and colour vision deficiency.
SEVERITY_PRESENTATION: dict[str, dict[str, str]] = {
    "critical": {"label": "Critical", "glyph": "◆", "order": "4"},
    "high": {"label": "High", "glyph": "▲", "order": "3"},
    "medium": {"label": "Medium", "glyph": "■", "order": "2"},
    "low": {"label": "Low", "glyph": "●", "order": "1"},
    "info": {"label": "For information", "glyph": "○", "order": "0"},
}


def _render(
    request: Request, template: str, context: dict[str, Any], status: int = 200
) -> Response:
    # app.state is untyped, so the template engine arrives as Any; name the type
    # here rather than letting it propagate through every route's return type.
    templates: Jinja2Templates = request.app.state.templates
    response: Response = templates.TemplateResponse(
        request=request,
        name=template,
        context={"severity_presentation": SEVERITY_PRESENTATION, **context},
        status_code=status,
    )
    return response


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, settings: Annotated[Settings, Depends(get_app_settings)]) -> Any:
    """Upload page, and the explanation of what this does that a chatbot does not."""
    return _render(
        request,
        "index.html",
        {
            "engine": settings.resolved_engine.value,
            "max_mb": settings.max_upload_bytes // (1024 * 1024),
        },
    )


@router.post("/documents", response_class=HTMLResponse)
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
    documents: Annotated[Any, Depends(get_documents)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Any:
    """Handle an upload and redirect to its report.

    Errors render the upload page again with an error summary rather than a bare
    error page, so the user keeps their context and the message is associated
    with the field that caused it.
    """
    enforce_rate_limit(request, upload=True)
    try:
        data = await _read_limited(file, settings.max_upload_bytes)
        outcome = pipeline.ingest(data, _safe_filename(file.filename))
    except AdhikarError as exc:
        return _render(
            request,
            "index.html",
            {
                "engine": settings.resolved_engine.value,
                "max_mb": settings.max_upload_bytes // (1024 * 1024),
                "errors": [{"field": "file", "message": exc.safe_detail}],
            },
            status=exc.status_code,
        )

    await documents.put(outcome)
    await request.app.state.audit.append(outcome.audit)
    return RedirectResponse(url=f"/documents/{outcome.document.id}", status_code=303)


@router.get("/documents/{document_id}", response_class=HTMLResponse)
async def report(
    request: Request,
    document_id: str,
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
    documents: Annotated[Any, Depends(get_documents)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Any:
    """The analysis report: risks, obligations, the document, and the audit trail."""
    enforce_rate_limit(request)
    outcome: IngestOutcome = await documents.get(document_id)
    return _report_page(request, outcome, pipeline, settings)


@router.post("/documents/{document_id}/ask", response_class=HTMLResponse)
async def ask(
    request: Request,
    document_id: str,
    question: Annotated[str, Form(min_length=3, max_length=500)],
    pipeline: Annotated[Pipeline, Depends(get_pipeline)],
    documents: Annotated[Any, Depends(get_documents)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Any:
    """Answer a question and re-render the report with the result in place."""
    enforce_rate_limit(request)
    outcome: IngestOutcome = await documents.get(document_id)
    result = await pipeline.ask(outcome.document, question)
    await request.app.state.audit.append(result.audit)
    return _report_page(request, outcome, pipeline, settings, answer=result)


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, pipeline: Annotated[Pipeline, Depends(get_pipeline)]) -> Any:
    """The audit trail and a live verification of its hash chain."""
    enforce_rate_limit(request)
    records = pipeline.audit_chain.records()
    return _render(
        request,
        "audit.html",
        {
            "records": list(records[::-1]),
            "verification": verify_chain(records),
            "head": pipeline.audit_chain.head,
        },
    )


def _report_page(
    request: Request,
    outcome: IngestOutcome,
    pipeline: Pipeline,
    settings: Settings,
    answer: Any = None,
) -> Any:
    document = outcome.document
    analysis = pipeline.analyse(document)

    # Evidence highlights, most severe first so that where two findings overlap
    # the more serious one is the mark that survives.
    highlights: list[Highlight] = []
    for finding in sorted(analysis.findings, key=lambda f: -severity_rank(f.severity)):
        highlights.extend(
            Highlight(
                start=span.start,
                end=span.end,
                label=f"{SEVERITY_PRESENTATION[finding.severity.value]['label']} risk: "
                f"{finding.title}",
                kind=finding.severity.value,
                anchor_id=f"evidence-{finding.id.replace(':', '-')}",
            )
            for span in finding.spans
        )
    # Concealed passages are marked too: seeing where the hidden text sat is more
    # convincing than being told it existed.
    highlights.extend(
        Highlight(
            start=signal.start,
            end=signal.end,
            label=f"Hidden or manipulative text: {signal.explanation}",
            kind="injection",
        )
        for signal in outcome.injection.signals
    )

    glossary = get_glossary(settings.knowledge_path / "glossary.yaml")

    return _render(
        request,
        "report.html",
        {
            "document": document,
            "outcome": outcome,
            "analysis": analysis,
            "findings": analysis.findings,
            "obligations": analysis.obligations,
            "contradictions": analysis.contradictions,
            "questions": lawyer_questions(analysis.findings),
            "answer": answer,
            "highlighted": render_highlighted(document.text, highlights),
            "glossary_terms": glossary.present_in(document.text, limit=12),
            "engine": settings.resolved_engine.value,
            "excerpt": excerpt_around,
            "Severity": Severity,
        },
    )
