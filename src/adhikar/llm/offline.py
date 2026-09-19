"""Deterministic engine.

Adhikar's analysis is a pipeline of deterministic stages with model calls at
specific points -- not a model with some code around it.  This engine supplies
those points with rule-based implementations, which buys four things:

**The repository runs with no API key.**  Clone, install, run the suite: every
test passes, the web application works, the demo works.  Nothing is stubbed out
or skipped.

**Tests assert on behaviour, not on mocks.**  A test that pins a mocked model
response tests the mock.  These stages have real, specified behaviour that can be
asserted exactly.

**Reproducibility.**  Same input, same output, forever. An audit record from this
engine can be re-derived rather than merely believed.

**A floor.**  When the Anthropic provider is unavailable, the product degrades to
this rather than to nothing.

The honest trade is recall.  Retrieval here is lexical, so a question phrased
entirely in different words from the clause that answers it will be missed, and
entailment is word-overlap, so paraphrase is not recognised.  Both fail toward
*abstention* rather than fabrication, which is the correct direction: this engine
will tell you it cannot answer far more often than it will tell you something
untrue.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from adhikar.analysis.catalog import ClauseCatalog
from adhikar.analysis.glossary import Glossary
from adhikar.analysis.schemas import (
    AnswerDraft,
    ClaimDraft,
    ClauseTypeGuess,
    LawyerQuestion,
    LawyerQuestionList,
    ObligationDraft,
    ObligationList,
    PlainLanguage,
)
from adhikar.errors import SchemaViolationError
from adhikar.llm.base import ModelRequest, ModelResponse, Task, Usage
from adhikar.verify.gate import EntailmentJudgement, lexical_entailment

#: Candidate sentence boundary: punctuation, whitespace, then an opening capital.
#: Candidates are filtered by :func:`_is_real_boundary` rather than by a richer
#: regex, because Python's lookbehind must be fixed-width and the abbreviations
#: that need excluding are not.
_SENTENCE_CANDIDATE = re.compile(
    # A sentence may be followed by ordinary prose (a capital or a quote) or
    # by the next numbered clause ("3. Indemnity"), which is the more common
    # case in a contract and the one a capital-only lookahead misses.
    r"(?<=[.;])\s+(?=[A-Z(\"\u201c]|\d{1,3}[.)])"
)

#: Tokens that end in a period without ending a sentence. Contracts are dense
#: with them, and splitting on one shreds a clause into fragments too short to
#: cite -- which defeats the point of clause-level provenance.
_ABBREVIATIONS = frozenset(
    {
        "no",
        "nos",
        "ltd",
        "pvt",
        "inc",
        "corp",
        "co",
        "cl",
        "sec",
        "art",
        "sch",
        "ann",
        "app",
        "ex",
        "mr",
        "mrs",
        "ms",
        "dr",
        "st",
        "vs",
        "viz",
        "eg",
        "ie",
        "etc",
        "al",
        "para",
        "fig",
    }
)

_TRAILING_TOKEN = re.compile(r"([A-Za-z0-9]+)[.;]\s*$")


def _is_real_boundary(text: str, position: int) -> bool:
    """Whether the punctuation before ``position`` genuinely ends a sentence.

    Rejects clause numbering ("7.2 Fees."), single-letter initials, and known
    abbreviations. Everything else is treated as a boundary.
    """
    match = _TRAILING_TOKEN.search(text[:position])
    if match is None:
        return True
    token = match.group(1)
    if token.isdigit():
        return False
    if len(token) == 1 and token.isupper():
        return False
    return token.casefold() not in _ABBREVIATIONS


#: Words this short are function words; indexing them adds noise, not recall.
_MIN_TERM_CHARS = 2

#: Mirrors ClaimDraft.text's max_length: a claim longer than the schema allows
#: would be rejected at validation rather than shown.
_MAX_CLAIM_CHARS = 600

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "by",
        "within",
        "from",
        "at",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "shall",
        "must",
        "will",
        "may",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "their",
        "such",
        "any",
        "all",
        "each",
        "either",
        "not",
        "no",
        "than",
        "then",
        "there",
        "here",
        "which",
        "who",
        "what",
        "when",
        "where",
        "how",
        "does",
        "do",
        "did",
        "document",
        "contract",
        "agreement",
        "clause",
        "say",
        "says",
    ]
)


@dataclass(frozen=True, slots=True)
class _Passage:
    text: str
    start: int
    end: int


class OfflineEngine:
    """A :class:`~adhikar.llm.base.ModelProvider` that never leaves the process."""

    def __init__(
        self, catalog: ClauseCatalog | None = None, glossary: Glossary | None = None
    ) -> None:
        self._catalog = catalog
        self._glossary = glossary

    @property
    def name(self) -> str:
        return "offline"

    @property
    def model_id(self) -> str | None:
        return None

    async def generate[TOut: BaseModel](
        self, request: ModelRequest, schema: type[TOut]
    ) -> ModelResponse[TOut]:
        """Dispatch on task and return a validated instance of ``schema``."""
        handlers = {
            Task.VERIFY: self._verify,
            Task.ANSWER: self._answer,
            Task.CLAUSE_TYPING: self._clause_type,
            Task.SIMPLIFY: self._simplify,
            Task.OBLIGATIONS: self._obligations,
            Task.LAWYER_QUESTIONS: self._lawyer_questions,
        }
        handler = handlers.get(request.task)
        if handler is None:
            raise SchemaViolationError(f"offline engine does not implement task {request.task}")

        result = handler(request)
        if not isinstance(result, schema):
            # Guards against a handler and its caller disagreeing about the
            # schema -- the same failure the Anthropic path gets from validation.
            raise SchemaViolationError(
                f"offline handler for {request.task} returned {type(result).__name__}, "
                f"expected {schema.__name__}"
            )
        return ModelResponse(
            output=result,
            usage=Usage(input_tokens=self._estimate(request), output_tokens=0),
            model="offline-deterministic",
        )

    # ------------------------------------------------------------------ tasks
    def _verify(self, request: ModelRequest) -> EntailmentJudgement:
        statement = _extract_between(request.instruction, "STATEMENT:", "\n\n")
        evidence = "\n".join(document.text for document in request.documents)
        return lexical_entailment(statement, evidence)

    def _answer(self, request: ModelRequest) -> AnswerDraft:
        question = str(request.params.get("question", request.instruction))
        top_k = int(request.params.get("top_k", 4))

        # A reader asks about "payment terms"; the contract says "Fees". Lexical
        # retrieval cannot bridge that on its own, and that gap is exactly what
        # makes legal documents hard to navigate -- so the query is expanded with
        # drafting-language equivalents before ranking.
        expanded = question
        if self._glossary is not None:
            extra = self._glossary.expand(question)
            if extra:
                expanded = f"{question} {' '.join(extra)}"

        claims: list[ClaimDraft] = []
        for document in request.documents:
            passages = _split_passages(document.text)
            ranked = _rank(expanded, passages)[:top_k]
            claims.extend(
                ClaimDraft(text=_as_statement(passage.text), quotes=[passage.text])
                for passage, score in ranked
                if score > 0
            )

        return AnswerDraft(claims=claims[:top_k], unable_to_answer=not claims)

    def _clause_type(self, request: ModelRequest) -> ClauseTypeGuess:
        if self._catalog is None:
            return ClauseTypeGuess(clause_type=None, confidence=0.0)
        text = "\n".join(document.text for document in request.documents)
        clause_type, confidence = self._catalog.classify(text)
        return ClauseTypeGuess(clause_type=clause_type, confidence=confidence)

    def _simplify(self, request: ModelRequest) -> PlainLanguage:
        """Extractive simplification: the clause's own leading sentences.

        Genuine paraphrase needs a language model. Rather than fake it, the
        offline engine returns the clause's own opening and says plainly that it
        has not been rewritten -- which is honest, and still useful as a summary.
        """
        text = "\n".join(document.text for document in request.documents)
        passages = _split_passages(text)
        lead = " ".join(passage.text for passage in passages[:2]).strip()
        return PlainLanguage(
            summary=lead[:800] or text[:800],
            quotes=[passages[0].text] if passages else [],
            reading_level_note=(
                "Shown as written. Plain-language rewriting requires a language "
                "model, which is not configured."
            ),
        )

    def _obligations(self, request: ModelRequest) -> ObligationList:
        """Rule-based obligation extraction over the supplied text."""
        from adhikar.analysis.obligations import _MODAL, _PARTY

        pattern = re.compile(
            rf"\b(?P<obligor>{_PARTY})\s+(?:{_MODAL})\s+(?P<action>[^.;]{{10,300}}?)(?=[.;]|$)",
            re.MULTILINE,
        )
        drafts: list[ObligationDraft] = []
        for document in request.documents:
            for match in pattern.finditer(document.text):
                sentence = match.group(0)
                drafts.append(
                    ObligationDraft(
                        obligor=" ".join(match.group("obligor").split())[:120],
                        action=" ".join(match.group("action").split())[:400],
                        period_text=_period_text(sentence),
                        trigger_event=_trigger_text(sentence),
                        quotes=[sentence[:300]],
                    )
                )
        return ObligationList(obligations=drafts[:60])

    def _lawyer_questions(self, request: ModelRequest) -> LawyerQuestionList:
        """Questions come from the catalogue, which already holds curated ones."""
        titles: Sequence[str] = request.params.get("finding_titles", ())
        questions: Sequence[str] = request.params.get("catalogue_questions", ())
        items = [
            LawyerQuestion(
                question=question[:300],
                why=(
                    titles[index % len(titles)][:300] if titles else "Identified in your document."
                ),
                quotes=[],
            )
            for index, question in enumerate(questions)
        ]
        return LawyerQuestionList(questions=items[:15])

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _estimate(request: ModelRequest) -> int:
        """Rough token count, so the efficiency view has comparable numbers."""
        characters = len(request.instruction) + sum(len(d.text) for d in request.documents)
        return characters // 4


def _split_passages(text: str) -> list[_Passage]:
    """Sentence-level passages carrying their exact offsets into ``text``.

    Offsets are computed from the split points rather than by searching for each
    passage afterwards, so a sentence that appears twice in a document still
    anchors to the occurrence it actually came from.
    """
    boundaries = [
        match.start()
        for match in _SENTENCE_CANDIDATE.finditer(text)
        if _is_real_boundary(text, match.start())
    ]

    passages: list[_Passage] = []
    cursor = 0
    for boundary in [*boundaries, len(text)]:
        chunk = text[cursor:boundary]
        stripped = chunk.strip()
        if stripped:
            offset = cursor + (len(chunk) - len(chunk.lstrip()))
            passages.append(_Passage(text=stripped, start=offset, end=offset + len(stripped)))
        cursor = boundary
    return passages


def _rank(question: str, passages: Sequence[_Passage]) -> list[tuple[_Passage, float]]:
    """Rank passages against a question by BM25-style lexical overlap.

    BM25 rather than raw overlap so that a rare term ("indemnify") outweighs a
    common one ("agreement"), and so a long clause does not win on length alone.
    """
    query = _terms(question)
    if not query or not passages:
        return []

    documents = [_terms(p.text) for p in passages]
    lengths = [len(d) for d in documents]
    average_length = sum(lengths) / len(lengths) if lengths else 0.0
    frequency: Counter[str] = Counter()
    for document in documents:
        frequency.update(set(document))

    k1, b = 1.5, 0.75
    total = len(documents)
    scored: list[tuple[_Passage, float]] = []
    for passage, terms, length in zip(passages, documents, lengths, strict=True):
        counts = Counter(terms)
        score = 0.0
        for term in query:
            if term not in counts:
                continue
            idf = math.log(1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5))
            tf = counts[term]
            denominator = tf + k1 * (1 - b + b * length / (average_length or 1))
            score += idf * (tf * (k1 + 1)) / denominator
        if score > 0:
            scored.append((passage, round(score, 6)))
    return sorted(scored, key=lambda pair: -pair[1])


def _terms(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in _STOPWORDS and len(word) > _MIN_TERM_CHARS
    ]


def _as_statement(passage: str) -> str:
    """Present a retrieved passage as a claim.

    The offline engine does not rewrite, so the claim *is* the passage. Saying so
    explicitly keeps the claim and its evidence trivially consistent, which is
    why offline answers always verify.
    """
    collapsed = " ".join(passage.split())
    if len(collapsed) <= _MAX_CLAIM_CHARS:
        return collapsed
    return collapsed[: _MAX_CLAIM_CHARS - 1] + "…"


def _period_text(sentence: str) -> str | None:
    match = re.search(
        r"\b(?:[a-z\- ]+\s*)?(?:\(\d{1,4}\)\s*)?\d{0,4}\s*"
        r"(?:business |working |calendar )?(?:days?|weeks?|months?|years?)\b",
        sentence,
        re.IGNORECASE,
    )
    return " ".join(match.group(0).split())[:80] if match else None


def _trigger_text(sentence: str) -> str | None:
    match = re.search(
        r"\b(?:of|from|after|before|prior to)\s+(?:the\s+)?"
        r"(receipt|invoice|effective date|commencement|termination|notice|delivery|breach)\b",
        sentence,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
    """Pull a labelled section out of a rendered instruction."""
    start = text.find(start_marker)
    if start == -1:
        return text
    start += len(start_marker)
    end = text.find(end_marker, start)
    return text[start : end if end != -1 else len(text)].strip()
