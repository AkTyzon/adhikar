"""Command-line interface.

Exists so the analysis can be run without the web server -- in a terminal, in a
pipeline, or in CI -- and so the offline engine's behaviour can be inspected
directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from adhikar import __version__
from adhikar.config import Settings
from adhikar.errors import AdhikarError
from adhikar.export.packet import build_packet
from adhikar.llm.registry import build_provider
from adhikar.pipeline import Pipeline, lawyer_questions


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adhikar",
        description="Analyse a legal document. Every finding quotes the source.",
    )
    parser.add_argument("--version", action="version", version=f"adhikar {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyse = subparsers.add_parser("analyse", help="analyse a document")
    analyse.add_argument("path", type=Path, help="PDF, DOCX or text file")
    analyse.add_argument(
        "--packet", action="store_true", help="print the lawyer-preparation packet"
    )
    analyse.add_argument("--ask", metavar="QUESTION", help="ask a question about it")

    subparsers.add_parser("serve", help="run the web application")
    return parser


def _analyse(args: argparse.Namespace) -> int:
    settings = Settings()
    pipeline = Pipeline(settings, build_provider(settings))

    try:
        outcome = pipeline.ingest(args.path.read_bytes(), args.path.name)
    except AdhikarError as exc:
        print(f"error: {exc.safe_detail}", file=sys.stderr)
        return 2

    analysis = pipeline.analyse(outcome.document)

    if args.packet:
        print(
            build_packet(
                outcome.document,
                analysis.risk,
                analysis.obligations,
                analysis.contradictions,
                lawyer_questions(analysis.findings),
                redaction=outcome.redaction,
                engine=settings.resolved_engine.value,
            )
        )
        return 0

    print(
        f"{args.path.name}: {len(outcome.document.clauses)} clauses, risk {analysis.risk.score:.2f}"
    )
    if outcome.injection.signals:
        print(f"  ! embedded-instruction score {outcome.injection.score:.2f}")
    for finding in analysis.findings:
        print(f"  [{finding.severity.value.upper():<8}] {finding.title}")

    if args.ask:
        result = asyncio.run(pipeline.ask(outcome.document, args.ask))
        print(f"\nQ: {args.ask}")
        if result.answer.abstain_reason:
            print(f"   {result.answer.abstain_reason}")
        for item in result.answer.admitted:
            print(f"   - {item.claim.text}")
        if result.answer.withheld:
            print(f"   ({len(result.answer.withheld)} statement(s) withheld as unverified)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run("adhikar.api.app:create_app", factory=True, host="127.0.0.1", port=8000)
        return 0
    return _analyse(args)


if __name__ == "__main__":
    raise SystemExit(main())
