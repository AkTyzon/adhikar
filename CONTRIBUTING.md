# Contributing

## Setup

```bash
make install     # uv-managed venv, Python 3.12, all extras
make check       # lint, types, tests, security — everything CI runs
```

No API key is needed for any of it.

## The one rule

**Every user-visible statement must be traceable to a byte range in a document
the user supplied, and checked against it.**

If a change would let text reach a user without a resolvable
[`Span`](src/adhikar/domain.py) behind it, that change is wrong regardless of how
good the output looks. Tests enforce this; please do not weaken them to make a
feature fit.

## Where things belong

**Contract knowledge goes in YAML, not Python.** Clause types, risk rules,
baselines, injection signatures, PII patterns and glossary terms all live in
[`src/adhikar/analysis/knowledge/`](src/adhikar/analysis/knowledge/). A new risk
rule is a data change — no code required — and the catalogue loader validates it
strictly at startup.

Adding a rule:

```yaml
- id: descriptive_snake_case
  severity: critical | high | medium | low | info
  title: What is wrong, in plain language
  when:
    any: ['\bregex\b']        # or all / none / near
  why_it_matters: >-
    What this costs the reader, concretely. Not "this may be unfavourable".
  questions_for_lawyer:
    - A specific question answerable in a short consultation.
```

Then add a case to `tests/unit/test_analysis.py`, **and** a benign clause to the
corpus in `tests/security/test_injection.py` if the pattern could plausibly
over-match.

## Adding an attack

New injection techniques are welcome. Add a builder to
[`scripts/make_fixtures.py`](scripts/make_fixtures.py) and an entry to
`EXPECTATIONS` in [`scripts/verify_defences.py`](scripts/verify_defences.py). CI
then fails permanently if that attack ever stops being caught.

Fixtures are generated, never committed: the repository stays small and the attack
stays readable in source.

## Style

- `ruff` and `mypy --strict` must pass. Both are configured in `pyproject.toml`.
- Comments explain **why**, not what. If a line needs a comment saying what it
  does, rename something instead.
- Prose in findings and UI copy is written for someone reading their own
  contract: short sentences, no Latin, no "pursuant to".
- New thresholds get a named constant with a comment explaining the number.

## Tests

- No mocked models. The offline engine is deterministic; assert on real behaviour.
- A false positive in a detector is a real bug. New detectors need benign cases
  as well as attack cases.
- Coverage gate is 85%. It is checked in CI and will fail the build.
