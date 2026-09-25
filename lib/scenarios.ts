/**
 * Scenario quick-starts, with pre-written answers.
 *
 * Two reasons these answers are written out in full rather than generated:
 *
 * 1. **The brief requires the demo to work without an API key.** A judge who
 *    clones this repo and runs it with no credentials must see the real product,
 *    not an error state.
 * 2. **These five situations are the ones where a hallucination does most harm.**
 *    Someone searching "my husband is hitting me" needs the correct section of the
 *    PWDVA and the correct helpline, not a plausible-sounding approximation. For
 *    the highest-stakes paths, a human-checked answer beats a generated one, and
 *    every section cited below is in the registry, so the citation verifier marks
 *    all of them green.
 *
 * When a model *is* configured it still answers, because it can respond to the
 * user's actual situation rather than the generic case. These remain the floor.
 */

export interface Scenario {
  id: string;
  /** Short label for the chip. */
  label: string;
  /** Lucide icon name, resolved in the component. */
  icon: "shield" | "train" | "home" | "credit-card" | "briefcase";
  /** The question the chip fills into the search box. */
  question: string;
  /** Helpline numbers most relevant to this situation. */
  helplines: string[];
  /** Pre-written answer, used when no model is configured. Markdown. */
  fallbackAnswer: string;
}

