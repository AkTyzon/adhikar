"""Obligation extraction and contradiction detection.

An obligation is "who must do what, by when, if what happens".  Represented as
prose it can only be read; represented as a typed record it can be sorted into a
calendar, checked against other documents, and tested.

The extraction is a two-speed design.  A deterministic pass finds obligations by
their grammatical signature -- a party, a modal verb, an action -- and works with
no model at all.  Where a model is available it produces the same
:class:`~adhikar.domain.Obligation` records with better recall on unusual
phrasing.  Both paths route dates through :mod:`adhikar.analysis.deadlines`, so
neither performs arithmetic.

Contradiction detection is what makes the structure earn its keep.  Two documents
that each look reasonable can be jointly impossible -- an MSA requiring 60 days'
termination notice and an SOW promising 30 -- and no amount of reading either one
in isolation reveals it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from adhikar.analysis.deadlines import Duration, add_duration, find_dates, parse_duration
from adhikar.domain import Contradiction, Document, Obligation, Span, TriggerKind

#: Modal verbs that create a duty. "May" is excluded: it grants a right.
_MODAL: Final = r"(?:shall|must|will|agrees? to|undertakes? to|is required to|is obliged to)"

#: A party is a defined term ("the Client"), a capitalised entity, or a pronoun
#: standing for one. Defined terms carry initial capitals by drafting convention.
_PARTY: Final = (
    r"(?:the\s+)?(?:[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3}|Company|Client|Customer|"
    r"Provider|Supplier|Vendor|Contractor|Licensee|Licensor|Party|Parties|Employee|Employer)"
)

_OBLIGATION = re.compile(
    rf"\b(?P<obligor>{_PARTY})\s+(?P<modal>{_MODAL})\s+(?P<action>[^.;]{{10,300}}?)(?=[.;]|$)",
    re.MULTILINE,
)

#: Phrases that anchor a relative deadline to an event.
_TRIGGER_PHRASES: Final[tuple[tuple[str, str], ...]] = (
    (r"of\s+receipt", "receipt"),
    (r"of\s+(?:the\s+)?invoice", "invoice date"),
    (r"(?:of|from|after)\s+(?:the\s+)?effective\s+date", "effective date"),
    (r"(?:of|from|after)\s+(?:the\s+)?commencement", "commencement"),
    (r"(?:prior to|before)\s+(?:the\s+)?renewal", "renewal date"),
    (r"(?:of|from|after)\s+(?:the\s+)?termination", "termination"),
    (r"(?:of|from|after)\s+(?:written\s+)?notice", "notice"),
    (r"(?:of|from|after)\s+(?:the\s+)?(?:breach|default)", "breach"),
    (r"(?:of|from|after)\s+(?:the\s+)?delivery", "delivery"),
)

#: Conditional framing that makes an obligation contingent rather than absolute.
_CONDITION = re.compile(
    r"\b(?:if|in the event (?:that|of)|upon|provided that|should|where|unless)\b[^.;]{5,200}",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ObligationSet:
    """Extracted obligations with the anchor dates used to resolve them."""

    obligations: tuple[Obligation, ...]
    anchors: dict[str, date]
    #: Deadlines that could not be resolved because their anchor event has no
    #: known date. Surfaced to the user as "tell us when X happened".
    unresolved_anchors: tuple[str, ...]

    def dated(self) -> tuple[Obligation, ...]:
        return tuple(o for o in self.obligations if o.computed_due or o.stated_date)

    def by_party(self) -> dict[str, tuple[Obligation, ...]]:
        grouped: dict[str, list[Obligation]] = {}
        for obligation in self.obligations:
            grouped.setdefault(obligation.obligor, []).append(obligation)
        return {party: tuple(items) for party, items in grouped.items()}


def find_anchor_dates(document: Document) -> dict[str, date]:
    """Locate dates the document defines, keyed by the event they anchor.

    Only the effective/commencement date is inferred, because it is the one
    contracts reliably state outright. Everything else -- receipt, notice,
    delivery -- depends on events outside the document and is left unresolved
    rather than guessed.
    """
    anchors: dict[str, date] = {}
    dates = find_dates(document.text)
    if not dates:
        return anchors

    effective = re.search(
        r"\b(?:effective date|commenc\w+|shall begin|start(?:s|ing)? on)\b",
        document.text,
        re.IGNORECASE,
    )
    if effective:
        # The nearest date following the phrase is the one it introduces.
        following = [d for d in dates if d[1] >= effective.start()]
        if following:
            anchors["effective date"] = following[0][0]
        else:
            anchors["effective date"] = dates[0][0]
    else:
        anchors["effective date"] = dates[0][0]
    return anchors


def extract(document: Document, *, anchors: dict[str, date] | None = None) -> ObligationSet:
    """Deterministically extract obligations from a document.

    Recall is the weak point of the rule-based path -- unusual drafting will be
    missed -- and that is the honest trade for a stage that runs with no model,
    no key and no network, and never invents an obligation that is not there.
    """
    resolved_anchors = anchors if anchors is not None else find_anchor_dates(document)
    obligations: list[Obligation] = []
    unresolved: set[str] = set()

    for clause in document.clauses:
        for match in _OBLIGATION.finditer(clause.text):
            obligor = _clean_party(match.group("obligor"))
            if not obligor or _is_noise(obligor):
                continue
            action = " ".join(match.group("action").split())
            sentence = match.group(0)

            trigger_kind, trigger_event, duration, stated = _classify_trigger(sentence)
            computed = _resolve_due(trigger_kind, trigger_event, duration, stated, resolved_anchors)
            if trigger_kind is TriggerKind.RELATIVE_TO_EVENT and computed is None and trigger_event:
                unresolved.add(trigger_event)

            start = clause.span.start + match.start()
            end = clause.span.start + match.end()
            obligations.append(
                Obligation(
                    id=_obligation_id(document.id, obligor, action),
                    obligor=obligor,
                    obligee=None,
                    action=action,
                    trigger_kind=trigger_kind,
                    trigger_event=trigger_event,
                    offset_days=duration.approximate_days if duration else None,
                    business_days=bool(duration and duration.business_days),
                    stated_date=stated,
                    computed_due=computed,
                    condition=_find_condition(sentence),
                    spans=(Span.over(document.id, document.text, start, end),),
                    document_id=document.id,
                )
            )

    return ObligationSet(
        obligations=tuple(obligations),
        anchors=resolved_anchors,
        unresolved_anchors=tuple(sorted(unresolved)),
    )


def _classify_trigger(
    sentence: str,
) -> tuple[TriggerKind, str | None, Duration | None, date | None]:
    """Determine how an obligation's deadline is anchored."""
    explicit = find_dates(sentence)
    duration = parse_duration(sentence)

    if explicit:
        return TriggerKind.ABSOLUTE, None, duration, explicit[0][0]

    if re.search(r"\b(?:annually|monthly|quarterly|each year|every \w+)\b", sentence, re.I):
        return TriggerKind.RECURRING, None, duration, None

    if duration is not None:
        for pattern, event in _TRIGGER_PHRASES:
            if re.search(pattern, sentence, re.IGNORECASE):
                return TriggerKind.RELATIVE_TO_EVENT, event, duration, None
        return TriggerKind.RELATIVE_TO_EVENT, "unspecified event", duration, None

    if _CONDITION.search(sentence):
        return TriggerKind.ON_CONDITION, None, None, None

    return TriggerKind.NONE, None, None, None


