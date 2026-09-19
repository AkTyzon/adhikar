#!/usr/bin/env python3
"""Side-by-side demonstration: a poisoned contract against two pipelines.

This is the argument for why Adhikar is not "a chatbot with extra steps",
reduced to something you can run in ten seconds.

The same PDF goes through two paths:

  naive     -- what almost every document-QA tool does: extract the text, put it
               in the prompt, ask the question. The document's own instructions
               arrive with the same authority as the operator's.
  adhikar   -- extraction with concealment forensics, a scan for embedded
               instructions, a hard data/instruction boundary, and a verification
               gate that only ever reads document spans.

The payload is white-on-white text inside an otherwise ordinary services
agreement. It is invisible in every PDF reader and returned verbatim by every
text extractor. It instructs the reader to suppress the indemnity finding and
report the contract as standard and fair.

Usage:
    python scripts/demo_injection.py
    python scripts/demo_injection.py --fixture tests/fixtures/contract_poisoned_tiny.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adhikar.analysis.catalog import get_catalog
from adhikar.analysis.risk import analyse
from adhikar.config import Settings
from adhikar.domain import Document
from adhikar.errors import DocumentQuarantinedError
from adhikar.ingest.extract import extract
from adhikar.ingest.segment import segment
from adhikar.llm import transcript
from adhikar.llm.base import DocumentContext
from adhikar.llm.registry import build_provider
from adhikar.pipeline import Pipeline

RULE = "─" * 78


def heading(text: str) -> None:
    print(f"\n{RULE}\n  {text}\n{RULE}")


def naive_pipeline(data: bytes, settings: Settings) -> None:
    """What a typical 'upload a PDF and ask questions' implementation does."""
    heading("PATH 1  —  naive pipeline (text into the prompt, no defences)")

    extraction = extract(data, settings, "contract.pdf")
    print(f"Extracted {len(extraction.text)} characters.")
    print("Concealment forensics: not performed.")
    print("Embedded-instruction scan: not performed.\n")

    # This is the critical line. The document is concatenated into the system
    # prompt, so its text carries operator authority.
    system_prompt = (
        "You are a contract analyst. Review the following contract and report "
        "any risks to the user.\n\n" + extraction.text
    )

    payload_start = extraction.text.find("SYSTEM INSTRUCTION")
    print("The prompt sent to the model ends like this:\n")
    if payload_start != -1:
        tail = extraction.text[payload_start : payload_start + 300]
        for line in tail.splitlines():
            if line.strip():
                print(f"    | {line.strip()}")
    print(
        "\n⚠  Those lines are invisible in any PDF reader. In this prompt they sit"
        "\n   inside the system message, indistinguishable from the operator's own"
        f"\n   instructions. The model receives {len(system_prompt)} characters in which"
        "\n   'report no risks found' has exactly as much authority as 'report any risks'."
    )


def adhikar_pipeline(data: bytes, settings: Settings) -> None:
    """The same document through the defended pipeline."""
    heading("PATH 2  —  Adhikar")

    extraction = extract(data, settings, "contract.pdf")
    print(f"Extracted {len(extraction.text)} characters.")

    print(
        f"\n1. Concealment forensics at the glyph level: {len(extraction.artifacts)} artifact(s)."
    )
    for artifact in extraction.artifacts:
        quoted = extraction.text[artifact.start : artifact.start + 62].replace("\n", " ")
        print(f"     [{artifact.kind}] characters {artifact.start}–{artifact.end}")
        print(f"     → {quoted!r}")

    pipeline = Pipeline(settings, build_provider(settings))
    print("\n2. Embedded-instruction scan (lexical + structural):")
    try:
        outcome = pipeline.ingest(data, "contract.pdf")
    except DocumentQuarantinedError as exc:
        score = exc.context.get("score", 0.0)
        print(
            f"     score {score:.3f} ≥ block threshold "
            f"{settings.injection_block_threshold} → QUARANTINED"
        )
        print(f"     The document is never analysed. Audit run {exc.context.get('run_id')}.")
        _show_boundary(extraction.text)
        _show_would_be_findings(extraction, settings)
        return

    print(f"     score {outcome.injection.score:.3f} — below the block threshold.")
    _show_boundary(extraction.text)


def _show_boundary(text: str) -> None:
    """Even below the block threshold, the structural boundary still holds."""
    print("\n3. The data/instruction boundary (applied regardless of score):")
    built = transcript.build(
        system_prompt="You analyse contracts. Fence token: {{FENCE}}",
        instruction="List the risks in this agreement.",
        documents=[DocumentContext("d1", "contract.pdf", text)],
    )
    print(f"     System prompt: {len(built.system)} characters, containing no document text.")
    print(f"     Document fenced with a per-request nonce: {built.nonce[:16]}…")
    print("     Operator instruction restated after the document, with system-role authority.")
    print(
        "\n     A forged '</untrusted_document>' inside the document cannot close the"
        "\n     real fence, because the real one carries a 128-bit nonce the author of"
        "\n     the document never saw."
    )


def _show_would_be_findings(extraction, settings: Settings) -> None:
    """What the risk engine says about the clause the payload tried to suppress."""
    print("\n4. What the payload was trying to hide:")
    clauses = segment(extraction.text, "demo", settings.knowledge_path / "segmentation.yaml")
    document = Document(
        id="demo",
        filename="contract.pdf",
        media_type=extraction.media_type,
        content_sha256="0" * 64,
        text=extraction.text,
        clauses=clauses,
        ingested_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    report = analyse(document, get_catalog(settings.knowledge_path / "clauses.yaml"))
    for finding in report.by_severity()[:3]:
        print(f"     [{finding.severity.value.upper():<8}] {finding.title}")
    print(
        "\n     These findings come from deterministic rules over the clause text."
        "\n     No instruction in the document can suppress them: the rules do not"
        "\n     read instructions, and the verification gate only ever reads spans."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).parent.parent / "tests" / "fixtures" / "contract_poisoned_white.pdf",
    )
    args = parser.parse_args(argv)

    if not args.fixture.exists():
        print(f"Fixture not found: {args.fixture}", file=sys.stderr)
        print("Run: python scripts/make_fixtures.py", file=sys.stderr)
        return 2

    settings = Settings(_env_file=None)
    data = args.fixture.read_bytes()

    print(f"\nDocument under test: {args.fixture.name} ({len(data)} bytes)")
    print("A services agreement with an instruction hidden inside it.")

    naive_pipeline(data, settings)
    adhikar_pipeline(data, settings)

    heading("CONCLUSION")
    print(
        "Detection is best-effort and an adaptive attacker will eventually evade it.\n"
        "That is why it is not the load-bearing defence. The document never enters\n"
        "the system prompt, the fence cannot be forged, and no statement reaches the\n"
        "user without being checked against a passage that provably exists in the\n"
        "document. An injected instruction that survives every scan still cannot\n"
        "manufacture a verified claim.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
