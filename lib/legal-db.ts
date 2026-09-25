/**
 * Indian legal registry.
 *
 * This file is the project's substantive knowledge, and it does two jobs:
 *
 * 1. It powers the browsable registry and the scenario answers.
 * 2. It is the **allow-list against which model citations are verified**
 *    (see `lib/citations.ts`). A model that cites "Section 999 BNS" produces a
 *    reference this registry does not contain, and the UI marks it unverified
 *    instead of rendering a confident link to nothing. That check is the reason
 *    the registry is exhaustive about the sections it does contain rather than
 *    illustrative.
 *
 * Accuracy notes, stated because this is law and being wrong has a cost:
 *
 * - The BNS/BNSS/BSA replaced the IPC/CrPC/Evidence Act with effect from
 *   1 July 2024. Offences committed before that date are still tried under the
 *   old codes, so `previously` records the IPC/CrPC equivalent for each entry.
 * - Tenancy is a State subject. The Model Tenancy Act 2021 is a *model* law that
 *   States adopt, amend or ignore; entries say so rather than implying it applies
 *   nationally.
 * - Section numbers were chosen conservatively. Where a mapping is contested or
 *   I am not confident, the entry is omitted rather than guessed at, because a
 *   plausible wrong section is worse for a user than no section.
 */

export type ActId =
  | "BNS"
  | "BNSS"
  | "PWDVA"
  | "CPA"
  | "IT"
  | "RERA"
  | "RAILWAYS"
  | "WAGES"
  | "MTA"
  | "LSAA";

export interface Act {
  id: ActId;
  /** Short name used in citations, e.g. "BNS". */
  shortName: string;
  /** Full statutory title. */
  title: string;
  year: number;
  /** What this Act replaced, if anything. */
  replaces?: string;
  /** One sentence a non-lawyer can act on. */
  summary: string;
  /** Broad area, used for filtering the registry. */
  domain: "criminal" | "procedure" | "family" | "consumer" | "cyber" | "property" | "labour" | "access";
}

export interface Section {
  actId: ActId;
  /** Section number as cited, e.g. "85" or "19(2)". */
  number: string;
  heading: string;
  /** Plain-language effect. Written for a reader with no legal training. */
  plain: string;
  /** Corresponding provision in the repealed code, where applicable. */
  previously?: string;
  /** Punishment or remedy, where the section provides one. */
  consequence?: string;
}