def _resolve_due(
    kind: TriggerKind,
    event: str | None,
    duration: Duration | None,
    stated: date | None,
    anchors: dict[str, date],
) -> date | None:
    """Compute a due date where the anchor is known. Never guesses."""
    if kind is TriggerKind.ABSOLUTE:
        return stated
    if kind is TriggerKind.RELATIVE_TO_EVENT and duration is not None and event:
        anchor = anchors.get(event)
        if anchor is not None:
            return add_duration(anchor, duration)
    return None


def _clean_party(raw: str) -> str:
    return " ".join(raw.replace("the ", "").replace("The ", "").split()).strip()


#: Sentence-initial capitalised words that are not parties. Without this the
#: extractor reads "This Agreement shall..." as an obligation of "This Agreement".
_NOISE_PARTIES: Final = frozenset(
    {
        "this",
        "that",
        "these",
        "those",
        "it",
        "which",
        "who",
        "agreement",
        "clause",
        "section",
        "party a",
        "party b",
        "nothing",
        "no",
        "each",
        "either",
        "any",
        "all",
        "such",
        "the",
    }
)


#: A single character is never a party name.
_MIN_PARTY_CHARS = 2


def _is_noise(party: str) -> bool:
    return party.lower() in _NOISE_PARTIES or len(party) < _MIN_PARTY_CHARS


