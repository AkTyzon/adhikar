"""Document extraction with concealment forensics.

Text extraction is the point at which a document stops being bytes an adversary
controls and starts being input to a language model, so it is the right place to
notice that some of those bytes were never meant for a human to see.

A PDF can position text outside the page, paint it in white on a white page, or
set it at a quarter of a point.  All three are invisible when the document is
read and perfectly legible to an extractor.  This module walks the glyph stream
rather than calling a convenience text API, so colour, size and position are
available at the moment each character is appended -- which is what lets a
concealed passage be reported as a span with real offsets rather than a vague
warning.

What is *not* covered is stated plainly in ``docs/THREAT_MODEL.md``: PDF text
render mode 3 (invisible ink), glyphs covered by a later opaque shape, and text
inside embedded images (no OCR).  The scanner is one layer; the architecture does
not depend on it catching everything.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTPage, LTTextContainer
from pdfminer.pdfparser import PDFSyntaxError

from adhikar.config import Settings
from adhikar.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    MalformedDocumentError,
    UnsupportedMediaTypeError,
)
from adhikar.security.injection import ExtractionArtifact

PDF: Final = "application/pdf"
DOCX: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT: Final = "text/plain"

SUPPORTED_MEDIA_TYPES: Final = frozenset({PDF, DOCX, TXT})

#: Magic-byte prefixes. The browser-supplied content type is advisory only --
#: it is attacker-controlled, so the file's own bytes decide how it is parsed.
_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"%PDF-", PDF),
    (b"PK\x03\x04", DOCX),  # DOCX is a zip; confirmed below by its content types
)

#: A glyph whose colour is at least this bright on an assumed-white page is
#: effectively invisible. 0.90 leaves headroom for legitimate pale-grey print.
_WHITE_LUMINANCE: Final = 0.90
#: Body text is rarely below 4pt; footnotes bottom out around 6pt.
_TINY_FONT_PT: Final = 3.5
#: Concealed runs shorter than this are noise (a stray white space character).
_MIN_CONCEALED_CHARS: Final = 12


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Normalised text plus everything the extractor noticed while producing it."""

    text: str
    media_type: str
    page_count: int | None = None
    artifacts: tuple[ExtractionArtifact, ...] = ()
    #: Per-page character counts, used to map offsets back to pages in the UI.
    page_offsets: tuple[int, ...] = field(default=())


def sniff_media_type(data: bytes, filename: str | None = None) -> str:
    """Determine a document's type from its contents.

    Raises:
        UnsupportedMediaTypeError: the bytes are not a supported document.
    """
    for prefix, media_type in _MAGIC:
        if data.startswith(prefix):
            if media_type is DOCX and not _is_docx(data):
                raise UnsupportedMediaTypeError(
                    "zip archive is not a Word document", context={"filename": filename}
                )
            return media_type

    # Plain text has no magic number; accept it only if it decodes cleanly and
    # contains no control bytes, which excludes arbitrary binaries.
    if _looks_like_text(data):
        return TXT

    raise UnsupportedMediaTypeError("unrecognised document format", context={"filename": filename})


def _is_docx(data: bytes) -> bool:
    """Confirm a zip is really a WordprocessingML package."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _looks_like_text(data: bytes, sample: int = 8192) -> bool:
    head = data[:sample]
    if b"\x00" in head:
        return False
    try:
        decoded = head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    control = sum(1 for ch in decoded if ord(ch) < 32 and ch not in "\t\n\r")
    return control / max(len(decoded), 1) < 0.01


def normalise_text(text: str) -> str:
    """Canonicalise whitespace while preserving paragraph structure.

    Offsets are assigned against *this* string and never against the raw
    extraction, so normalisation has to happen exactly once, before any span is
    created. Line endings are unified, runs of spaces collapsed, and blank-line
    runs capped at one -- enough to make clause segmentation reliable without
    destroying the layout cues it depends on.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------- #
# Extractors
# --------------------------------------------------------------------------- #


def extract(data: bytes, settings: Settings, filename: str | None = None) -> ExtractionResult:
    """Extract text from a document, enforcing every configured limit.

    Raises:
        DocumentTooLargeError: the input or its expansion exceeds limits.
        UnsupportedMediaTypeError: the format is not supported.
        MalformedDocumentError: the document could not be parsed.
        EmptyDocumentError: no text was recoverable.
    """
    if len(data) > settings.max_upload_bytes:
        raise DocumentTooLargeError(
            f"upload is {len(data)} bytes, limit is {settings.max_upload_bytes}"
        )

    media_type = sniff_media_type(data, filename)
    if media_type == PDF:
        result = _extract_pdf(data, settings)
    elif media_type == DOCX:
        result = _extract_docx(data, settings)
    else:
        result = _extract_plain(data, settings)

    if not result.text.strip():
        raise EmptyDocumentError(
            "no extractable text found; the document may be a scan requiring OCR"
        )
    if len(result.text) > settings.max_document_chars:
        raise DocumentTooLargeError(
            f"document expands to {len(result.text)} characters, "
            f"limit is {settings.max_document_chars}"
        )
    # Guard against decompression bombs: a small file that explodes into a huge
    # amount of text is not a contract.
    if len(result.text) > len(data) * settings.max_expansion_ratio:
        raise DocumentTooLargeError(
            f"document expands {len(result.text) / max(len(data), 1):.0f}x, "
            f"limit is {settings.max_expansion_ratio:.0f}x"
        )
    return result


