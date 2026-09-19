"""Structured output schemas shared by every engine.

Both the offline engine and the Anthropic provider return instances of these
models, which is what makes them substitutable.  Callers never branch on which
engine produced a result.

One decision shapes all of them: **models quote, they do not compute offsets.**
Asking a model for character positions is asking it to count, which it does
badly and silently.  Asking it to reproduce the sentence it relied on is asking
it to copy, which it does well -- and a quote can be *located* in the document by
:mod:`adhikar.verify.anchor`, deterministically.  A quote that cannot be found
verbatim is a fabrication, detected in Python rather than trusted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClaimDraft(BaseModel):
    """One atomic assertion plus the exact text it rests on."""

    model_config = {"extra": "forbid"}

    text: str = Field(
        min_length=1,
        max_length=600,
        description="A single factual statement, in plain language, about the document.",
    )
    quotes: list[str] = Field(
        min_length=1,
        max_length=4,
        description=(
            "Exact verbatim passages copied from the document that establish the "
            "statement. Must be reproduced character for character."
        ),
    )


class AnswerDraft(BaseModel):
    """A generated answer, before verification."""

    model_config = {"extra": "forbid"}

    claims: list[ClaimDraft] = Field(
        default_factory=list,
        max_length=20,
        description="Atomic statements answering the question, each with its evidence.",
    )
    unable_to_answer: bool = Field(
        default=False,
        description="True when the document does not contain the answer.",
    )
    #: Note the schema has no 'recommendation' or 'advice' field in any mode.
    #: See adhikar.security.upl for why that is structural rather than incidental.


class ClauseTypeGuess(BaseModel):
    """A model's opinion on what kind of clause a passage is."""

    model_config = {"extra": "forbid"}

    clause_type: str | None = Field(
        default=None, description="Catalogue id of the clause type, or null if none fits."
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PlainLanguage(BaseModel):
    """A plain-language rendering of a clause."""

    model_config = {"extra": "forbid"}

    summary: str = Field(max_length=800, description="What this clause does, in plain words.")
    quotes: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Verbatim passages the summary is drawn from.",
    )
    reading_level_note: str | None = Field(
        default=None,
        max_length=200,
        description="Anything that had to be simplified at the cost of precision.",
    )


class ObligationDraft(BaseModel):
    """One extracted duty, with its anchor described rather than calculated."""

    model_config = {"extra": "forbid"}

    obligor: str = Field(max_length=120, description="Who owes the duty.")
    obligee: str | None = Field(default=None, max_length=120, description="Who is owed it.")
    action: str = Field(max_length=400, description="What must be done.")
    #: Deliberately a description, not a date. Resolution happens in
    #: adhikar.analysis.deadlines so that no computed date originates in a model.
    trigger_event: str | None = Field(
        default=None,
        max_length=120,
        description="The event the deadline runs from, e.g. 'receipt of invoice'.",
    )
    period_text: str | None = Field(
        default=None,
        max_length=80,
        description="The period exactly as written, e.g. 'thirty (30) days'. Do not convert it.",
    )
    condition: str | None = Field(default=None, max_length=300)
    quotes: list[str] = Field(min_length=1, max_length=3)


class ObligationList(BaseModel):
    model_config = {"extra": "forbid"}

    obligations: list[ObligationDraft] = Field(default_factory=list, max_length=60)


class LawyerQuestion(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(max_length=300)
    why: str = Field(max_length=300, description="What this question is trying to establish.")
    quotes: list[str] = Field(default_factory=list, max_length=2)


class LawyerQuestionList(BaseModel):
    model_config = {"extra": "forbid"}

    questions: list[LawyerQuestion] = Field(default_factory=list, max_length=15)