def _find_condition(sentence: str) -> str | None:
    match = _CONDITION.search(sentence)
    return " ".join(match.group(0).split()) if match else None


def _obligation_id(document_id: str, obligor: str, action: str) -> str:
    digest = hashlib.sha256(f"{obligor}|{action}".encode()).hexdigest()[:12]
    return f"{document_id}:o:{digest}"


# --------------------------------------------------------------------------- #
# Contradictions
# --------------------------------------------------------------------------- #

#: Below this Jaccard similarity two obligations are about different subjects and
#: any difference between them is not a contradiction.
_SUBJECT_SIMILARITY = 0.45

#: Words this short are function words and carry no subject signal.
_MIN_CONTENT_CHARS = 2

_STOPWORDS: Final = frozenset(
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
        "shall",
        "must",
        "will",
        "be",
        "is",
        "are",
        "this",
        "that",
        "these",
        "those",
        "its",
        "their",
        "his",
        "her",
        "such",
        "any",
        "all",
        "each",
    ]
)


def find_contradictions(
    obligations: Sequence[Obligation], documents: Sequence[Document]
) -> tuple[Contradiction, ...]:
    """Find obligations that cannot both be satisfied.

    Restricted to pairs that are about the same subject and bind the same party.
    Two clauses saying different things about different topics is a contract, not
    a contradiction, and a detector without that constraint produces noise that
    buries the real conflicts.
    """
    found: list[Contradiction] = []
    for index, left in enumerate(obligations):
        for right in obligations[index + 1 :]:
            if left.obligor.lower() != right.obligor.lower():
                continue
            if _subject_similarity(left.action, right.action) < _SUBJECT_SIMILARITY:
                continue

            conflict = _conflict_between(left, right)
            if conflict is None:
                continue
            kind, explanation = conflict
            found.append(
                Contradiction(
                    id=f"{left.id}~{right.id}",
                    kind=kind,
                    explanation=explanation,
                    left=left,
                    right=right,
                    spans=left.spans + right.spans,
                )
            )
    return tuple(found)


def _conflict_between(left: Obligation, right: Obligation) -> tuple[str, str] | None:
    """Whether two same-subject obligations are jointly unsatisfiable."""
    if left.computed_due and right.computed_due and left.computed_due != right.computed_due:
        return (
            "conflicting_deadline",
            f"The same obligation is given two different deadlines: "
            f"{left.computed_due.isoformat()} and {right.computed_due.isoformat()}.",
        )

    if (
        left.offset_days is not None
        and right.offset_days is not None
        and left.offset_days != right.offset_days
        and left.trigger_event == right.trigger_event
    ):
        return (
            "conflicting_period",
            f"The same obligation is given two different periods: "
            f"{left.offset_days} days and {right.offset_days} days"
            + (f" from {left.trigger_event}." if left.trigger_event else "."),
        )

    left_doc, right_doc = left.document_id, right.document_id
    if left_doc != right_doc and left.action.strip().lower() != right.action.strip().lower():
        negated = _one_is_negated(left.action, right.action)
        if negated:
            return (
                "cross_document_conflict",
                "Two documents state opposite requirements for the same party "
                "on what appears to be the same subject.",
            )
    return None


def _one_is_negated(left: str, right: str) -> bool:
    negative = re.compile(r"\bnot\b|\bno\b|\bnever\b|\bwithout\b", re.IGNORECASE)
    return bool(negative.search(left)) != bool(negative.search(right))


def _subject_similarity(left: str, right: str) -> float:
    """Jaccard overlap of content words."""
    left_set = _content_words(left)
    right_set = _content_words(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        word
        for word in re.findall(r"[a-z]+", text.lower())
        if word not in _STOPWORDS and len(word) > _MIN_CONTENT_CHARS
    )