def _extract_plain(data: bytes, settings: Settings) -> ExtractionResult:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedDocumentError("file is not valid UTF-8 text") from exc
    return ExtractionResult(text=normalise_text(text), media_type=TXT, page_count=None)


def _extract_docx(data: bytes, settings: Settings) -> ExtractionResult:
    import docx  # imported lazily: only paid for when a DOCX arrives

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises a wide range of parse errors
        raise MalformedDocumentError("Word document could not be parsed") from exc

    paragraphs: list[str] = []
    artifacts: list[ExtractionArtifact] = []
    cursor = 0
    for paragraph in document.paragraphs:
        text = paragraph.text
        if not text.strip():
            paragraphs.append(text)
            cursor += len(text) + 1
            continue
        if _docx_paragraph_hidden(paragraph):
            artifacts.append(
                ExtractionArtifact(
                    kind="hidden_docx_text",
                    start=cursor,
                    end=cursor + len(text),
                    detail=(
                        "Text marked hidden in the Word document, which does not "
                        "appear when the document is read normally."
                    ),
                    weight=0.75,
                )
            )
        paragraphs.append(text)
        cursor += len(text) + 1

    # Tables carry obligations as often as prose does; omitting them would lose
    # payment schedules and SLA tables entirely.
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                paragraphs.append(" | ".join(cells))

    return ExtractionResult(
        text=normalise_text("\n".join(paragraphs)),
        media_type=DOCX,
        artifacts=tuple(artifacts),
    )


def _docx_paragraph_hidden(paragraph: object) -> bool:
    """Whether every run in a paragraph carries the Word 'hidden' property."""
    runs = getattr(paragraph, "runs", [])
    if not runs:
        return False
    return all(bool(getattr(run.font, "hidden", False)) for run in runs)


def _extract_pdf(data: bytes, settings: Settings) -> ExtractionResult:
    """Walk the glyph stream, recording both text and concealment artifacts."""
    stream = io.BytesIO(data)
    chunks: list[str] = []
    artifacts: list[ExtractionArtifact] = []
    page_offsets: list[int] = []
    cursor = 0
    page_count = 0

    try:
        pages = extract_pages(stream, laparams=LAParams())
        for page in pages:
            page_count += 1
            # Checked before parsing the page, so an oversized document costs one
            # page of work rather than all of them.
            _enforce_page_limit(page_count, settings.max_pdf_pages)
            page_offsets.append(cursor)
            page_text, page_artifacts = _extract_pdf_page(page, cursor)
            chunks.append(page_text)
            artifacts.extend(page_artifacts)
            cursor += len(page_text) + 1  # the newline joined in below
    except DocumentTooLargeError:
        raise
    except PDFSyntaxError as exc:
        raise MalformedDocumentError("PDF structure is invalid") from exc
    except Exception as exc:
        raise MalformedDocumentError("PDF could not be read") from exc

    raw = "\n".join(chunks)
    normalised = normalise_text(raw)
    # Normalisation shifts offsets, so artifacts are re-anchored by searching for
    # their text rather than trusting pre-normalisation positions.
    rebased = _rebase_artifacts(artifacts, raw, normalised)
    return ExtractionResult(
        text=normalised,
        media_type=PDF,
        page_count=page_count,
        artifacts=tuple(rebased),
        page_offsets=tuple(page_offsets),
    )


def _enforce_page_limit(page_count: int, limit: int) -> None:
    """Raise once a document exceeds its configured page budget.

    Separated from the extraction loop so the limit is a guard clause rather than
    an exception raised and immediately re-caught inside the same ``try``.
    """
    if page_count > limit:
        raise DocumentTooLargeError(f"document exceeds the {limit}-page limit")


