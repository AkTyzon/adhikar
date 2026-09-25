/**
 * Citation verification.
 *
 * These are the most important tests in the project. The claim Adhikar makes is
 * that a fabricated section number will not be rendered to a citizen as a
 * confident link to a government archive. If these pass, that claim holds; if
 * they regress, the application actively misleads the people it is for.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { auditCitations, extractCitations, verifyCitation } from "../lib/citations";

describe("extracting citations", () => {
  it("finds a section cited before its Act", () => {
    const found = extractCitations("You can file under Section 85 BNS today.");
    assert.equal(found.length, 1);
    assert.equal(found[0]?.actId, "BNS");
    assert.equal(found[0]?.number, "85");
  });

  it("finds a section cited after its Act", () => {
    const found = extractCitations("See RERA Section 18 for the refund.");
    assert.equal(found[0]?.actId, "RERA");
    assert.equal(found[0]?.number, "18");
  });

  it("handles 'of the' phrasing with a trailing year", () => {
    const found = extractCitations("Report it under Section 66D of the IT Act, 2000.");
    assert.equal(found[0]?.actId, "IT");
    assert.equal(found[0]?.number, "66D");
  });

  it("preserves a letter suffix, because 66 and 66C are different offences", () => {
    const found = extractCitations("Section 66C of the IT Act covers identity theft.");
    assert.equal(found[0]?.number, "66C");
    assert.equal(found[0]?.section?.heading, "Identity theft");
  });

  it("finds several citations in one passage", () => {
    const found = extractCitations(
      "Use Section 12 of the PWDVA for the application and Section 18 of the PWDVA for the order.",
    );
    assert.deepEqual(
      found.map((citation) => citation.number).sort(),
      ["12", "18"],
    );
  });

  it("collapses the same citation written two different ways", () => {
    const found = extractCitations("Section 85 BNS applies. As noted, BNS Section 85 applies.");
    assert.equal(found.length, 1);
  });

  it("does not invent a citation from an ordinary word", () => {
    // A generic letter class with the /i flag matched "under" as an Act name and
    // produced a phantom unverified citation beside every real one. This is the
    // regression test for that.
    const found = extractCitations("You may proceed under Section 85 BNS.");
    assert.equal(found.length, 1);
    assert.equal(found[0]?.status, "verified");
  });

  it("finds nothing in prose with no citation", () => {
    assert.deepEqual(extractCitations("Speak to a lawyer as soon as you can."), []);
  });
});

describe("verifying against the registry", () => {
  it("marks a real Act and section verified, with its plain-language text", () => {
    const citation = verifyCitation("Section 85 BNS", "BNS", "85");
    assert.equal(citation.status, "verified");
    assert.equal(citation.section?.heading, "Cruelty by husband or his relatives");
    assert.ok(citation.section?.plain.length ?? 0 > 0);
    assert.ok(citation.url?.includes("indiacode.nic.in"));
  });

  it("refuses to confirm a section the registry does not contain", () => {
    const citation = verifyCitation("Section 999 BNS", "BNS", "999");
    assert.equal(citation.status, "unknown-section");
    assert.ok(citation.caution?.includes("does not contain"));
  });

  it("links an unconfirmed section to the Act, never to the section", () => {
    // The dangerous failure would be a confident deep link to a provision that
    // may not exist. The Act always exists, so that is where the reader is sent.
    const citation = verifyCitation("Section 999 BNS", "BNS", "999");
    assert.ok(citation.url?.includes("indiacode.nic.in"));
    assert.ok(!citation.url?.includes("999"));
  });

  it("flags an Act it has never heard of", () => {
    const citation = verifyCitation("Section 5 of the Imaginary Act", "Imaginary Act", "5");
    assert.equal(citation.status, "unrecognised");
    assert.equal(citation.url, undefined);
  });

  it("catches a fabricated statute in running prose", () => {
    // Without a catch-all for statute-shaped names, a citation to an invented Act
    // drew no chip at all, and an unverifiable claim reached the reader unmarked.
    const found = extractCitations("Refer to Section 5 of the Fictional Protection Act 1999.");
    assert.equal(found.length, 1);
    assert.equal(found[0]?.status, "unrecognised");
  });

  it("resolves a sub-clause to its parent section rather than reporting it missing", () => {
    const citation = verifyCitation("Section 19(2) PWDVA", "PWDVA", "19(2)");
    assert.equal(citation.status, "verified");
    assert.equal(citation.section?.heading, "Residence orders");
    assert.ok(citation.caution?.includes("sub-clause"));
  });

  it("recognises the repealed codes as aliases of their replacements", () => {
    // Users and older material cite the IPC. Resolving it to the BNS is what lets
    // the registry verify a citation written in the old language.
    assert.equal(verifyCitation("Section 85 IPC", "IPC", "85").actId, "BNS");
    assert.equal(verifyCitation("Section 173 CrPC", "CrPC", "173").actId, "BNSS");
  });

  it("does not confuse BNSS with BNS", () => {
    // A longest-alias-first match is the only thing preventing "BNSS" being read
    // as "BNS" followed by a stray S.
    assert.equal(verifyCitation("Section 173 BNSS", "BNSS", "173").actId, "BNSS");
    assert.equal(verifyCitation("Section 303 BNS", "BNS", "303").actId, "BNS");
  });

  it("is case-insensitive about Act names", () => {
    assert.equal(verifyCitation("section 85 bns", "bns", "85").status, "verified");
  });
});

describe("auditing an answer", () => {
  it("counts verified and unverified separately", () => {
    const audit = auditCitations(
      "File under Section 85 BNS and Section 12 of the PWDVA. Also see Section 999 BNS.",
    );
    assert.equal(audit.verified, 2);
    assert.equal(audit.unverified, 1);
    assert.equal(audit.uncited, false);
  });

  it("reports an answer that cites nothing", () => {
    const audit = auditCitations("You should talk to a lawyer about this.");
    assert.equal(audit.uncited, true);
    assert.equal(audit.citations.length, 0);
  });

  it("is safe to run repeatedly on the same text", () => {
    // Patterns carry the /g flag, so a stale lastIndex between calls would make
    // the second audit of an answer silently miss citations.
    const text = "Section 85 BNS and Section 18 RERA apply.";
    const first = auditCitations(text);
    const second = auditCitations(text);
    assert.deepEqual(first.citations.length, second.citations.length);
    assert.equal(second.verified, 2);
  });

  it("does not hang on adversarial input", () => {
    // Catastrophic backtracking in a citation pattern would be a denial of
    // service reachable from any model response.
    const hostile = `Section ${"9".repeat(500)} of the ${"A".repeat(500)} Act`;
    const started = Date.now();
    auditCitations(hostile);
    assert.ok(Date.now() - started < 1_000, "citation parsing should stay fast on hostile input");
  });
});
