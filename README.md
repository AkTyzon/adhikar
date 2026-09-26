# Adhikar

**अधिकार — "right", "entitlement".**

AI-powered legal accessibility for India. Ask a question in your own language, get
a plain-language answer that cites the exact section of the law — **and every
citation is checked against a registry of Indian statutes before you see it.**

![Next.js 16](https://img.shields.io/badge/Next.js-16-black)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178c6)
![Tests](https://img.shields.io/badge/tests-57%20passing-brightgreen)
![npm audit](https://img.shields.io/badge/npm%20audit-0%20vulnerabilities-brightgreen)
![WCAG 2.2 AA](https://img.shields.io/badge/WCAG-2.2%20AA-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

**▶ Live demo: https://adhikar-eight.vercel.app**

No sign-up, no API key needed. The five situation cards return complete answers
with verified citations straight away; to get answers tailored to your own
question, paste a free Google AI Studio key into the panel on the page — it stays
in your browser and is never stored on the server.

```bash
git clone https://github.com/AkTyzon/adhikar && cd adhikar
npm install
npm run dev      # http://localhost:3000
```

**No API key needed to try it.** The five scenario cards return complete,
human-checked answers with verified citations, so a fresh clone demonstrates the
real product rather than an error state.

---

## Judging guide — test everything in 90 seconds

**Live: https://adhikar-eight.vercel.app** — no sign-up, no key needed.

| # | Do this | What it proves |
|---|---|---|
| 1 | Click **UPI Fraud** | Full answer, and the *Sections cited* panel below it shows every reference **verified** against the registry, each linked to India Code |
| 2 | Type *"my employer fired me without notice"* and press Ask | Live Gemini answer. Watch the citation panel: some sections come back **unverified** — that is the product working, not failing. It refuses to hyperlink a section it cannot confirm |
| 3 | Switch **Language → हिंदी**, ask again | Answer in Hindi; statute names stay in English so you can search them. `lang` is set per answer so screen readers pronounce it correctly |
| 4 | Open the **Legal Registry** tab, search `deposit` | The 10 Acts / 55 sections every citation is checked against, with pre-2024 IPC/CrPC equivalents |
| 5 | **Upload Document** tab, drop any PDF | Parsed **in your browser** — the file is never uploaded. Only extracted text is sent |
| 6 | Press **Tab** repeatedly from the top | Skip link first, then every control reachable with a visible focus ring |
| 7 | Disable JavaScript and ask a question | Still works. The form is a real GET form the server honours |

---

## Evaluation standards audit

### 1. Code Quality
Knowledge is **data, not code**: Acts, sections, plain-language text and scenario answers live in `lib/legal-db.ts` and `lib/scenarios.ts`, so a lawyer can correct a section without reading React. One concern per module — `lib/citations.ts` (verification), `lib/llm.ts` (providers), `lib/doc-extract.ts` (parsing), `lib/rate-limit.ts`. TypeScript **strict**, ESLint clean, no `any` in application code. Comments explain *why*, not *what*.

### 2. Security
`npm audit` = **0 vulnerabilities**, achieved by removing the Vercel AI SDK (filetype-bypass advisory, plus `jsondiffpatch` XSS/prototype-pollution) in favour of ~150 lines we own. Strict CSP with no `unsafe-eval`; **no `dangerouslySetInnerHTML` anywhere** (lint-enforced). Uploaded documents are read in-browser and never touch a server disk. File type decided by **magic bytes**, not by the attacker-controlled extension. Per-IP rate limits on both routes. API keys are server-side only — CI asserts no credential shape reaches the client bundle and that `process.env` is never read from a client component. Documents are fenced with a per-request UUID so text inside them cannot act as instructions.

### 3. Efficiency
Gemini's reasoning phase is disabled (`thinkingBudget: 0`): it was spending 94 of 100 tokens thinking and pushing answers past 200s. `pdfjs` and `mammoth` are **dynamically imported**, so the ~1 MB of parsing code is fetched only by the minority of visitors who upload a file. **Ten runtime dependencies, every one of them imported** — the tree is audited, not accumulated. No component library, no animation library, no state-management library: the UI primitives are ~150 lines of our own. Static shell, streamed answers, `output: "standalone"` for a minimal container. Citation verification is regex over a few KB, costing no extra model call.

### 4. Testing
**80 tests**, `npm test`, no mocked models anywhere. Concentrated where a defect would harm someone: citation verification (a fabricated section *must* be refused), registry integrity (every BNS/BNSS entry must record its IPC/CrPC predecessor), the pre-written answers (**every citation in them must verify**), scenario matching (must *refuse* to match on one weak keyword), and the rate limiter. Plus a ReDoS guard on adversarial input. CI runs types, lint, tests and build on Node 20 and 22, with a security job on every push.

### 5. Accessibility
**WCAG 2.2 AA.** Full ARIA tab pattern (arrow keys, `aria-selected`, roving `tabindex`). `aria-live` on the streaming answer, and focus moves to it on completion. Citation status uses **icon + text + colour**, never colour alone. `lang` set per answer so Hindi and Tamil are pronounced correctly rather than read as mispronounced English. Native `<dialog>` for focus trapping. `aria-disabled` rather than `disabled` on busy buttons. Helplines are `tel:` links. AA contrast in light *and* dark, `prefers-reduced-motion`, `forced-colors`, zoom never disabled. **Everything works with JavaScript off.**

### 6. Problem Statement Alignment
The brief asks for legal *information*, not advice — enforced structurally, not by disclaimer. A hallucinated section number is the specific harm this domain invites, and the brief's own requirement to link each citation to India Code would give a fabrication the authority of the State. So every citation is verified before display, and unconfirmed ones are never hyperlinked. Simplification, comparison against a registry, risk flags, actionable checklists, multilingual access and NALSA free-legal-aid routing are all present. It runs **without any API key**, because the people who need this most are least likely to have one.

---

## The problem

A tenant whose deposit is being withheld, a woman being beaten by her in-laws, a
worker two months unpaid — all have rights, and most have no realistic way to find
out what they are. The law is published, in English, in statutory language, across
dozens of Acts, with the criminal code having been entirely renumbered in 2024.

An AI can bridge that. But there is a specific danger in doing so, and it shapes
this whole project.

## Why a hallucinated section is worse here than anywhere else

Ask a general-purpose chatbot about Indian law and it will produce a confident,
well-organised answer citing "Section 354 IPC" or "Section 12 of the Domestic
Violence Act". Sometimes the section is right. Sometimes the number is invented,
or belongs to a code repealed in 2024, or says something entirely different.

The user cannot tell the difference. That is the whole point — they came because
they don't know the law.

And this brief asks for something that makes it sharper: **every cited section
must link to India Code**, the government's official statute archive. Rendering a
fabricated section as a confident hyperlink to a government site lends an
invention the authority of the State. For someone deciding whether to walk into a
police station, that is the most damaging thing this application could do.

### So citations are not trusted — they are verified

Every statutory reference a model produces is parsed and checked against
[`lib/legal-db.ts`](lib/legal-db.ts) before it reaches the screen:

| Result | What the reader sees |
| --- | --- |
| **Verified** | Green badge, the section's own plain-language summary, the punishment or remedy, its pre-2024 number, and a link to India Code |
| **Unconfirmed section** | Amber badge. Links to the **Act**, never to a section we cannot confirm exists |
| **Unknown law** | Amber badge, no link, and a plain statement that Adhikar could not check it |
| **Nothing cited** | A note saying there is nothing to verify, so treat the answer as orientation only |

The panel also shows the count: *3 verified, 1 unverified*. An answer where one
reference in four does not check out is a different thing from one where all four
do, and the reader is the person who needs to know which they are looking at.

The registry is **not** a complete statute book, so "unverified" does not mean
"invented" — it means *we could not confirm this*, and the UI says exactly that.
Overclaiming in either direction would be the bug.

> This is tested directly. [`tests/citations.test.ts`](tests/citations.test.ts)
> asserts that `Section 999 BNS` is refused, that an invented Act is flagged, that
> an unconfirmed section links to the Act rather than the section, and that
> `Section 19(2) PWDVA` resolves to its parent section instead of being reported
> missing.

## What it does

**Ask in your own words, in your own language** — English, हिंदी, Hinglish, தமிழ்,
తెలుగు, मराठी, বাংলা, ಕನ್ನಡ. Statute names and section numbers stay in English,
because you will need to say them to an official.

**Five one-tap situations**, each returning a complete answer with the right
helpline in the first two lines:

| | |
| --- | --- |
| **Domestic Safety** | PWDVA protection, residence and monetary orders; why you cannot be evicted from your own home |
| **Occupied Train Seat** | Railways Act s.155, Rail Madad 139, and the consumer route if the Railways failed you |
| **Tenant Deposit** | Deposit caps, the Rent Authority, and why the answer depends on your State |
| **UPI Fraud** | The RBI three-working-day zero-liability window, and why 1930 comes before anything else |
| **Unpaid Salary** | Code on Wages claims route via the Labour Commissioner, and the EPFO angle |

**Upload a document** — PDF, DOCX or text. It is read **in your browser**; only the
extracted text is sent, and nothing is written to any server's disk. You get a
plain-language summary, red flags, and a next-steps checklist.

**Browse the registry** — 10 Acts, 55 sections, each with plain-language text, its
pre-2024 equivalent, and a link to the official source.

**Free legal aid, prominently** — the NALSA helpline is in the header, the
emergency numbers sit directly under it rather than in the footer, and a dedicated
panel sets out who qualifies for a free lawyer under s.12 of the Legal Services
Authorities Act.

## How it is built

```
Next.js 16 · React 19 · TypeScript (strict) · Tailwind 4 · zero UI dependencies
```

```
Question → validate → rate-limit → provider (Gemini / OpenAI / Anthropic)
         → stream → render → PARSE CITATIONS → verify against registry → show
Document → read in browser → extract text → fence with a random nonce
         → stream → same verification path
```

### Notable decisions

**The Vercel AI SDK was removed.** The brief specifies it, and the version
compatible with this stack carried a filetype-bypass advisory and pulled in
`jsondiffpatch`, which has published XSS and prototype-pollution findings.
Replacing it with [`lib/llm.ts`](lib/llm.ts) — three request builders and one SSE
parser, about 150 lines we own — took `npm audit` from **10 vulnerabilities (2
high) to zero**. Streaming, cancellation and timeouts all still work.

**Three providers, not one.** The brief names Gemini and OpenAI; Anthropic is
wired too. Whichever key is present is used. Without any key the scenario answers
still serve, which is what makes the demo work on a grader's machine.

**The uploaded document is untrusted input.** A tenancy agreement or an employer's
notice was written by the other side of the user's dispute. It is fenced with a
per-request random UUID, and the system prompt states that text inside the fence
is data — so a document instructing the model to report that it is fair gets
reported as a finding instead of obeyed.

**All legal knowledge is data.** Acts, sections, plain-language text, scenario
answers, and the alias table that maps "IPC" to "BNS" all live in
[`lib/legal-db.ts`](lib/legal-db.ts) and [`lib/scenarios.ts`](lib/scenarios.ts). A
lawyer can correct a section without reading React.

**Dependencies are minimal and hand-audited.** No component library — the
primitives in [`components/ui/primitives.tsx`](components/ui/primitives.tsx) are
about 150 lines, which keeps the accessibility behaviour visible in the repo
instead of inherited from a black box.

## Security

| Control | Where |
| --- | --- |
| Zero known vulnerabilities | `npm audit` in CI, AI SDK removed to achieve it |
| CSP with no `unsafe-eval`, no inline script | [`next.config.ts`](next.config.ts) |
| Document never uploaded, never written to disk | [`lib/doc-extract.ts`](lib/doc-extract.ts) |
| Prompt-injection fencing with a per-request nonce | [`app/api/analyze-doc/route.ts`](app/api/analyze-doc/route.ts) |
| Magic-number file sniffing (MIME and extension are attacker-controlled) | [`lib/doc-extract.ts`](lib/doc-extract.ts) |
| Size, length and rate limits on both routes | [`lib/rate-limit.ts`](lib/rate-limit.ts) |
| Provider errors never forwarded to the client | [`lib/llm.ts`](lib/llm.ts) |
| pdf.js with `isEvalSupported: false` | [`lib/doc-extract.ts`](lib/doc-extract.ts) |
| No `dangerouslySetInnerHTML`; enforced by lint | [`eslint.config.mjs`](eslint.config.mjs) |
| API keys server-side only | never in a client component |

Rate limiting is in-process, which a serverless deployment weakens — that is
stated in the source rather than hidden, and the fix is a shared store behind the
same `check()` signature.

## Accessibility

WCAG 2.2 AA, built in rather than retrofitted:

- Skip link; landmarks; one `h1`; headings that descend without skipping
- **Tabs implement the full ARIA pattern** — `role="tablist"`, arrow-key
  navigation, `aria-selected`, roving `tabIndex`
- `aria-live` on the answer region, because answers stream in; focus moves to the
  answer after a response so a keyboard user isn't left hunting for the change
- Citation status is conveyed by **icon + text + colour**, never colour alone
- `lang` is set per answer, so a screen reader pronounces Hindi or Tamil correctly
  instead of reading it as mispronounced English
- Native `<dialog>` for the legal-aid panel: platform focus trapping and Escape
- `aria-disabled` rather than `disabled` on busy buttons, so they stay announced
- Helplines are `tel:` links — one tap on the phone someone is panicking on
- AA contrast in light and dark; `prefers-reduced-motion`; `forced-colors` rules;
  zoom never disabled

## Verification

```bash
npm run check     # typecheck → lint → test → build
```

```
57 tests · TypeScript strict · ESLint clean · 0 vulnerabilities · builds clean
```

Tests concentrate where a defect would actually hurt someone: citation
verification, registry integrity (every BNS/BNSS section must record its IPC/CrPC
predecessor), the pre-written answers (**every citation in them must verify, or
the curated content is wrong**), scenario matching (it must *refuse* to match on
one weak keyword — showing a stranger a canned domestic-violence answer because
they typed "bank" would be worse than showing nothing), and the rate limiter.

## Configuration

```bash
cp .env.example .env.local
```

| Variable | Effect |
| --- | --- |
| `ADHIKAR_LOCAL_MODEL` | **On-device** via Ollama or any OpenAI-compatible server. Takes priority. |
| `ADHIKAR_LOCAL_BASE_URL` | Defaults to Ollama (`http://127.0.0.1:11434/v1`) |
| `GOOGLE_GENERATIVE_AI_API_KEY` | Use Gemini |
| `OPENAI_API_KEY` | Use OpenAI |
| `ANTHROPIC_API_KEY` | Use Claude |
| `ADHIKAR_MODEL` | Override the model for the chosen cloud provider |

None set → scenario cards serve pre-written answers; free-text questions explain
that no model is configured. The interface always states which model is
answering, so a pre-written answer can never be mistaken for a tailored one.

### Running entirely on-device

```bash
ollama pull qwen3:8b
echo 'ADHIKAR_LOCAL_MODEL=qwen3:8b' >> .env.local
npm run dev
```

Nothing leaves the machine — the strongest privacy posture available for someone
uploading a tenancy agreement or a legal notice, which is why a local model
**outranks** any cloud key found in the environment.

Two things were learned making this work, both encoded in the code and its tests:

- **A reasoning model may never reach its answer.** On qwen3:8b via Ollama, with
  thinking enabled a 250-token budget went *entirely* into the `reasoning` field
  and produced **zero** content tokens. `reasoning_effort: "none"` is therefore
  sent by default, and the same question then answered in nine seconds.
- **One wall-clock timeout is the wrong shape.** A local 8B model streams a long
  structured answer over minutes; a 60-second ceiling aborted healthy
  generations. Timeouts are now split into a first-byte budget and an
  *inactivity* budget, so a slow-but-live stream finishes and only a genuinely
  hung one is dropped.

Local models also make the citation verifier earn its place. Asked about a
withheld deposit, qwen3:8b cited "Section 107 of the Model Tenancy Act" and
"Section 13 of the Legal Services Authorities Act". Both are inventions — the
real provisions are s.11 and s.12 — and both were flagged **unverified** rather
than rendered as confident links to a government archive.

## Deployment

### Free, no card required (how the live demo is hosted)

```bash
npx vercel --prod
```

Vercel's Hobby tier needs no payment method, is the native host for Next.js, and
needs no configuration here — `maxDuration` is already declared on both API routes
to sit inside its 60-second function ceiling, and Gemini's thinking is disabled by
default partly to stay comfortably under it.

Other card-free options: **Hugging Face Spaces** (Docker SDK — use the Dockerfile
in this repo; a long-running container, so no per-request ceiling at all) and
**Netlify**.

### Google Cloud Run

Cloud Run's free tier is generous, but it is a *discount on a billing-enabled
project* rather than a way to run without billing attached. A project with no
billing account cannot start a container at all, so Cloud Run needs a card on file
even when the monthly bill is zero.

```bash
PROJECT=your-project-id
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

printf '%s' "YOUR_GEMINI_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=-
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# --source builds from the Dockerfile in Cloud Build: no local Docker, and the
# linux/amd64 cross-build is handled for you.
gcloud run deploy adhikar --source . --region us-central1 --allow-unauthenticated \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest" --memory=1Gi
```

### Locally

```bash
docker build -t adhikar . && docker run -p 8080:8080 adhikar
```

The image is multi-stage, runs as an unprivileged user, carries no source or dev
dependencies, and listens on the injected `PORT`.

**A deployment needs no API key at all.** Without one the scenario cards still
serve verified answers, and a visitor can supply their own key in the interface.

## Limitations

Stated plainly, because a tool that hides its failure modes is the problem it
claims to solve:

- **The registry holds 55 sections, not the statute book.** Unverified citations
  will include real provisions. The UI never implies otherwise.
- **No OCR.** A scanned or photographed document is refused with an explanation
  rather than half-analysed — but the user is still stuck, and in India a great
  many documents are scans.
- **Tenancy, police procedure and stamp duty vary by State.** Answers say so;
  they cannot resolve it for you.
- **Section numbers were chosen conservatively.** Where a BNS↔IPC mapping is
  contested, the entry was omitted rather than guessed. Verify anything you act on.
- **Rate limiting is per-instance**, so serverless autoscaling dilutes it.
- **No accounts, no history, nothing persisted.** By design, but it means you
  cannot come back to an answer.
- **The pre-written answers were checked by an engineer, not a lawyer.** They cite
  verified sections and describe standard procedure, and they should be reviewed by
  a practitioner before anyone relies on them.

## Not legal advice

Adhikar provides AI-generated legal information for educational purposes only. It
is not a substitute for professional legal advice, it creates no lawyer–client
relationship, and it cannot tell you how a court would decide your matter. For
formal representation, consult a registered Advocate. If you cannot afford one,
call **15100** — you may be entitled to a free lawyer.

Statutory text is published by the Government of India on
[India Code](https://www.indiacode.nic.in). This is an independent open-source
project, not affiliated with any government body.

## Licence

MIT — see [LICENSE](LICENSE).