export const ACTS: readonly Act[] = [
  {
    id: "BNS",
    shortName: "BNS",
    title: "Bharatiya Nyaya Sanhita",
    year: 2023,
    replaces: "Indian Penal Code, 1860",
    summary:
      "India's main criminal code. Defines offences and their punishments. In force from 1 July 2024.",
    domain: "criminal",
  },
  {
    id: "BNSS",
    shortName: "BNSS",
    title: "Bharatiya Nagarik Suraksha Sanhita",
    year: 2023,
    replaces: "Code of Criminal Procedure, 1973",
    summary:
      "The procedure code: how a complaint becomes an FIR, how police investigate, arrest and bring a case to court.",
    domain: "procedure",
  },
  {
    id: "PWDVA",
    shortName: "PWDVA",
    title: "Protection of Women from Domestic Violence Act",
    year: 2005,
    summary:
      "A civil law giving women facing domestic violence access to protection orders, the right to stay in the shared home, and monetary relief — without needing to file a criminal case first.",
    domain: "family",
  },
  {
    id: "CPA",
    shortName: "Consumer Protection Act",
    title: "Consumer Protection Act",
    year: 2019,
    replaces: "Consumer Protection Act, 1986",
    summary:
      "Lets a consumer complain about a defective product or deficient service to a Consumer Commission, including online.",
    domain: "consumer",
  },
  {
    id: "IT",
    shortName: "IT Act",
    title: "Information Technology Act",
    year: 2000,
    summary:
      "Covers computer-related offences: hacking, identity theft, online cheating, and the duty to protect personal data.",
    domain: "cyber",
  },
  {
    id: "RERA",
    shortName: "RERA",
    title: "Real Estate (Regulation and Development) Act",
    year: 2016,
    summary:
      "Regulates builders and housing projects. Gives homebuyers a route to a refund with interest when possession is delayed.",
    domain: "property",
  },
  {
    id: "RAILWAYS",
    shortName: "Railways Act",
    title: "Railways Act",
    year: 1989,
    summary:
      "Governs rail travel, including reserved accommodation and penalties for unauthorised occupation of a reserved berth.",
    domain: "consumer",
  },
  {
    id: "WAGES",
    shortName: "Code on Wages",
    title: "Code on Wages",
    year: 2019,
    replaces: "Payment of Wages Act 1936, Minimum Wages Act 1948 and others",
    summary:
      "Requires wages to be paid on time and gives a worker a claims route to recover unpaid wages.",
    domain: "labour",
  },
  {
    id: "MTA",
    shortName: "Model Tenancy Act",
    title: "Model Tenancy Act",
    year: 2021,
    summary:
      "A model law on rental housing, including a cap on security deposits. Tenancy is a State subject, so this applies only in States that have enacted it — check your State's own rent law.",
    domain: "property",
  },
  {
    id: "LSAA",
    shortName: "Legal Services Authorities Act",
    title: "Legal Services Authorities Act",
    year: 1987,
    summary:
      "Creates NALSA and the District Legal Services Authorities, and sets out who is entitled to a free lawyer.",
    domain: "access",
  },
] as const;

