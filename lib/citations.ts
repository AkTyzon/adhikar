/**
 * Citation extraction and verification.
 *
 * The brief requires every cited section to become a live link to India Code.
 * That requirement has a sharp edge: a model that invents "Section 412 BNS"
 * produces a citation that *looks* exactly like a real one, and rendering it as a
 * confident hyperlink to an official government archive lends a fabrication the
 * authority of the State. For someone deciding whether to go to the police, that
 * is the most damaging failure this application could have.
 *
 * So citations are not trusted. Every reference the model emits is parsed and
 * checked against the registry in `lib/legal-db.ts`:
 *
 * - **verified** — the Act and the section both exist. Rendered as a link, with
 *   the registry's own plain-language description attached.
 * - **unknown-section** — the Act exists, the section is not in the registry.
 *   Rendered with a caution and linked to the *Act*, never to a section we cannot
 *   confirm exists.
 * - **unrecognised** — the Act itself is not in the registry.
 *
 * The registry is not a complete statute book, so "unknown" does not mean
 * "invented" — it means *we could not confirm it*, and the UI says exactly that.
 * Overclaiming in either direction would be the bug.
 */

import { ACTS, type Act, type ActId, type Section, getAct, getSection, indiaCodeUrl } from "./legal-db";

export type CitationStatus = "verified" | "unknown-section" | "unrecognised";

export interface Citation {
  /** The text as the model wrote it, e.g. "Section 85 BNS". */
  raw: string;
  /** Resolved Act, when the Act name was recognised. */
  actId?: ActId;
  act?: Act;
  /** Section number as written, upper-cased. */
  number?: string;
  status: CitationStatus;
  /** Registry entry. Present when status is "verified". */
  section?: Section;
  /** Where to send the reader. Undefined when nothing resolved. */
  url?: string;
  /** Shown beside the citation whenever there is a caveat. */
  caution?: string;
}

/**
 * Aliases the model (or a user) might use for each Act.
 *
 * Sorted longest-first at use, so "Consumer Protection Act" wins over a bare
 * "Act" and "BNSS" is not swallowed by "BNS".
 */
const ACT_ALIASES: ReadonlyArray<readonly [ActId, readonly string[]]> = [
  ["BNSS", ["bharatiya nagarik suraksha sanhita", "bnss", "crpc", "code of criminal procedure"]],
  ["BNS", ["bharatiya nyaya sanhita", "bns", "ipc", "indian penal code"]],
  ["PWDVA", ["protection of women from domestic violence act", "pwdva", "dv act", "domestic violence act"]],
  ["CPA", ["consumer protection act", "cpa", "consumer act"]],
  ["IT", ["information technology act", "it act"]],
  ["RERA", ["real estate (regulation and development) act", "real estate regulation and development act", "rera"]],
  ["RAILWAYS", ["indian railways act", "railways act", "railway act"]],
  ["WAGES", ["code on wages", "payment of wages act", "minimum wages act", "wages code"]],
  ["MTA", ["model tenancy act", "tenancy act", "mta"]],
  ["LSAA", ["legal services authorities act", "legal services act", "lsaa"]],
];

/** Every alias paired with its Act, longest alias first. */
const SORTED_ALIASES: ReadonlyArray<readonly [ActId, string]> = ACT_ALIASES.flatMap(([id, names]) =>
  names.map((name) => [id, name] as const),
).sort((a, b) => b[1].length - a[1].length);

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Act names as a regex alternation, built from the alias list.
 *
 * Deliberately not a generic letter class. An earlier version used `[A-Z]{2,5}`
 * with the `i` flag, which matches any two-to-five letter word — so "under
 * Section 85 BNS" parsed as an Act named "under", producing a phantom
 * unverified citation beside every real one. Only names the registry knows match.
 */
const ACT_NAME_ALTERNATION: string = SORTED_ALIASES.map(([, alias]) =>
  escapeRegExp(alias).replace(/\s+/g, "\\s+"),
).join("|");

/** Digits, an optional letter suffix, an optional sub-clause. */
const SECTION_NUMBER = String.raw`\d{1,3}[A-Za-z]{0,2}(?:\(\d+[a-z]?\))?`;

/**
 * The two orders a citation realistically appears in:
 *
 *     Section 85 BNS            Section 66D of the IT Act, 2000
 *     BNS Section 303           PWDVA s. 18
 *
 * A letter suffix and a sub-clause must survive intact: "66" and "66C" are
 * different offences, and "19(2)" is a specific sub-clause of section 19.
 */
const CITATION_PATTERNS: readonly RegExp[] = [
  new RegExp(
    String.raw`\b(?:sections?|sec\.?|s\.)\s*(${SECTION_NUMBER})\s*(?:of\s+)?(?:the\s+)?(${ACT_NAME_ALTERNATION})\b`,
    "gi",
  ),
  new RegExp(
    String.raw`\b(${ACT_NAME_ALTERNATION})\b(?:,?\s*\d{4})?[\s,]*(?:sections?|sec\.?|s\.)\s*(${SECTION_NUMBER})`,
    "gi",
  ),
  // Catch-all for statutes the registry does not know. Requires a statute-like
  // suffix (Act / Sanhita / Code / Adhiniyam / Rules), which is what keeps it
  // from matching ordinary words the way a bare letter class did -- "under" is
  // not a statute name, "Fictional Protection Act" is. Without this a citation
  // to an invented Act would draw no chip at all, and an unverifiable claim
  // would reach the reader with nothing marking it.
  new RegExp(
    String.raw`\b(?:[Ss]ections?|[Ss]ec\.?|[Ss]\.)\s*(${SECTION_NUMBER})\s+of\s+(?:[Tt]he\s+)?((?:[A-Z][\w()'-]*\s+){0,6}?(?:Act|Sanhita|Code|Adhiniyam|Rules|Regulations))\b`,
    "g",
  ),
];