export const SCENARIOS: readonly Scenario[] = [
  {
    id: "domestic-violence",
    label: "Domestic Safety",
    icon: "shield",
    question:
      "My husband and in-laws are physically abusing me. What immediate legal protections do I have?",
    helplines: ["112", "1091", "15100"],
    fallbackAnswer: `## Key takeaway

You do not have to leave your home, and you do not have to file a criminal case to get protection. The Protection of Women from Domestic Violence Act 2005 is a **civil** law that can give you a protection order within days, and the Magistrate can grant it before the other side is even heard.

If you are in immediate danger, call **112** now. For a women's helpline, call **1091**.

## What the law says

- **Section 3 of the PWDVA** defines domestic violence broadly. It is not limited to physical harm — verbal abuse, emotional abuse, and economic abuse such as withholding money or denying food all count.
- **Section 18 of the PWDVA** lets the Magistrate order the abuser to stop all violence, stop contacting you, and stay away from your workplace or your children's school.
- **Section 19 of the PWDVA** is the residence order. **You cannot be evicted from the shared household**, regardless of whose name the property is in. The Magistrate can instead order the abuser to leave.
- **Section 20 of the PWDVA** covers monetary relief: medical expenses, lost earnings, and maintenance.
- **Section 23 of the PWDVA** allows interim and ex-parte orders, which is what makes this a matter of days rather than years.
- **Section 85 of the BNS** makes cruelty by a husband or his relatives a criminal offence, punishable with up to three years' imprisonment. **Section 115 of the BNS** and **Section 117 of the BNS** cover causing hurt and grievous hurt.

## Step-by-step

1. **If you are in danger right now, call 112.** Everything else can wait.
2. **Get any injury documented.** Go to any government hospital and ask for a medico-legal case (MLC) record. This is free, and it becomes the strongest evidence you have.
3. **Contact the Protection Officer** for your district, appointed under the PWDVA. They can file your application for you and are obliged to help. Your District Legal Services Authority will have the contact.
4. **File an application under Section 12 of the PWDVA** before the Magistrate. Ask specifically for a protection order (s.18), a residence order (s.19), and interim relief (s.23).
5. **Ask for free legal aid.** Call **15100**. As a woman you are entitled to a free lawyer under Section 12 of the Legal Services Authorities Act, whatever your income.
6. **Preserve evidence** as you go: photographs, medical papers, messages, names of anyone who witnessed the abuse.

## What to keep in mind

A PWDVA application and a criminal complaint are separate, and you can pursue either or both. Many people start with the PWDVA because it is faster and aimed at stopping the violence rather than punishing after the fact.`,
  },
  {
    id: "train-seat",
    label: "Occupied Train Seat",
    icon: "train",
    question:
      "I booked a reserved train seat, but someone else is forcibly occupying it and refusing to move.",
    helplines: ["139"],
    fallbackAnswer: `## Key takeaway

Your reservation is a contract with the Railways, and someone occupying your reserved berth without authority is committing an offence. You do not have to negotiate — this is the Travelling Ticket Examiner's job, and if they will not act, the Railway Protection Force will.

**Call or message 139** (Rail Madad). It works on the train.

## What the law says

- **Section 155 of the Railways Act** makes it an offence to enter or remain in a reserved compartment or berth without authority, and to refuse to leave when asked by railway staff. The person can be removed and fined.
- **Section 162 of the Railways Act** is a specific offence for entering a compartment reserved for women.
- **Section 2(11) of the Consumer Protection Act** — if the Railways itself fails to give you the berth you paid for, that is a deficiency in service, and you can claim compensation.

## Step-by-step

1. **Find the TTE for your coach.** Show your ticket or the PNR on your phone. Allotting the berth is their duty, not a favour.
2. **If the TTE does not act, use 139.** Send a complaint with your PNR, coach and berth number. Rail Madad complaints are logged and tracked, which makes them harder to ignore than a verbal request.
3. **For RPF assistance, use the RPF helpline 182** or ask the TTE to call them. Refusing to vacate after being asked is where Section 155 bites.
4. **Record what happened** — the time, the coach, the TTE's name, and your complaint number.
5. **If you were denied the berth you paid for**, claim a refund through TDR on IRCTC, and if that is refused, file a consumer complaint on **E-Daakhil** (edaakhil.nic.in) under Section 35 of the Consumer Protection Act. You can file where you live.

## What to keep in mind

Keep it to the staff and the helpline rather than a confrontation. A logged complaint with a PNR is worth far more later than an argument in the aisle.`,
  },
  {
    id: "tenant-deposit",
    label: "Tenant Deposit",
    icon: "home",
    question: "My landlord is withholding my security deposit without valid cause.",
    helplines: ["15100"],
    fallbackAnswer: `## Key takeaway

A security deposit is your money held in trust, not the landlord's to keep. They may deduct only for what the agreement actually allows — unpaid rent and proven damage beyond normal wear. Keeping it without cause is recoverable.

**Important:** tenancy is a **State subject**, so which law applies depends on your State. Check whether your State has enacted the Model Tenancy Act 2021 or has its own Rent Control Act.

## What the law says

- **Section 11 of the Model Tenancy Act** caps the security deposit at two months' rent for residential premises and requires refund, less lawful deductions, when you hand back the premises. This applies **only in States that have enacted it**.
- **Section 32 of the Model Tenancy Act** creates a Rent Authority and Rent Court to decide these disputes quickly, instead of an ordinary civil suit.
- **Section 316 of the BNS** — criminal breach of trust. A deposit is property entrusted to the landlord, and dishonestly keeping it can amount to an offence. This is a serious step; use it as leverage sparingly and on advice.
- **Section 2(11) of the Consumer Protection Act** may apply where the landlord is a service provider such as a co-living or managed-rental company, though an ordinary individual landlord usually is not.

## Step-by-step

1. **Send a written demand.** Email or WhatsApp is fine. State the amount, the date you vacated, and give a clear deadline of 15 days. A written demand converts a disagreement into a documented one.
2. **Attach your evidence**: the tenancy agreement, deposit receipt or bank transfer record, the handover photographs, and the final meter readings.
3. **If there is no response, send a legal notice.** A lawyer will draft one cheaply, and many landlords pay at this stage rather than go further.
4. **Approach the Rent Authority** if your State has enacted the Model Tenancy Act, or the **Rent Controller** under your State's own rent law.
5. **Consider a Lok Adalat** under Section 22B of the Legal Services Authorities Act. No court fee, the award is binding, and it is often the fastest route for a money claim.
6. **Call 15100** if you need free legal aid and are eligible under Section 12 of the Legal Services Authorities Act.

## What to keep in mind

Take dated photographs of the empty property on the day you hand it over, every time. A dispute about the condition of a flat is almost always decided on whoever has the better record.`,
  },
  {
    id: "upi-fraud",
    label: "UPI Fraud",
    icon: "credit-card",
    question: "I got scammed on UPI and lost money. What is the emergency reporting window?",
    helplines: ["1930"],
    fallbackAnswer: `## Key takeaway

**Speed is everything. Call 1930 right now**, before reading the rest of this.

Two separate clocks are running. The first is practical: the money is moving between accounts, and the chance of freezing it falls sharply within hours. The second is legal: under the RBI's customer-protection framework, if you report an unauthorised electronic transaction to your bank **within three working days, your liability is zero**. Between four and seven working days it is limited. After that it depends on your bank's policy.

## What the law says

- **Section 66D of the IT Act** — cheating by personation using a computer resource. This is the main provision for UPI and online fraud, punishable with up to three years' imprisonment and a fine.
- **Section 66C of the IT Act** — identity theft, where your credentials or OTP were misused.
- **Section 43 of the IT Act** gives you a **civil claim for compensation** for unauthorised access to your account, separate from the criminal case.
- **Section 319 of the BNS** — cheating by personation. **Section 318 of the BNS** — cheating generally.
- **Section 173 of the BNSS** — police must register your FIR, and can do so regardless of where the fraud happened. This is what a **Zero FIR** means, and it matters because cyber fraud rarely happens in your own police station's jurisdiction.

## Step-by-step

1. **Call 1930** — the national cyber financial fraud helpline. This is the fastest route to getting the receiving account frozen.
2. **Report on cybercrime.gov.in** as well, under "Financial Fraud". Save the acknowledgement number.
3. **Tell your bank in writing immediately** — the app's in-built dispute form, plus an email. Written notice starts the three-working-day clock that decides your liability. A phone call alone leaves you with nothing to point to.
4. **Do not delete anything.** Keep the SMS, the UPI transaction ID, the UTR number, the payee's UPI handle, screenshots, and any call recordings.
5. **File an FIR** and insist on it. If the station says the fraud happened elsewhere, Section 173 of the BNSS lets them register a Zero FIR and transfer it. Get a free copy.
6. **Follow up with your bank's Nodal Officer**, and if unresolved in 30 days, escalate to the **RBI Ombudsman** (cms.rbi.org.in).

## What to keep in mind

Never share an OTP, UPI PIN or screen with anyone, including someone claiming to be from your bank or from support. No genuine bank process ever needs your PIN or remote access to your phone.`,
  },
  {
    id: "unpaid-salary",
    label: "Unpaid Salary",
    icon: "briefcase",
    question: "My employer hasn't paid my salary for 2 months and refuses to respond.",
    helplines: ["15100"],
    fallbackAnswer: `## Key takeaway

Unpaid wages are a statutory claim, not a favour to be negotiated. You do not need to file a civil suit: there is a dedicated claims authority, usually the Labour Commissioner, and it costs very little to approach.

## What the law says

- **Section 17 of the Code on Wages** requires wages to be paid on time — by the seventh day after the wage period for monthly-paid employees, and on the same or next day where your employment is terminated.
- **Section 45 of the Code on Wages** lets you file a claim for unpaid wages with the authority appointed by the Government, rather than going to a civil court.
- **Section 316 of the BNS** — criminal breach of trust may apply where deductions were made from your salary (such as PF or TDS) and not deposited.
- **Section 22B of the Legal Services Authorities Act** — a Lok Adalat can settle a money claim quickly, with no court fee and a binding award.

## Step-by-step

1. **Put the demand in writing.** Email your manager and HR together. State the months unpaid, the amount, and a deadline. Keep it factual. This single step converts "they refuse to respond" into evidence.
2. **Gather your record**: appointment letter, salary slips, bank statements showing earlier credits, attendance records, and any messages acknowledging the arrears.
3. **File a claim under Section 45 of the Code on Wages** with the Labour Commissioner for your area. Many States accept this online through the Shram Suvidha portal.
4. **If PF or ESI was deducted but not deposited**, complain to the EPFO (epfindia.gov.in) — this is often resolved faster than the wage claim itself, and it is a serious matter for the employer.
5. **Consider a Lok Adalat** for a quick binding settlement.
6. **Call 15100** for free legal aid. Industrial workmen are specifically entitled under Section 12 of the Legal Services Authorities Act.

## What to keep in mind

Resign carefully if you are considering it. Leaving without notice can give the employer a counter-argument about dues, so take advice on the sequence before you send a resignation.`,
  },
] as const;