def _extract_pdf_page(page: LTPage, base: int) -> tuple[str, list[ExtractionArtifact]]:
    """Extract one page's text and note any concealed runs within it."""
    parts: list[str] = []
    artifacts: list[ExtractionArtifact] = []
    offset = 0
    # (reason, start, end, chars) for the run currently being accumulated.
    run: tuple[str, int, list[str]] | None = None

    def close_run(end: int) -> None:
        nonlocal run
        if run is None:
            return
        reason, start, chars = run
        text = "".join(chars).strip()
        if len(text) >= _MIN_CONCEALED_CHARS:
            artifacts.append(
                ExtractionArtifact(
                    kind=reason,
                    start=base + start,
                    end=base + end,
                    detail=_CONCEALMENT_DETAIL[reason],
                    weight=_CONCEALMENT_WEIGHT[reason],
                )
            )
        run = None

    for char, text in _iter_page_chars(page):
        reason = _concealment_reason(char, page) if char is not None else None
        if reason is not None:
            if run is None or run[0] != reason:
                close_run(offset)
                run = (reason, offset, [])
            run[2].append(text)
        else:
            close_run(offset)
        parts.append(text)
        offset += len(text)

    close_run(offset)
    return "".join(parts), artifacts


def _iter_page_chars(page: LTPage) -> Iterator[tuple[LTChar | None, str]]:
    """Yield (glyph, text) pairs, with ``None`` for layout-inserted whitespace."""
    for element in page:
        if not isinstance(element, LTTextContainer):
            continue
        for line in element:
            if not hasattr(line, "__iter__"):
                continue
            for item in line:
                if isinstance(item, LTChar):
                    yield item, item.get_text()
                elif hasattr(item, "get_text"):
                    yield None, item.get_text()
        yield None, "\n"


_CONCEALMENT_DETAIL: Final[dict[str, str]] = {
    "invisible_white_text": (
        "Text painted in white or near-white, invisible against the page but readable by software."
    ),
    "microscopic_text": ("Text set far below a legible size, effectively invisible to a reader."),
    "offpage_text": (
        "Text positioned outside the printable page area, so it never appears "
        "when the document is viewed or printed."
    ),
}

_CONCEALMENT_WEIGHT: Final[dict[str, float]] = {
    "invisible_white_text": 0.85,
    "microscopic_text": 0.7,
    "offpage_text": 0.8,
}


def _concealment_reason(char: LTChar, page: LTPage) -> str | None:
    """Why this glyph would not be visible to a reader, if it would not be."""
    if _luminance(char) >= _WHITE_LUMINANCE:
        return "invisible_white_text"
    if char.size < _TINY_FONT_PT:
        return "microscopic_text"
    if _outside_page(char, page):
        return "offpage_text"
    return None


def _luminance(char: LTChar) -> float:
    """Approximate perceived brightness of a glyph's fill colour.

    pdfminer reports the non-stroking colour in whatever space the PDF used, so
    this handles greyscale, RGB and CMYK. An unknown shape returns 0 (dark),
    because guessing "invisible" on an unparseable colour would produce false
    accusations against ordinary documents.
    """
    state = getattr(char, "graphicstate", None)
    colour = getattr(state, "ncolor", None) if state is not None else None

    if isinstance(colour, (int, float)):
        return float(colour)
    if isinstance(colour, (tuple, list)):
        values = [float(component) for component in colour if isinstance(component, (int, float))]
        if len(values) == 1:
            return values[0]
        if len(values) == 3:
            red, green, blue = values
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue
        if len(values) == 4:
            cyan, magenta, yellow, key = values
            red = 1 - min(1.0, cyan + key)
            green = 1 - min(1.0, magenta + key)
            blue = 1 - min(1.0, yellow + key)
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return 0.0


def _outside_page(char: LTChar, page: LTPage) -> bool:
    """Whether a glyph sits wholly outside the page box."""
    x0, y0, x1, y1 = char.bbox
    px0, py0, px1, py1 = page.bbox
    tolerance = 2.0
    return (
        x1 < px0 - tolerance or x0 > px1 + tolerance or y1 < py0 - tolerance or y0 > py1 + tolerance
    )


def _rebase_artifacts(
    artifacts: Sequence[ExtractionArtifact], raw: str, normalised: str
) -> list[ExtractionArtifact]:
    """Re-anchor artifact offsets from raw extraction space to normalised space.

    Whitespace normalisation moves everything, so each artifact's own text is
    located in the normalised string. An artifact whose text cannot be found is
    kept with a zero-width anchor rather than dropped: losing the *signal*
    because the *offset* is uncertain would be the wrong trade.
    """
    rebased: list[ExtractionArtifact] = []
    search_from = 0
    for artifact in artifacts:
        needle = normalise_text(raw[artifact.start : artifact.end])
        if not needle:
            continue
        index = normalised.find(needle, search_from)
        if index == -1:
            index = normalised.find(needle)
        if index == -1:
            rebased.append(
                ExtractionArtifact(
                    kind=artifact.kind,
                    start=0,
                    end=1,
                    detail=artifact.detail,
                    weight=artifact.weight,
                )
            )
            continue
        rebased.append(
            ExtractionArtifact(
                kind=artifact.kind,
                start=index,
                end=index + len(needle),
                detail=artifact.detail,
                weight=artifact.weight,
            )
        )
        search_from = index + len(needle)
    return rebased
