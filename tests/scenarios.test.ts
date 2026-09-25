/**
 * Scenario matching and the offline fallback.
 *
 * The brief requires the demo to work with no API key. These answers are also the
 * highest-stakes content in the product — someone reading the domestic-violence
 * answer is in danger — so they are checked for correct citations and for the
 * presence of the right helpline, not merely for existing.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { auditCitations } from "../lib/citations";
import { SCENARIOS, getScenario, matchScenario } from "../lib/scenarios";

describe("scenario catalogue", () => {
  it("covers the five situations the brief names", () => {
    assert.equal(SCENARIOS.length, 5);
    for (const id of ["domestic-violence", "train-seat", "tenant-deposit", "upi-fraud", "unpaid-salary"]) {
      assert.ok(getScenario(id), `scenario ${id} is missing`);
    }
  });

  it("gives every scenario a substantial pre-written answer", () => {
    for (const scenario of SCENARIOS) {
      assert.ok(
        scenario.fallbackAnswer.length > 800,
        `${scenario.id} fallback is too thin to be useful offline`,
      );
    }
  });

  it("uses the structure the system prompt specifies", () => {
    for (const scenario of SCENARIOS) {
      assert.ok(scenario.fallbackAnswer.includes("## Key takeaway"), `${scenario.id} has no key takeaway`);
      assert.ok(scenario.fallbackAnswer.includes("## Step-by-step"), `${scenario.id} has no action plan`);
    }
  });

  it("cites only sections the registry can verify", () => {
    // A pre-written answer is human-checked, so every citation in it must be
    // green. An unverified chip here would mean the curated content is wrong.
    for (const scenario of SCENARIOS) {
      const audit = auditCitations(scenario.fallbackAnswer);
      assert.ok(audit.verified > 0, `${scenario.id} cites nothing`);
      assert.equal(
        audit.unverified,
        0,
        `${scenario.id} cites something unverifiable: ${audit.citations
          .filter((c) => c.status !== "verified")
          .map((c) => `${c.actId ?? "?"} s.${c.number}`)
          .join(", ")}`,
      );
    }
  });

  it("names its own helplines in the answer text", () => {
    for (const scenario of SCENARIOS) {
      for (const helpline of scenario.helplines) {
        assert.ok(
          scenario.fallbackAnswer.includes(helpline),
          `${scenario.id} lists helpline ${helpline} but never mentions it in the answer`,
        );
      }
    }
  });

  it("puts the emergency number in the urgent scenarios", () => {
    assert.ok(getScenario("domestic-violence")!.fallbackAnswer.includes("112"));
    assert.ok(getScenario("upi-fraud")!.fallbackAnswer.includes("1930"));
  });

  it("says that tenancy law varies by State", () => {
    // Tenancy is a State subject. Stating the Model Tenancy Act as a national
    // rule would be actively misleading.
    const answer = getScenario("tenant-deposit")!.fallbackAnswer;
    assert.match(answer, /State/);
  });
});

describe("matching a free-text question to a scenario", () => {
  it("matches each scenario from a natural phrasing", () => {
    const cases: ReadonlyArray<readonly [string, string]> = [
      ["my husband keeps hitting me and his family joins in", "domestic-violence"],
      ["someone is sitting in my reserved train berth and won't move", "train-seat"],
      ["my landlord refuses to return the deposit after I vacated", "tenant-deposit"],
      ["i lost money in a upi scam this morning", "upi-fraud"],
      ["my employer has not paid my salary for two months", "unpaid-salary"],
    ];
    for (const [question, expected] of cases) {
      assert.equal(matchScenario(question)?.id, expected, `failed on: ${question}`);
    }
  });

  it("declines to match on a single weak signal", () => {
    // Showing a stranger a canned domestic-violence answer because they used the
    // word "bank" would be far worse than showing nothing.
    assert.equal(matchScenario("what is a bank"), undefined);
    assert.equal(matchScenario("hello"), undefined);
  });

  it("returns nothing for a question outside all five scenarios", () => {
    assert.equal(matchScenario("how do I register a trademark for my logo"), undefined);
  });
});
