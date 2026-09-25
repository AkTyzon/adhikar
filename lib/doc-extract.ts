/**
 * Client-side document text extraction.
 *
 * Runs entirely in the browser. The file itself is never uploaded — only the text
 * needed to answer the user's question crosses the network. For a tenancy
 * agreement or a legal notice that distinction matters, and it means nothing is
 * written to any server's disk at any point.
 *
 * Supported: PDF (pdf.js), DOCX (mammoth), and plain text. Scanned pages and
 * photographs are **not** supported — there is no OCR — and the failure is
 * explicit rather than a silently empty result, because a user handed a blank
 * analysis would not know their document had not been read.
 */

/** Matches the server's ceiling in app/api/analyze-doc/route.ts. */
export const MAX_DOCUMENT_CHARS = 120_000;
/** Below this the file is almost certainly a scan or an empty page. */
export const MIN_DOCUMENT_CHARS = 200;
export const MAX_FILE_BYTES = 12 * 1024 * 1024;

export interface ExtractionResult {
  text: string;
  /** Page count, where the format has pages. */
  pages?: number;
  /** Set when the text was cut to the size ceiling. */
  truncated: boolean;
  kind: "pdf" | "docx" | "text";
}

/** Common shape returned by every format-specific extractor. */
interface RawExtraction {
  text: string;
  pages?: number;
}

export class ExtractionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ExtractionError";
  }
}

/**
 * Determine the format from the file's own bytes.
 *
 * The browser-reported MIME type and the extension are both trivially wrong —
 * renaming a file changes them — so the magic number decides.
 */
async function sniff(file: File): Promise<"pdf" | "docx" | "text"> {
  const header = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  const startsWith = (bytes: number[]) => bytes.every((byte, index) => header[index] === byte);

  if (startsWith([0x25, 0x50, 0x44, 0x46])) return "pdf"; // %PDF
  if (startsWith([0x50, 0x4b, 0x03, 0x04])) return "docx"; // PK.. (a zip; DOCX confirmed by mammoth)
  return "text";
}

export async function extractText(file: File): Promise<ExtractionResult> {
  if (file.size === 0) throw new ExtractionError("That file is empty.");
  if (file.size > MAX_FILE_BYTES) {
    throw new ExtractionError(
      `That file is ${(file.size / 1024 / 1024).toFixed(1)} MB. The limit is ${MAX_FILE_BYTES / 1024 / 1024} MB.`,
    );
  }

  const kind = await sniff(file);
  const extracted: RawExtraction = kind === "pdf" ? await fromPdf(file) : kind === "docx" ? await fromDocx(file) : await fromText(file);

  const normalised = normalise(extracted.text);
  if (normalised.length < MIN_DOCUMENT_CHARS) {
    throw new ExtractionError(
      kind === "pdf"
        ? "Almost no text could be read from that PDF. It is probably a scan or a photograph, and Adhikar has no OCR yet."
        : "That file did not contain enough readable text to analyse.",
    );
  }

  const truncated = normalised.length > MAX_DOCUMENT_CHARS;
  return {
    text: truncated ? normalised.slice(0, MAX_DOCUMENT_CHARS) : normalised,
    pages: extracted.pages,
    truncated,
    kind,
  };
}

async function fromPdf(file: File): Promise<RawExtraction> {
  // Imported dynamically so pdf.js is not in the initial bundle: most visitors
  // ask a question rather than upload anything, and this is a large dependency.
  const pdfjs = await import("pdfjs-dist");

  // Served from public/ by scripts/copy-pdf-worker.mjs rather than resolved by the
  // bundler, which is fragile across Next and Turbopack versions.
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

  let document;
  try {
    document = await pdfjs.getDocument({
      data: new Uint8Array(await file.arrayBuffer()),
      // A PDF is untrusted input. Remote resources and embedded scripts have no
      // legitimate role in text extraction and are refused.
      isEvalSupported: false,
      disableFontFace: true,
    }).promise;
  } catch {
    throw new ExtractionError("That PDF could not be opened. It may be corrupt or password-protected.");
  }

  const parts: string[] = [];
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent();
    parts.push(
      content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" "),
    );
    page.cleanup();
  }

  const pages = document.numPages;
  await document.destroy();
  return { text: parts.join("\n\n"), pages };
}

async function fromDocx(file: File): Promise<RawExtraction> {
  const mammoth = await import("mammoth");
  try {
    const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() });
    return { text: result.value };
  } catch {
    throw new ExtractionError("That file is a zip archive but not a readable Word document.");
  }
}

async function fromText(file: File): Promise<RawExtraction> {
  const text = await file.text();
  // Reject binaries that slipped past the magic-number check rather than sending
  // a wall of control characters to a model.
  if (/\u0000/.test(text.slice(0, 4096))) {
    throw new ExtractionError("Adhikar can read PDF, Word (.docx) and plain text files.");
  }
  return { text };
}

/** Collapse whitespace while keeping paragraph breaks, which carry structure. */
function normalise(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