export const SECTIONS: readonly Section[] = [
  // ------------------------------------------------------------ BNS (criminal)
  {
    actId: "BNS",
    number: "85",
    heading: "Cruelty by husband or his relatives",
    plain:
      "Makes it a crime for a husband or his relatives to subject a woman to cruelty. Cruelty includes both physical harm and conduct likely to drive her to self-harm, as well as harassment over dowry.",
    previously: "IPC 498A",
    consequence: "Up to 3 years' imprisonment and a fine.",
  },
  {
    actId: "BNS",
    number: "86",
    heading: "Meaning of cruelty",
    plain:
      "Defines cruelty for Section 85: wilful conduct likely to cause grave injury or drive a woman to suicide, and harassment aimed at extracting property or valuable security.",
    previously: "IPC 498A explanation",
  },
  {
    actId: "BNS",
    number: "115",
    heading: "Voluntarily causing hurt",
    plain: "Covers deliberately causing bodily pain, disease or infirmity to another person.",
    previously: "IPC 323",
    consequence: "Up to 1 year's imprisonment, or a fine, or both.",
  },
  {
    actId: "BNS",
    number: "117",
    heading: "Voluntarily causing grievous hurt",
    plain:
      "Applies where the injury is serious — for example a fracture, loss of sight or hearing, or any hurt that endangers life or leaves the person unable to follow their usual activities for twenty days.",
    previously: "IPC 325",
    consequence: "Up to 7 years' imprisonment and a fine.",
  },
  {
    actId: "BNS",
    number: "74",
    heading: "Assault or criminal force on a woman with intent to outrage her modesty",
    plain:
      "Covers assault or use of criminal force against a woman intending to outrage, or knowing it likely to outrage, her modesty.",
    previously: "IPC 354",
    consequence: "1 to 5 years' imprisonment and a fine.",
  },
  {
    actId: "BNS",
    number: "351",
    heading: "Criminal intimidation",
    plain:
      "Threatening someone with injury to their person, reputation or property in order to make them do something they are not legally bound to do, or to frighten them.",
    previously: "IPC 503 and 506",
    consequence: "Up to 2 years' imprisonment, or a fine, or both; more if the threat is of death or grievous hurt.",
  },
  {
    actId: "BNS",
    number: "303",
    heading: "Theft",
    plain: "Dishonestly taking movable property out of someone's possession without their consent.",
    previously: "IPC 378 and 379",
    consequence: "Up to 3 years' imprisonment, or a fine, or both.",
  },
  {
    actId: "BNS",
    number: "316",
    heading: "Criminal breach of trust",
    plain:
      "Applies where someone entrusted with property or money dishonestly uses it for themselves or disposes of it against the terms on which it was entrusted.",
    previously: "IPC 405 and 406",
    consequence: "Up to 5 years' imprisonment and a fine.",
  },
  {
    actId: "BNS",
    number: "318",
    heading: "Cheating",
    plain:
      "Deceiving someone to make them deliver property or consent to someone keeping it, or to do something they would not otherwise have done, causing them damage.",
    previously: "IPC 415 and 420",
    consequence: "Up to 7 years' imprisonment and a fine where property is delivered.",
  },
  {
    actId: "BNS",
    number: "319",
    heading: "Cheating by personation",
    plain:
      "Cheating while pretending to be someone else — the provision most often used alongside the IT Act in online and UPI fraud.",
    previously: "IPC 416 and 419",
    consequence: "Up to 5 years' imprisonment and a fine.",
  },

  // --------------------------------------------------------- BNSS (procedure)
  {
    actId: "BNSS",
    number: "173",
    heading: "Information in cognizable cases",
    plain:
      "The FIR provision. Police must record information about a cognizable offence. It can be given orally or electronically, and it must be registered regardless of where the offence took place — this is what makes a 'Zero FIR' possible. You are entitled to a free copy.",
    previously: "CrPC 154",
  },
  {
    actId: "BNSS",
    number: "175",
    heading: "Power of police to investigate a cognizable case",
    plain:
      "Lets police investigate a cognizable offence without a magistrate's order, and lets a magistrate direct an investigation if police refuse.",
    previously: "CrPC 156",
  },
  {
    actId: "BNSS",
    number: "193",
    heading: "Report of police officer on completion of investigation",
    plain:
      "The chargesheet. Police must file this within a set period, and you can ask about its status.",
    previously: "CrPC 173",
  },
  {
    actId: "BNSS",
    number: "35",
    heading: "When police may arrest without warrant",
    plain:
      "Sets out the limited circumstances in which police can arrest without a warrant, and requires them to record reasons where they do not arrest.",
    previously: "CrPC 41",
  },
  {
    actId: "BNSS",
    number: "47",
    heading: "Person arrested to be informed of grounds of arrest",
    plain:
      "Anyone arrested must be told why, and is entitled to bail information where the offence is bailable.",
    previously: "CrPC 50",
  },
  {
    actId: "BNSS",
    number: "58",
    heading: "Person arrested not to be detained more than twenty-four hours",
    plain:
      "Police cannot hold someone for more than 24 hours without producing them before a magistrate.",
    previously: "CrPC 57",
  },
  {
    actId: "BNSS",
    number: "144",
    heading: "Order for maintenance of wives, children and parents",
    plain:
      "A quick route to a monthly maintenance order against someone who is neglecting a wife, child or parent unable to maintain themselves.",
    previously: "CrPC 125",
  },
  {
    actId: "BNSS",
    number: "183",
    heading: "Recording of confessions and statements",
    plain:
      "How a magistrate records statements, including the safeguards for a woman survivor's statement.",
    previously: "CrPC 164",
  },

  // ------------------------------------------------------------------ PWDVA
  {
    actId: "PWDVA",
    number: "3",
    heading: "Definition of domestic violence",
    plain:
      "Defines domestic violence broadly: physical, sexual, verbal, emotional and economic abuse. Withholding money, denying food, or persistent insults all count — it is not limited to physical harm.",
  },
  {
    actId: "PWDVA",
    number: "12",
    heading: "Application to Magistrate",
    plain:
      "How you start a case: an application to the Magistrate, which can be filed by you, a Protection Officer or someone on your behalf. The Magistrate is expected to fix a first hearing within three days.",
  },
  {
    actId: "PWDVA",
    number: "18",
    heading: "Protection orders",
    plain:
      "The Magistrate can order the respondent to stop all violence, stop contacting you, stay away from your workplace or your child's school, and not dispose of your assets.",
  },
  {
    actId: "PWDVA",
    number: "19",
    heading: "Residence orders",
    plain:
      "You cannot be evicted from the shared household, whatever the ownership. The Magistrate can order the respondent to leave, or to provide you alternative accommodation of the same standard.",
  },
  {
    actId: "PWDVA",
    number: "20",
    heading: "Monetary relief",
    plain:
      "Covers loss of earnings, medical expenses, loss caused by destruction of property, and maintenance for you and your children.",
  },
  {
    actId: "PWDVA",
    number: "21",
    heading: "Custody orders",
    plain: "Temporary custody of your children can be granted to you while the case runs.",
  },
  {
    actId: "PWDVA",
    number: "22",
    heading: "Compensation orders",
    plain: "Compensation for mental torture and emotional distress caused by the violence.",
  },
  {
    actId: "PWDVA",
    number: "23",
    heading: "Power to grant interim and ex-parte orders",
    plain:
      "The Magistrate can grant urgent protection before the other side is heard — which is what makes this a same-week remedy rather than a years-long case.",
  },
  {
    actId: "PWDVA",
    number: "31",
    heading: "Penalty for breach of protection order",
    plain: "Breaching a protection order is itself a criminal offence.",
    consequence: "Up to 1 year's imprisonment, or a fine up to ₹20,000, or both.",
  },

  // ------------------------------------------------------- Consumer Protection
  {
    actId: "CPA",
    number: "2(11)",
    heading: "Deficiency in service",
    plain:
      "Any fault, shortcoming or inadequacy in the quality or manner of a service that has been promised. This is the provision most complaints rest on.",
  },
  {
    actId: "CPA",
    number: "2(47)",
    heading: "Unfair trade practice",
    plain:
      "Covers misleading claims, false representations, and refusing to return a deposit or issue a bill.",
  },
  {
    actId: "CPA",
    number: "34",
    heading: "Jurisdiction of the District Commission",
    plain:
      "The District Commission hears complaints where the value of goods or services paid does not exceed ₹50 lakh. You can file where you live or work, not only where the seller is.",
  },
  {
    actId: "CPA",
    number: "35",
    heading: "Manner of making a complaint",
    plain:
      "How to file, including electronically. There is no requirement to engage a lawyer, and fees are nominal.",
  },
  {
    actId: "CPA",
    number: "38",
    heading: "Procedure on admission of complaint",
    plain:
      "The Commission is expected to decide a complaint within three months where no expert analysis is needed, and five months where it is.",
  },
  {
    actId: "CPA",
    number: "39",
    heading: "Findings of the District Commission",
    plain:
      "What the Commission can order: repair, replacement, a refund, compensation for loss or injury, removal of the deficiency, and costs.",
  },
  {
    actId: "CPA",
    number: "47",
    heading: "Jurisdiction of the State Commission",
    plain: "Hears complaints above ₹50 lakh and up to ₹2 crore, and appeals from District Commissions.",
  },

  // ------------------------------------------------------------------ IT Act
  {
    actId: "IT",
    number: "43",
    heading: "Penalty for damage to a computer or computer system",
    plain:
      "Gives you a civil claim for compensation where someone accesses your account or data without permission — including unauthorised transactions.",
  },
  {
    actId: "IT",
    number: "66",
    heading: "Computer-related offences",
    plain: "Makes dishonest or fraudulent conduct of the kind described in Section 43 a criminal offence.",
    consequence: "Up to 3 years' imprisonment, or a fine up to ₹5 lakh, or both.",
  },
  {
    actId: "IT",
    number: "66C",
    heading: "Identity theft",
    plain:
      "Dishonestly using someone else's password, digital signature or other unique identification.",
    consequence: "Up to 3 years' imprisonment and a fine up to ₹1 lakh.",
  },
  {
    actId: "IT",
    number: "66D",
    heading: "Cheating by personation using a computer resource",
    plain:
      "The core provision for online and UPI fraud: cheating someone by pretending to be another person using a phone or computer.",
    consequence: "Up to 3 years' imprisonment and a fine up to ₹1 lakh.",
  },
  {
    actId: "IT",
    number: "43A",
    heading: "Compensation for failure to protect data",
    plain:
      "A body corporate that handles your sensitive personal data negligently and causes you loss must compensate you.",
  },
  {
    actId: "IT",
    number: "72",
    heading: "Breach of confidentiality and privacy",
    plain:
      "Penalises someone who, having access to records under the Act, discloses them without consent.",
  },

  // -------------------------------------------------------------------- RERA
  {
    actId: "RERA",
    number: "13",
    heading: "No deposit or advance without an agreement for sale",
    plain:
      "A builder cannot take more than 10% of the cost of the flat as an advance before signing a registered agreement for sale.",
  },
  {
    actId: "RERA",
    number: "18",
    heading: "Return of amount and compensation",
    plain:
      "If the builder fails to give possession by the promised date, you can either withdraw and get your money back with interest, or stay in the project and claim interest for every month of delay.",
  },
  {
    actId: "RERA",
    number: "12",
    heading: "Obligations of the promoter regarding advertisement or prospectus",
    plain:
      "If you paid relying on something in a brochure or advertisement that turns out to be false, you are entitled to compensation, and to withdraw with a full refund plus interest.",
  },
  {
    actId: "RERA",
    number: "31",
    heading: "Filing of complaints with the Authority",
    plain:
      "How to complain to your State's RERA Authority against a builder or agent. Most States accept online filing.",
  },

  // --------------------------------------------------------------- Railways
  {
    actId: "RAILWAYS",
    number: "155",
    heading: "Entering a compartment reserved, or resisting lawful entry",
    plain:
      "Makes it an offence to enter or remain in a reserved compartment or berth without authority, and to refuse to leave when asked by railway staff.",
    consequence: "A fine, and the person may be removed from the compartment.",
  },
  {
    actId: "RAILWAYS",
    number: "162",
    heading: "Entering a compartment reserved for women",
    plain: "A specific offence of entering a compartment set apart for women without authority.",
    consequence: "Up to 3 months' imprisonment, or a fine up to ₹500, or both.",
  },

  // ------------------------------------------------------------ Code on Wages
  {
    actId: "WAGES",
    number: "17",
    heading: "Time limit for payment of wages",
    plain:
      "Wages must be paid on time: by the 7th day after the wage period for monthly-paid employees, and on the same or next day where employment is terminated.",
  },
  {
    actId: "WAGES",
    number: "45",
    heading: "Claims arising under this Code",
    plain:
      "Lets you file a claim for unpaid wages with the authority appointed by the Government — usually the Labour Commissioner — rather than going to a civil court.",
  },

  // ------------------------------------------------------- Model Tenancy Act
  {
    actId: "MTA",
    number: "11",
    heading: "Security deposit",
    plain:
      "Caps the security deposit at two months' rent for residential premises, and requires the landlord to refund it (less lawful deductions) when you hand back the premises. Applies only in States that have enacted the Model Tenancy Act.",
  },
  {
    actId: "MTA",
    number: "32",
    heading: "Rent Authority and Rent Court",
    plain:
      "Creates a dedicated Rent Authority and Rent Court to decide tenancy disputes quickly, instead of an ordinary civil suit.",
  },

  // ------------------------------------------------- Legal Services Authorities
  {
    actId: "LSAA",
    number: "12",
    heading: "Criteria for giving legal services",
    plain:
      "Sets out who gets a free lawyer as a right: women and children, members of Scheduled Castes and Scheduled Tribes, victims of trafficking, persons with disabilities, industrial workmen, people in custody, victims of mass disaster or violence, and anyone whose annual income is below the limit their State has set.",
  },
  {
    actId: "LSAA",
    number: "22B",
    heading: "Lok Adalats and permanent Lok Adalats",
    plain:
      "A settlement forum whose award is binding and cannot be appealed. Often the fastest route for a money claim, and there is no court fee.",
  },
] as const;

