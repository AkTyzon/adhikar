# Architecture

## The shape of the thing

Adhikar is **a deterministic pipeline with model calls at specific points**, not a
model with code around it. That inversion is the central design decision and
almost everything else follows from it.

Concretely: clause segmentation, risk detection, baseline comparison, date
arithmetic, PII redaction, injection scanning and span verification are all
ordinary code. Models are used for the two things code is bad at — reading
unusual phrasing, and judging whether a passage supports a statement — and their
output is checked by code before anyone sees it.

One consequence is worth stating plainly: **the whole product works with no API
key.** The offline engine is a real implementation, not a stub, so `git clone &&
make install && make check` passes with no secrets, and the test suite asserts on
actual behaviour rather than on mocked responses.

## Request flow

```
  Upload
    │
    ├─ 1. extract ──────── glyph-level walk: text + concealment artifacts
    │                      (colour, size, position per character)
    │
    ├─ 2. scan ─────────── signatures + structural signals → injection score
    │                      ≥ block threshold?  →  QUARANTINE, never analysed
    │
    ├─ 3. sanitise ─────── strip invisible + bidirectional characters
    │
    ├─ 4. redact ───────── PII → [[PERSON_1]], keeping an OffsetMap so every
    │                      later span can be translated back
    │
    └─ 5. segment ──────── clause tree with exact, non-overlapping spans
                           (invariant asserted before returning)

  Ask a question
    │
    ├─ 1. scope gate ───── intent → response mode → output schema
    │                      refer_out?  →  answered with no model call at all
    │
    ├─ 2. generate ─────── model returns atomic claims, each with verbatim quotes
    │                      (document fenced with a per-request nonce; never in
    │                       the system prompt)
    │
    ├─ 3. anchor ───────── locate each quote in the document → Span
    │                      not found verbatim?  →  dropped as fabricated
    │
    ├─ 4. verify ───────── (a) re-resolve every span against its quote hash
    │                      (b) independent entailment judgement, seeing ONLY
    │                          the cited passage
    │
    └─ 5. respond ──────── admitted claims + withheld claims + why
                           audit record sealed into the hash chain
```

## Why the stages sit in that order

**Quarantine before analysis.** A poisoned document is refused, not analysed with
a warning attached. Analysing it first and warning afterwards means the payload
has already been processed.

**Redaction before segmentation, and therefore before every model call.** It
would be easier to redact after segmenting; it would also mean the model saw the
real names. Redaction shifts every offset, which is why `OffsetMap` exists rather
than being an afterthought.

**The scope gate before generation.** A question asking for a prediction is
refused on the way in. Generating an answer and then filtering it means the
advice was produced, and the only thing standing between it and the user is a
filter.

**Anchoring before entailment.** The cheap deterministic check runs first. A
fabricated quote never reaches the verifier, so no model time is spent judging a
claim whose evidence does not exist.

## Module map

| Module | Responsibility |
| --- | --- |
| [`domain.py`](../src/adhikar/domain.py) | `Span`, `Claim`, `Finding`, `Obligation`. Frozen. `Span` is the provenance atom. |
| [`pipeline.py`](../src/adhikar/pipeline.py) | Stage order, in one readable file, with auditing |
| [`ingest/extract.py`](../src/adhikar/ingest/extract.py) | Text + concealment forensics, format sniffing, limits |
| [`ingest/segment.py`](../src/adhikar/ingest/segment.py) | Clause tree; asserts spans tile exactly |
| [`security/injection.py`](../src/adhikar/security/injection.py) | Signature and structural scanning, noisy-OR scoring |
| [`security/redaction.py`](../src/adhikar/security/redaction.py) | Reversible pseudonymisation with checksum validation |
| [`security/textmap.py`](../src/adhikar/security/textmap.py) | Offset translation across rewrites |
| [`security/upl.py`](../src/adhikar/security/upl.py) | Scope routing: intent → mode → schema |
| [`security/audit.py`](../src/adhikar/security/audit.py) | Hash-chained records |
| [`llm/transcript.py`](../src/adhikar/llm/transcript.py) | The data/instruction boundary |
| [`llm/offline.py`](../src/adhikar/llm/offline.py) | Deterministic engine: BM25 retrieval, lexical entailment |
| [`llm/anthropic_provider.py`](../src/adhikar/llm/anthropic_provider.py) | Claude backend: structured outputs, caching, effort |
| [`analysis/catalog.py`](../src/adhikar/analysis/catalog.py) | Loads the clause taxonomy; validates strictly |
| [`analysis/risk.py`](../src/adhikar/analysis/risk.py) | Runs rules, rebases offsets, compares to baseline |
| [`analysis/deadlines.py`](../src/adhikar/analysis/deadlines.py) | All date arithmetic in the system |
| [`verify/anchor.py`](../src/adhikar/verify/anchor.py) | Quote → span, or rejection |
| [`verify/gate.py`](../src/adhikar/verify/gate.py) | Integrity check + entailment judgement |
| [`web/render.py`](../src/adhikar/web/render.py) | Escape-then-assemble highlighting |

