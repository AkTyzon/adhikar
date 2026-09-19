"""The lawyer-preparation packet.

The most useful thing this tool can produce is not an answer -- it is a document
someone can put in front of a solicitor at the start of a paid half-hour, so that
the half-hour is spent on judgement rather than on reading.

The packet is Markdown: readable as plain text, printable, pasteable into an
email, and requiring no software the recipient does not have.  Every finding
carries the passage it came from, so the lawyer can go straight to the clause
rather than taking the tool's word for anything.

Personal data is restored here and only here.  Analysis ran on pseudonymised
text; the packet is for the user and their adviser, so the real names go back in
at the last step, in memory, on the way out.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from adhikar.analysis.obligations import ObligationSet
from adhikar.analysis.risk import RiskReport
from adhikar.domain import Contradiction, Document, Finding, Severity, severity_rank
from adhikar.security.redaction import RedactionResult

_SEVERITY_LABEL = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "FOR INFORMATION",
}


def build_packet(
    document: Document,
    risk: RiskReport,
    obligations: ObligationSet,
    contradictions: Sequence[Contradiction],
    questions: Sequence[tuple[str, str]],
    *,
    redaction: RedactionResult | None = None,
    engine: str = "offline",
) -> str:
    """Render the full packet as Markdown."""
    sections = [
        _header(document, engine),
        _summary(risk, obligations, contradictions),
        _questions(questions),
        _findings(document, risk.by_severity()),
        _deadlines(obligations),
        _contradictions(contradictions),
        _method(engine),
    ]
    packet = "\n\n".join(section for section in sections if section)

    # Restore real values last: the analysis ran pseudonymised, the reader needs
    # the names. Nothing between these two points ever saw them.
    if redaction is not None and redaction.vault:
        packet = redaction.restore(packet)
    return packet


def _header(document: Document, engine: str) -> str:
    generated = datetime.now(UTC).strftime("%d %B %Y at %H:%M UTC")
    return (
        f"# Document review notes: {document.filename}\n\n"
        f"Prepared by Adhikar on {generated}.\n\n"
        f"- **Document fingerprint (SHA-256):** `{document.content_sha256}`\n"
        f"- **Clauses analysed:** {len(document.clauses)}\n"
        f"- **Analysis engine:** {engine}\n\n"
        "> **This is not legal advice.** It is a summary of what the document says, "
        "produced automatically, to help you prepare for a conversation with a "
        "qualified lawyer. Every point below quotes the document so you can check "
        "it yourself."
    )


def _summary(
    risk: RiskReport, obligations: ObligationSet, contradictions: Sequence[Contradiction]
) -> str:
    counts = risk.counts()
    if not counts:
        summary = "No clauses matched a known risk pattern."
    else:
        parts = [
            f"{count} {_SEVERITY_LABEL.get(level, level).lower()}"
            for level, count in sorted(
                counts.items(), key=lambda kv: -severity_rank(_as_severity(kv[0]))
            )
        ]
        summary = "Findings: " + ", ".join(parts) + "."

    lines = [
        "## At a glance",
        "",
        f"- {summary}",
        f"- {len(obligations.obligations)} obligations identified.",
    ]
    if obligations.unresolved_anchors:
        lines.append(
            f"- {len(obligations.unresolved_anchors)} deadline(s) could not be "
            f"calculated because the document never states when "
            f"{', '.join(obligations.unresolved_anchors)} occurred."
        )
    if contradictions:
        lines.append(f"- {len(contradictions)} conflicting requirement(s) found.")
    return "\n".join(lines)


def _as_severity(value: str) -> Severity:
    return Severity(value)


def _questions(questions: Sequence[tuple[str, str]]) -> str:
    """Questions come first: this is the part that is used in the meeting."""
    if not questions:
        return ""
    lines = [
        "## Questions to ask",
        "",
        "Each of these is specific to this document and answerable in a short consultation.",
        "",
    ]
    for index, (question, prompted_by) in enumerate(questions, start=1):
        lines.append(f"{index}. **{question}**")
        lines.append(f"   _Prompted by: {prompted_by}_")
        lines.append("")
    return "\n".join(lines).rstrip()


def _findings(document: Document, findings: Sequence[Finding]) -> str:
    if not findings:
        return ""
    lines = ["## Findings in detail", ""]
    for finding in findings:
        label = _SEVERITY_LABEL.get(finding.severity.value, finding.severity.value.upper())
        lines.append(f"### [{label}] {finding.title}")
        lines.append("")
        lines.append(finding.why_it_matters)
        lines.append("")
        for span in finding.spans[:2]:
            quote = " ".join(span.resolve(document.text).split())
            lines.append(f"> {quote}")
            lines.append("")
            lines.append(f"_Source: this document, characters {span.start}–{span.end}._")
            lines.append("")
        deviation = finding.baseline_deviation
        if deviation and deviation.expected:
            lines.append(f"**Usually:** {deviation.expected}")
            lines.append("")
    return "\n".join(lines).rstrip()


def _deadlines(obligations: ObligationSet) -> str:
    if not obligations.obligations:
        return ""
    lines = [
        "## Obligations and deadlines",
        "",
        "| Who | Must | By when |",
        "| --- | --- | --- |",
    ]
    for obligation in obligations.obligations:
        if obligation.computed_due:
            when = obligation.computed_due.strftime("%d %B %Y")
        elif obligation.offset_days and obligation.trigger_event:
            when = (
                f"{obligation.offset_days} days from {obligation.trigger_event} (date not stated)"
            )
        else:
            when = "Not stated"
        lines.append(
            f"| {_cell(obligation.obligor)} | {_cell(obligation.action)} | {_cell(when)} |"
        )
    lines.append("")
    lines.append(
        "_Dates were calculated from the periods the document states. Where the "
        "document does not say when a triggering event happened, no date is shown "
        "rather than an estimate._"
    )
    return "\n".join(lines)


def _contradictions(contradictions: Sequence[Contradiction]) -> str:
    if not contradictions:
        return ""
    lines = ["## Conflicting requirements", ""]
    lines.extend(f"- {c.explanation}" for c in contradictions)
    return "\n".join(lines)


def _method(engine: str) -> str:
    return (
        "## How this was produced\n\n"
        f"Clause risks were detected by rule, from a published catalogue, using the "
        f"`{engine}` engine. Every statement above quotes the source document and "
        "was checked against that quote before being included; anything that could "
        "not be verified was left out.\n\n"
        "Adhikar does not interpret the law, predict outcomes, or recommend a "
        "course of action. Those judgements belong to a qualified professional who "
        "knows the full circumstances."
    )


def _cell(value: str) -> str:
    """Escape a value for a Markdown table cell."""
    return " ".join(value.split()).replace("|", "\\|")[:200]