const SCENARIO_INDEX = new Map(SCENARIOS.map((scenario) => [scenario.id, scenario]));

export function getScenario(id: string): Scenario | undefined {
  return SCENARIO_INDEX.get(id);
}

/**
 * Best pre-written answer for a free-text question, if one clearly applies.
 *
 * Used only when no model is configured. Matching is keyword overlap with a
 * deliberately high bar: showing a domestic-violence answer to someone asking
 * about a train seat would be worse than showing nothing, so an uncertain match
 * returns undefined and the UI explains that a model is not configured.
 */
export function matchScenario(question: string): Scenario | undefined {
  const text = question.toLowerCase();

  const signals: ReadonlyArray<readonly [string, readonly string[]]> = [
    [
      "domestic-violence",
      // "hit" rather than "hit me": people write "he keeps hitting me", and an
      // exact phrase match missed the most common phrasing there is.
      ["abus", "husband", "in-law", "beat", "hit", "slap", "hurt", "threaten", "domestic", "violence", "dowry", "cruel"],
    ],
    ["train-seat", ["train", "railway", "berth", "seat", "coach", "irctc", "pnr", "reserved"]],
    ["tenant-deposit", ["landlord", "deposit", "rent", "tenant", "vacat", "flat", "lease"]],
    ["upi-fraud", ["upi", "scam", "fraud", "cyber", "phish", "otp", "transaction", "bank", "money lost", "paytm", "gpay"]],
    [
      "unpaid-salary",
      // "notice period" was here and pulled in resignation questions, which this
      // answer does not address -- an employment-shaped question is not the same
      // as an unpaid-wages question, and the wrong answer is worse than none.
      ["salary", "wage", "unpaid", "employer", "boss", "epf", "provident fund"],
    ],
  ];

  let best: { id: string; hits: number } | undefined;
  for (const [id, keywords] of signals) {
    const hits = keywords.filter((keyword) => text.includes(keyword)).length;
    if (hits > 0 && (!best || hits > best.hits)) best = { id, hits };
  }

  // Two independent signals before claiming a match. One shared word ("bank",
  // "notice") is too thin a basis for showing a stranger a canned legal answer.
  return best && best.hits >= 2 ? SCENARIO_INDEX.get(best.id) : undefined;
}
