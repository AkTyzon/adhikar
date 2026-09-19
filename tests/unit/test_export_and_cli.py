"""The lawyer packet, the CLI, and audit persistence."""

from __future__ import annotations

from adhikar.analysis.catalog import ClauseCatalog
from adhikar.analysis.obligations import extract as extract_obligations
from adhikar.analysis.risk import analyse
from adhikar.cli import main
from adhikar.db.models import AuditRecordRow
from adhikar.domain import Document
from adhikar.export.packet import build_packet
from adhikar.pipeline import lawyer_questions
from adhikar.security.audit import AuditChain, start_record, verify_chain
from adhikar.security.redaction import Redactor


def _packet(document: Document, catalog: ClauseCatalog, **kwargs) -> str:
    risk = analyse(document, catalog)
    obligations = extract_obligations(document)
    return build_packet(document, risk, obligations, (), lawyer_questions(risk.findings), **kwargs)


class TestLawyerPacket:
    def test_includes_the_document_fingerprint(
        self, document: Document, catalog: ClauseCatalog
    ) -> None:
        assert document.content_sha256 in _packet(document, catalog)

    def test_leads_with_the_questions(self, document: Document, catalog: ClauseCatalog) -> None:
        """This is the part used in the meeting, so it comes first."""
        packet = _packet(document, catalog)
        assert packet.index("## Questions to ask") < packet.index("## Findings in detail")

    def test_every_finding_quotes_the_document(
        self, document: Document, catalog: ClauseCatalog
    ) -> None:
        packet = _packet(document, catalog)
        assert "> " in packet
        assert "characters" in packet

    def test_states_that_it_is_not_legal_advice(
        self, document: Document, catalog: ClauseCatalog
    ) -> None:
        assert "not legal advice" in _packet(document, catalog).lower()

    def test_explains_uncomputed_deadlines(
        self, document: Document, catalog: ClauseCatalog
    ) -> None:
        assert "date not stated" in _packet(document, catalog)

    def test_table_cells_escape_pipe_characters(self, settings, catalog: ClauseCatalog) -> None:
        """An unescaped pipe would silently corrupt the Markdown table."""
        from datetime import UTC, datetime

        from adhikar.ingest.segment import segment

        text = (
            "1. Delivery. The Provider shall deliver the goods | services within "
            "thirty (30) days of the effective date of this Agreement.\n"
        )
        clauses = segment(text, "d1", settings.knowledge_path / "segmentation.yaml")
        doc = Document(
            id="d1",
            filename="d.txt",
            media_type="text/plain",
            content_sha256="e" * 64,
            text=text,
            clauses=clauses,
            ingested_at=datetime.now(UTC),
        )
        for line in _packet(doc, catalog).splitlines():
            if line.startswith("| ") and "---" not in line:
                assert line.count("|") - line.count("\\|") == 4

    def test_personal_data_is_restored_only_at_the_end(
        self, settings, catalog: ClauseCatalog
    ) -> None:
        """Analysis runs pseudonymised; the packet is for the user and their adviser."""
        from datetime import UTC, datetime

        from adhikar.ingest.segment import segment

        redactor = Redactor.from_catalogue(settings.knowledge_path / "pii_patterns.yaml")
        original = (
            "1. Notices. The Client shall send all notices to rajesh@example.com "
            "within thirty (30) days of the effective date.\n"
        )
        redaction = redactor.redact(original)
        clauses = segment(redaction.text, "d1", settings.knowledge_path / "segmentation.yaml")
        doc = Document(
            id="d1",
            filename="d.txt",
            media_type="text/plain",
            content_sha256="f" * 64,
            text=redaction.text,
            clauses=clauses,
            ingested_at=datetime.now(UTC),
        )

        assert "[[EMAIL_1]]" in _packet(doc, catalog)
        restored = _packet(doc, catalog, redaction=redaction)
        assert "rajesh@example.com" in restored
        assert "[[EMAIL_1]]" not in restored


class TestCli:
    def test_analyse_reports_findings(self, capsys, tmp_path) -> None:
        target = tmp_path / "contract.txt"
        target.write_text(
            "1. Indemnity. The Provider shall indemnify the Client against any and "
            "all claims arising out of this agreement, without limit.\n"
        )
        assert main(["analyse", str(target)]) == 0
        assert "CRITICAL" in capsys.readouterr().out

    def test_packet_mode_emits_markdown(self, capsys, tmp_path) -> None:
        target = tmp_path / "contract.txt"
        target.write_text(
            "1. Fees. The Client shall pay each invoice within thirty (30) days "
            "of receipt of a valid invoice.\n"
        )
        assert main(["analyse", str(target), "--packet"]) == 0
        assert capsys.readouterr().out.startswith("# Document review notes")

    def test_ask_mode_answers_from_the_document(self, capsys, tmp_path) -> None:
        target = tmp_path / "contract.txt"
        target.write_text(
            "1. Fees. The Client shall pay each invoice within thirty (30) days "
            "of receipt of a valid invoice.\n"
        )
        main(["analyse", str(target), "--ask", "When is payment due?"])
        assert "thirty" in capsys.readouterr().out

    def test_an_unreadable_document_exits_non_zero(self, capsys, tmp_path) -> None:
        target = tmp_path / "bad.txt"
        target.write_bytes(b"\x00\x01\x02\x03")
        assert main(["analyse", str(target)]) == 2
        assert "error:" in capsys.readouterr().err


class TestAuditPersistence:
    def test_a_record_survives_a_round_trip_through_the_row(self) -> None:
        """An audit log you cannot verify after a restart is decoration."""
        chain = AuditChain()
        original = chain.append(
            start_record(
                "ask",
                document_sha256="a" * 64,
                engine="offline",
                model=None,
                claims_admitted=3,
                claims_withheld=1,
            )
        )
        restored = AuditRecordRow.from_record(original).to_record()

        assert restored.record_hash == original.record_hash
        assert restored.compute_hash() == original.record_hash
        assert verify_chain([restored]).valid

    def test_the_row_stores_no_document_text(self) -> None:
        record = AuditChain().append(
            start_record("ingest", document_sha256="b" * 64, engine="offline", model=None)
        )
        row = AuditRecordRow.from_record(record)
        assert "text" not in row.payload