// --------------------------------------------------------------------------- //
// Helplines
// --------------------------------------------------------------------------- //

export interface Helpline {
  number: string;
  name: string;
  detail: string;
  /** Shown in the persistent emergency bar rather than only in the footer. */
  primary?: boolean;
}

export const HELPLINES: readonly Helpline[] = [
  {
    number: "112",
    name: "National Emergency",
    detail: "Police, fire and ambulance. Works from any phone across India.",
    primary: true,
  },
  {
    number: "1091",
    name: "Women Helpline",
    detail: "24-hour assistance for women in distress.",
    primary: true,
  },
  {
    number: "1930",
    name: "Cyber Financial Fraud",
    detail:
      "Report online financial fraud. Call as soon as you notice — the chance of freezing the money falls sharply after the first hours.",
    primary: true,
  },
  {
    number: "15100",
    name: "NALSA Free Legal Aid",
    detail: "Free legal advice and a lawyer at state expense if you are eligible under Section 12 LSAA.",
    primary: true,
  },
  { number: "1098", name: "Childline", detail: "For children in need of care and protection." },
  { number: "181", name: "Women Helpline (alternate)", detail: "State women's helpline in many States." },
  { number: "139", name: "Rail Madad", detail: "Indian Railways complaints and on-board assistance." },
  { number: "14567", name: "Elderline", detail: "Helpline for senior citizens." },
] as const;