## Knowledge lives in data, not code

Everything the system knows about contracts is in
[`analysis/knowledge/`](../src/adhikar/analysis/knowledge/) as YAML:

| File | Contains |
| --- | --- |
| `clauses.yaml` | 11 clause types, 23 risk rules, fair-terms baselines, lawyer questions |
| `injection_signatures.yaml` | 16 weighted attack signatures |
| `pii_patterns.yaml` | 16 identifier patterns with validators and context gates |
| `upl_policy.yaml` | Intent → mode routing and what each mode may produce |
| `glossary.yaml` | 20 legal terms: plain-language equivalents and search synonyms |
| `segmentation.yaml` | Clause-heading patterns |

**No clause name, keyword, threshold or baseline position appears in Python.**
Adding a jurisdiction or a contract family is a data change a lawyer can review
without reading code, and the engine cannot drift from what these files say
because it holds no independent copy of them.

The rule language (`any` / `all` / `none` / `near`) is interpreted in exactly one
place, [`analysis/rules.py`](../src/adhikar/analysis/rules.py). Conditions return
the byte ranges that caused them to fire, which is what lets a finding cite the
eleven words that triggered it.

Validation is strict and happens at load: an unknown severity, an invalid regex,
or a rule with an empty condition raises rather than being skipped. A rule that
silently never fires is worse than a server that refuses to start, because the
first looks exactly like a clean contract.

## Two engines, one interface

Every model call is a *structured* call: the caller supplies a Pydantic model and
gets a validated instance or an exception. There is no code path that parses
free-form model prose.

| | Offline | Anthropic |
| --- | --- | --- |
| Retrieval | BM25 + glossary query expansion | Model reads the whole document |
| Entailment | Content-word coverage with negation check | Independent model judgement |
| Clause typing | Catalogue regex detectors | Same (rules are already sufficient) |
| Determinism | Total | No |
| Recall on unusual phrasing | Poor | Good |
| Cost | Zero | Per token |

The offline engine's honest weakness is recall: a question phrased entirely
differently from the clause that answers it will be missed, and paraphrase is not
recognised as entailment. Both failures point toward **abstention**, which is the
correct direction — it will say it cannot answer far more often than it will say
something untrue.

Query expansion via `glossary.yaml` narrows the gap and is a product feature in
its own right: a reader asks about "payment terms", the contract says "Fees", and
that gap is precisely what makes legal documents hard to navigate.

## Cost and latency on the Anthropic path

Three API features do architectural work:

- **Structured outputs** (`messages.parse` with a Pydantic model) — removes the
  entire class of response-parsing bugs.
- **Prompt caching on the document block** — the contract is large and constant
  across a session; the question is small and varies. The document is marked as
  the cache breakpoint, so follow-up questions re-read it at a fraction of the
  cost. Measured, not assumed: `cache_read_input_tokens` is recorded in every
  audit record and shown in the audit view.
- **Per-task effort** — verification is a narrow judgement on a short passage and
  runs at `low`; extraction over a whole contract runs at `high`.

The verifier model is configurable separately from the generator, so the
entailment gate can run on a different model. An independent checker is harder to
talk past than the model that produced the claim.

## Storage

**Documents are never written to disk.** They live in a per-process store with a
TTL and a capacity cap. **Audit records are persisted** — they hold hashes,
counts and decisions, never text, so keeping them is safe and is the point.

This costs horizontal scalability: a session's document lives in one worker.
That is a deliberate trade for this data, and the boundary is drawn at
[`store.py`](../src/adhikar/store.py) so that adding a shared cache is a decision
someone has to make rather than a default someone inherits.

## Testing

323 tests, 88% coverage, no mocked models anywhere.

The suite is organised by what it protects:

- `tests/unit/` — segmentation invariants, rule semantics, date arithmetic,
  offset mapping, HTML escaping
- `tests/security/` — an adversarial corpus **and a benign corpus**. The benign
  one matters as much: a scanner that flags "shall not disclose" as an attack is
  a scanner that gets switched off.
- `tests/integration/` — stage order, the verification gate, the HTTP surface

Adversarial PDFs are **generated** by `scripts/make_fixtures.py` rather than
committed, so the repository stays small and each attack is readable in source
instead of opaque inside a binary.