function resolveActName(candidate: string): ActId | undefined {
  const needle = candidate
    .toLowerCase()
    .replace(/[,.]/g, " ")
    .replace(/\b(?:19|20)\d{2}\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!needle) return undefined;

  return SORTED_ALIASES.find(([, alias]) => needle === alias || needle.includes(alias))?.[0];
}

/** Parse every statutory reference out of a block of generated text. */
export function extractCitations(text: string): Citation[] {
  const found = new Map<string, Citation>();

  CITATION_PATTERNS.forEach((pattern, index) => {
    // Patterns carry /g, so reset before reuse across calls.
    pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      // Patterns 0 and 2 capture (number, act); pattern 1 captures (act, number).
      const numberRaw = index === 1 ? match[2] : match[1];
      const actRaw = index === 1 ? match[1] : match[2];
      if (!numberRaw || !actRaw) continue;

      const citation = verifyCitation(match[0].trim(), actRaw, numberRaw);
      // Key on resolved identity, so "Section 85 BNS" and "BNS Section 85"
      // collapse into a single entry.
      const key = citation.actId ? `${citation.actId}:${citation.number}` : citation.raw.toLowerCase();
      if (!found.has(key)) found.set(key, citation);
    }
  });

  return dropShadowedMatches([...found.values()]);
}

/**
 * Remove unresolved citations that are fragments of a resolved one.
 *
 * The catch-all pattern matches any statute-shaped name, so "Section 17 of the
 * Code" matches inside "Section 17 of the Code on Wages" and would otherwise be
 * reported as an unknown law beside the real, verified citation. A shorter match
 * that failed to resolve, wholly contained in a longer one that succeeded, is an
 * artefact of overlapping patterns rather than a second reference.
 */
function dropShadowedMatches(citations: Citation[]): Citation[] {
  const resolved = citations.filter((citation) => citation.actId);
  return citations.filter((citation) => {
    if (citation.actId) return true;
    return !resolved.some(
      (other) => other.raw.length > citation.raw.length && other.raw.includes(citation.raw),
    );
  });
}

/** Check one Act/section pair against the registry. */
export function verifyCitation(raw: string, actName: string, number: string): Citation {
  const actId = resolveActName(actName);
  const cleanNumber = number.trim().toUpperCase();

  if (!actId) {
    return {
      raw,
      number: cleanNumber,
      status: "unrecognised",
      caution: "This law is not in Adhikar's registry, so the reference could not be checked.",
    };
  }

  const act = getAct(actId)!;
  const exact = getSection(actId, cleanNumber);
  if (exact) {
    return { raw, actId, act, number: cleanNumber, status: "verified", section: exact, url: indiaCodeUrl(act) };
  }

  // "Section 19(2)" names a sub-clause of section 19. The registry stores whole
  // sections, so resolve to the parent and say the sub-clause was not checked
  // separately -- far more useful than reporting a real provision as missing.
  const parentNumber = /^(\d{1,3}[A-Za-z]{0,2})\(/.exec(cleanNumber)?.[1];
  const parent = parentNumber ? getSection(actId, parentNumber) : undefined;
  if (parent && parentNumber) {
    return {
      raw,
      actId,
      act,
      number: cleanNumber,
      status: "verified",
      section: parent,
      url: indiaCodeUrl(act),
      caution: `Section ${parentNumber} of the ${act.shortName} is confirmed. The sub-clause (${cleanNumber}) was not checked separately.`,
    };
  }

  return {
    raw,
    actId,
    act,
    number: cleanNumber,
    status: "unknown-section",
    // Link to the Act, never to a section we cannot confirm exists.
    url: indiaCodeUrl(act),
    caution: `Adhikar's registry does not contain Section ${cleanNumber} of the ${act.shortName}. It may still exist — check it on India Code before relying on it.`,
  };
}

export interface CitationAudit {
  citations: Citation[];
  verified: number;
  unverified: number;
  /** True when the answer cited nothing, which is itself worth surfacing. */
  uncited: boolean;
}

/**
 * Summarise the citations in an answer.
 *
 * Shown in the UI rather than kept internal: a reader deciding how much weight to
 * give an answer benefits from knowing that three of its four references check
 * out and one does not.
 */
export function auditCitations(text: string): CitationAudit {
  const citations = extractCitations(text);
  const verified = citations.filter((citation) => citation.status === "verified").length;
  return {
    citations,
    verified,
    unverified: citations.length - verified,
    uncited: citations.length === 0,
  };
}

/** Every Act in the registry, for the browse view. */
export function allActs(): readonly Act[] {
  return ACTS;
}