// --------------------------------------------------------------------------- //
// Lookup helpers
// --------------------------------------------------------------------------- //

const ACT_INDEX: Map<ActId, Act> = new Map(ACTS.map((act) => [act.id, act]));

/** Sections keyed by `ACTID:number`, the canonical citation key. */
const SECTION_INDEX: Map<string, Section> = new Map(
  SECTIONS.map((section) => [sectionKey(section.actId, section.number), section]),
);

export function sectionKey(actId: ActId, number: string): string {
  return `${actId}:${number.trim().toUpperCase()}`;
}

export function getAct(actId: ActId): Act | undefined {
  return ACT_INDEX.get(actId);
}

export function getSection(actId: ActId, number: string): Section | undefined {
  return SECTION_INDEX.get(sectionKey(actId, number));
}

export function sectionsOf(actId: ActId): Section[] {
  return SECTIONS.filter((section) => section.actId === actId);
}

/**
 * Official source link for an Act.
 *
 * Deliberately a search URL on India Code rather than a deep `handle/` link.
 * Handle identifiers are opaque and a wrong one 404s, which is worse than a
 * search that always resolves — and the whole point of citing is that the reader
 * can go and check.
 */
export function indiaCodeUrl(act: Act): string {
  const query = encodeURIComponent(`${act.title} ${act.year}`);
  return `https://www.indiacode.nic.in/simple-search?query=${query}`;
}

/** Free-text search across acts and sections, for the registry tab. */
export function searchRegistry(query: string): { acts: Act[]; sections: Section[] } {
  const needle = query.trim().toLowerCase();
  if (!needle) return { acts: [...ACTS], sections: [] };

  const acts = ACTS.filter((act) =>
    [act.shortName, act.title, act.summary, act.replaces ?? "", act.domain]
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );

  const sections = SECTIONS.filter((section) => {
    const act = ACT_INDEX.get(section.actId);
    return [
      section.number,
      section.heading,
      section.plain,
      section.previously ?? "",
      act?.shortName ?? "",
      act?.title ?? "",
    ]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });

  return { acts, sections };
}
