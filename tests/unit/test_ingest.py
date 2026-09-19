"""Extraction, format sniffing and the limits that protect the server."""

from __future__ import annotations

import io
import zipfile

import pytest

from adhikar.config import Settings
from adhikar.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    MalformedDocumentError,
    UnsupportedMediaTypeError,
)
from adhikar.ingest.extract import (
    DOCX,
    PDF,
    TXT,
    extract,
    normalise_text,
    sniff_media_type,
)

#: The minimum parts a WordprocessingML package needs to be openable. Built here
#: rather than committed as a binary so the fixture is readable and adjustable.
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)


def build_docx(body: str) -> bytes:
    """A minimal, valid .docx containing one paragraph."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


class TestMediaTypeSniffing:
    def test_detects_a_pdf_by_its_magic_bytes(self, benign_pdf: bytes) -> None:
        assert sniff_media_type(benign_pdf, "anything.txt") == PDF

    def test_detects_plain_text(self) -> None:
        assert sniff_media_type(b"1. Term. This Agreement runs for a year.", "c.txt") == TXT

    def test_detects_a_docx_by_its_package_contents(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "<xml/>")
        assert sniff_media_type(buffer.getvalue(), "c.docx") == DOCX

    def test_a_zip_that_is_not_a_word_document_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("payload.sh", "rm -rf /")
        with pytest.raises(UnsupportedMediaTypeError):
            sniff_media_type(buffer.getvalue(), "c.docx")

    def test_binary_content_is_rejected(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            sniff_media_type(b"\x7fELF\x02\x01\x01\x00", "c.txt")

    def test_a_null_byte_disqualifies_text(self) -> None:
        with pytest.raises(UnsupportedMediaTypeError):
            sniff_media_type(b"text\x00with a null", "c.txt")

    def test_the_filename_does_not_decide(self, benign_pdf: bytes) -> None:
        """Filenames and content types are attacker-controlled; bytes are not."""
        assert sniff_media_type(benign_pdf, "invoice.docx") == PDF


class TestNormalisation:
    def test_unifies_line_endings(self) -> None:
        assert "\r" not in normalise_text("a\r\nb\rc")

    def test_collapses_runs_of_spaces(self) -> None:
        assert normalise_text("a     b") == "a b"

    def test_preserves_paragraph_breaks(self) -> None:
        assert "\n\n" in normalise_text("para one\n\n\n\n\npara two")

    def test_is_idempotent(self) -> None:
        """Offsets are assigned against normalised text, so it must be stable."""
        once = normalise_text("a  b\r\n\r\n\r\nc   d")
        assert normalise_text(once) == once


class TestLimits:
    def test_an_oversized_upload_is_refused(self, settings: Settings) -> None:
        tight = settings.model_copy(update={"max_upload_bytes": 100})
        with pytest.raises(DocumentTooLargeError):
            extract(b"x" * 500, tight, "big.txt")

    def test_a_page_limit_is_enforced(self, settings: Settings, benign_pdf: bytes) -> None:
        tight = settings.model_copy(update={"max_pdf_pages": 0})
        with pytest.raises(DocumentTooLargeError, match="page limit"):
            extract(benign_pdf, tight, "c.pdf")

    def test_a_character_limit_is_enforced(self, settings: Settings) -> None:
        tight = settings.model_copy(update={"max_document_chars": 50})
        with pytest.raises(DocumentTooLargeError, match="characters"):
            extract(b"A clause of text. " * 100, tight, "c.txt")

    def test_an_expansion_bomb_is_refused(self, settings: Settings) -> None:
        """A small file expanding to a huge amount of text is not a contract.

        The guard exists for compressed containers. Plain text cannot expand, but
        a .docx is a zip, and highly repetitive content compresses to almost
        nothing: this 2 KB file would yield 440,000 characters.
        """
        data = build_docx("The Client shall pay. " * 20_000)
        assert len(data) < 5_000

        with pytest.raises(DocumentTooLargeError, match="expands"):
            extract(data, settings, "bomb.docx")

    def test_an_ordinary_docx_is_accepted(self, settings: Settings) -> None:
        """The bomb guard must not reject real Word documents."""
        data = build_docx("1. Fees. The Client shall pay each invoice within thirty (30) days.")
        assert "thirty (30) days" in extract(data, settings, "c.docx").text

    def test_an_empty_document_is_refused(self, settings: Settings) -> None:
        with pytest.raises(EmptyDocumentError):
            extract(b"   \n  \n ", settings, "blank.txt")

    def test_invalid_utf8_is_refused(self, settings: Settings) -> None:
        with pytest.raises((MalformedDocumentError, UnsupportedMediaTypeError)):
            extract(b"\xff\xfe\x00valid text here to pass sniffing", settings, "c.txt")

    def test_a_corrupt_pdf_is_refused(self, settings: Settings) -> None:
        with pytest.raises(MalformedDocumentError):
            extract(b"%PDF-1.4\nthis is not a real pdf structure", settings, "c.pdf")


class TestExtraction:
    def test_extracts_text_from_a_pdf(self, benign_pdf: bytes, settings: Settings) -> None:
        result = extract(benign_pdf, settings, "c.pdf")
        assert "SERVICES AGREEMENT" in result.text
        assert result.page_count == 1

    def test_offsets_into_extracted_text_are_usable(
        self, benign_pdf: bytes, settings: Settings
    ) -> None:
        result = extract(benign_pdf, settings, "c.pdf")
        index = result.text.index("Indemnity")
        assert result.text[index : index + 9] == "Indemnity"

    def test_artifact_offsets_survive_normalisation(
        self, poisoned_pdf: bytes, settings: Settings
    ) -> None:
        """Normalisation moves everything; artifacts must be re-anchored, not stale."""
        result = extract(poisoned_pdf, settings, "c.pdf")
        for artifact in result.artifacts:
            assert 0 <= artifact.start < artifact.end <= len(result.text)
