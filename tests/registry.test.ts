/**
 * Registry integrity.
 *
 * The registry is the thing citations are checked against, so a defect here
 * silently weakens every verification in the product. These tests assert the
 * structural invariants rather than the content of any one entry.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ACTS,
  HELPLINES,
  SECTIONS,
  getAct,
  getSection,
  indiaCodeUrl,
  searchRegistry,
  sectionsOf,
} from "../lib/legal-db";

describe("acts", () => {
  it("have unique ids", () => {
    const ids = ACTS.map((act) => act.id);
    assert.equal(new Set(ids).size, ids.length);
  });

  it("are all retrievable by id", () => {
    for (const act of ACTS) assert.equal(getAct(act.id)?.id, act.id);
  });

  it("all carry a plain-language summary", () => {
    for (const act of ACTS) {
      assert.ok(act.summary.length > 30, `${act.id} needs a real summary`);
      assert.ok(!/\bpursuant to\b|\bhereinafter\b/i.test(act.summary), `${act.id} summary uses legalese`);
    }
  });

  it("produce an India Code link over https", () => {
    for (const act of ACTS) {
      const url = new URL(indiaCodeUrl(act));
      assert.equal(url.protocol, "https:");
      assert.equal(url.hostname, "www.indiacode.nic.in");
    }
  });
});

describe("sections", () => {
  it("are unique per act", () => {
    const keys = SECTIONS.map((section) => `${section.actId}:${section.number}`);
    assert.equal(new Set(keys).size, keys.length);
  });

  it("all belong to an act that exists", () => {
    for (const section of SECTIONS) {
      assert.ok(getAct(section.actId), `${section.actId} is not a known Act`);
    }
  });

  it("are all retrievable, including case-insensitively", () => {
    for (const section of SECTIONS) {
      assert.ok(getSection(section.actId, section.number));
      assert.ok(getSection(section.actId, section.number.toLowerCase()));
    }
  });

  it("explain their effect in plain language", () => {
    for (const section of SECTIONS) {
      assert.ok(
        section.plain.length > 40,
        `${section.actId} s.${section.number} needs a usable explanation`,
      );
      assert.ok(section.heading.length > 3);
    }
  });

  it("record what the repealed codes called them", () => {
    // The BNS and BNSS replaced the IPC and CrPC in July 2024. Someone searching
    // older material needs the old number, so every entry in the new codes
    // carries its predecessor.
    for (const section of SECTIONS.filter((s) => s.actId === "BNS" || s.actId === "BNSS")) {
      assert.ok(
        section.previously,
        `${section.actId} s.${section.number} should record its IPC/CrPC equivalent`,
      );
    }
  });

  it("cover every act in the registry", () => {
    for (const act of ACTS) {
      assert.ok(sectionsOf(act.id).length > 0, `${act.id} has no sections and can verify nothing`);
    }
  });
});

describe("search", () => {
  it("returns every act for an empty query", () => {
    assert.equal(searchRegistry("").acts.length, ACTS.length);
  });

  it("finds a section by subject rather than by number", () => {
    const { sections } = searchRegistry("deposit");
    assert.ok(sections.length > 0);
  });

  it("matches an act by its old name", () => {
    const { acts } = searchRegistry("Indian Penal Code");
    assert.ok(acts.some((act) => act.id === "BNS"));
  });

  it("is case-insensitive", () => {
    assert.equal(searchRegistry("RERA").acts.length, searchRegistry("rera").acts.length);
  });

  it("returns nothing for a term that does not appear", () => {
    const { acts, sections } = searchRegistry("zzzznotalaw");
    assert.equal(acts.length, 0);
    assert.equal(sections.length, 0);
  });
});

describe("helplines", () => {
  it("are all numeric and short enough to dial", () => {
    for (const helpline of HELPLINES) {
      assert.match(helpline.number, /^\d{3,5}$/, `${helpline.number} is not a dialable shortcode`);
    }
  });

  it("include the four the brief requires", () => {
    const numbers = HELPLINES.map((helpline) => helpline.number);
    for (const required of ["112", "1091", "1930", "15100"]) {
      assert.ok(numbers.includes(required), `helpline ${required} is missing`);
    }
  });

  it("mark the emergency numbers as primary, for the always-visible bar", () => {
    const primary = HELPLINES.filter((helpline) => helpline.primary).map((h) => h.number);
    assert.deepEqual(primary.sort(), ["112", "fifteen"].slice(0, 0).concat(["112", "1091", "1930", "15100"].sort()));
  });
});
