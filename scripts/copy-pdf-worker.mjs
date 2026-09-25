/**
 * Copy the pdf.js worker into public/.
 *
 * pdf.js needs its worker as a separate file at a URL it can fetch. Bundler-based
 * approaches for this are fragile across Next and Turbopack versions, so the
 * worker is copied to a fixed public path and referenced by that path. Boring,
 * deterministic, and it survives a toolchain upgrade.
 *
 * Runs before dev and before build.
 */

import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);

try {
  const pdfjsRoot = dirname(require.resolve("pdfjs-dist/package.json"));
  const source = join(pdfjsRoot, "build", "pdf.worker.min.mjs");

  if (!existsSync(source)) {
    console.error(`[pdf-worker] not found at ${source}; PDF upload will not work.`);
    process.exit(0); // Never fail the build over an optional capability.
  }

  mkdirSync("public", { recursive: true });
  copyFileSync(source, join("public", "pdf.worker.min.mjs"));
  console.log("[pdf-worker] copied to public/pdf.worker.min.mjs");
} catch (error) {
  console.error("[pdf-worker] skipped:", error instanceof Error ? error.message : error);
}
