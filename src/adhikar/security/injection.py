"""Embedded-instruction detection for untrusted documents.

Threat model: an adversary controls the contents of a document that a user
legitimately wants analysed.  They cannot reach the system prompt, but they can
write anything they like into the PDF -- including text positioned off-page, set
in white on white, or sized at a quarter-point, all of which a human reader never
sees and a text extractor happily returns.

This scanner is one layer of several, and deliberately not the one that carries
the most weight.  Detection is best-effort against an adaptive adversary; the
structural defences in :mod:`adhikar.llm.transcript` (the document never enters
the system prompt, and is fenced with a per-request nonce) and the entailment
gate in :mod:`adhikar.verify` are what make a *missed* injection non-fatal.  An
injected instruction that survives detection still cannot manufacture a verified
claim, because the verifier only ever sees document spans.

Scoring combines independent signals with a noisy-OR rather than a sum, so
several weak signals accumulate toward -- but never past -- certainty, and no
single pattern can quarantine a document on its own.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from math import prod
from pathlib import Path
from typing import Any

import yaml

from adhikar.errors import CatalogError


class SignalKind(StrEnum):
    """Where a signal came from, which determines how it is explained to the user."""

    LEXICAL = "lexical"
    """Matched a known injection phrasing."""
    STRUCTURAL = "structural"
    """Derived from the document's encoding or layout, not its wording."""


@dataclass(frozen=True, slots=True)
class Signature:
    id: str
    category: str
    regex: re.Pattern[str]
    weight: float
    explanation: str


@dataclass(frozen=True, slots=True)
class InjectionSignal:
    """One piece of evidence that a document is trying to steer the analysis."""

    id: str
    kind: SignalKind
    category: str
    weight: float
    start: int
    end: int
    evidence: str
    explanation: str


@dataclass(frozen=True, slots=True)
class InjectionReport:
    """The verdict on one document, with every signal that contributed."""

    score: float
    signals: tuple[InjectionSignal, ...] = ()
    #: Text stripped of invisible and directional control characters. This is what
    #: downstream stages read; the raw text is kept only for forensics.
    sanitised_text: str = ""

    @property
    def clean(self) -> bool:
        return not self.signals

    def categories(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for signal in self.signals:
            seen.setdefault(signal.category, None)
        return tuple(seen)

    def top_signals(self, limit: int = 5) -> tuple[InjectionSignal, ...]:
        return tuple(sorted(self.signals, key=lambda s: -s.weight)[:limit])


# --------------------------------------------------------------------------- #
# Unicode-level structural checks
# --------------------------------------------------------------------------- #

#: Zero-width and invisible formatting characters. These have legitimate uses in
#: Indic and Arabic scripts (ZWJ/ZWNJ), so their presence is weak evidence on its
#: own -- but a run of them inside Latin text is a classic way to smuggle tokens
#: past a human reader.
_INVISIBLE = frozenset(
    map(
        chr,
        (
            0x200B,  # ZERO WIDTH SPACE
            0x200C,  # ZERO WIDTH NON-JOINER
            0x200D,  # ZERO WIDTH JOINER
            0x2060,  # WORD JOINER
            0xFEFF,  # ZERO WIDTH NO-BREAK SPACE
            0x180E,  # MONGOLIAN VOWEL SEPARATOR
            0x00AD,  # SOFT HYPHEN
            0x034F,  # COMBINING GRAPHEME JOINER
            0x061C,  # ARABIC LETTER MARK
        ),
    )
)

#: Bidirectional overrides. These can visually reorder text so that what a human
#: reads differs from the character sequence a model receives.
_BIDI_CONTROL = frozenset(
    map(
        chr,
        (
            0x202A,  # LEFT-TO-RIGHT EMBEDDING
            0x202B,  # RIGHT-TO-LEFT EMBEDDING
            0x202C,  # POP DIRECTIONAL FORMATTING
            0x202D,  # LEFT-TO-RIGHT OVERRIDE
            0x202E,  # RIGHT-TO-LEFT OVERRIDE
            0x2066,  # LEFT-TO-RIGHT ISOLATE
            0x2067,  # RIGHT-TO-LEFT ISOLATE
            0x2068,  # FIRST STRONG ISOLATE
            0x2069,  # POP DIRECTIONAL ISOLATE
        ),
    )
)

#: Latin-lookalike codepoints from other scripts, used to evade keyword matching
#: (for example, "ignore" written with U+043E in place of the Latin o).
#: Mapped to their Latin equivalent so folding defeats the evasion.
_HOMOGLYPHS: dict[str, str] = {
    # Cyrillic and Greek codepoints that render identically to Latin letters.
    # Written as codepoints rather than characters so this table is reviewable
    # in any editor -- a source file full of lookalikes is its own hazard.
    chr(codepoint): latin
    for codepoint, latin in (
        (0x0430, "a"),
        (0x0435, "e"),
        (0x043E, "o"),
        (0x0440, "p"),
        (0x0441, "c"),
        (0x0445, "x"),
        (0x0443, "y"),
        (0x0456, "i"),
        (0x0458, "j"),
        (0x04BB, "h"),
        (0x0455, "s"),
        (0x0391, "A"),
        (0x0392, "B"),
        (0x0395, "E"),
        (0x0397, "H"),
        (0x0399, "I"),
        (0x039A, "K"),
        (0x039C, "M"),
        (0x039D, "N"),
        (0x039F, "O"),
        (0x03A1, "P"),
        (0x03A4, "T"),
        (0x03A7, "X"),
        (0x03BF, "o"),
        (0x03B1, "a"),
    )
}

_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPHS)


def strip_invisible(text: str) -> str:
    """Remove invisible and directional control characters."""
    return "".join(ch for ch in text if ch not in _INVISIBLE and ch not in _BIDI_CONTROL)


def fold_homoglyphs(text: str) -> str:
    """Normalise Latin-lookalike codepoints so evasion does not defeat matching."""
    return unicodedata.normalize("NFKC", text).translate(_HOMOGLYPH_TABLE)


# --------------------------------------------------------------------------- #
# Catalogue loading
# --------------------------------------------------------------------------- #


def load_signatures(path: Path) -> tuple[Signature, ...]:
    """Load and compile the injection signature catalogue."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"injection catalogue not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"injection catalogue at {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "signatures" not in raw:
        raise CatalogError(f"injection catalogue at {path} has no 'signatures' key")

    signatures: list[Signature] = []
    for entry in raw["signatures"]:
        flags = re.IGNORECASE if not entry.get("case_sensitive", False) else 0
        if entry.get("multiline", False):
            flags |= re.MULTILINE
        try:
            regex = re.compile(entry["pattern"], flags)
        except re.error as exc:
            raise CatalogError(
                f"signature '{entry.get('id', '?')}' has an invalid regex: {exc}"
            ) from exc
        weight = float(entry["weight"])
        if not 0.0 < weight <= 1.0:
            raise CatalogError(f"signature '{entry['id']}' weight {weight} outside (0, 1]")
        signatures.append(
            Signature(
                id=entry["id"],
                category=entry["category"],
                regex=regex,
                weight=weight,
                explanation=entry["explanation"],
            )
        )
    if not signatures:
        raise CatalogError(f"injection catalogue at {path} is empty")
    return tuple(signatures)


@lru_cache(maxsize=4)
def _cached_signatures(path: Path) -> tuple[Signature, ...]:
    return load_signatures(path)


# --------------------------------------------------------------------------- #
# Scanner
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ExtractionArtifact:
    """A structural oddity reported by the document extractor.

    The extractor sees things the text alone cannot show -- a glyph's colour, its
    size, whether it sits outside the page's media box.  Those observations arrive
    here as artifacts and are scored alongside the lexical signals.
    """

    kind: str
    start: int
    end: int
    detail: str
    weight: float


class InjectionScanner:
    """Scores a document for embedded instructions aimed at the analysis pipeline."""

    #: Signal weights for structural findings computed from the text itself.
    _INVISIBLE_RUN_WEIGHT = 0.55
    _BIDI_WEIGHT = 0.65
    _HOMOGLYPH_WEIGHT = 0.6
    #: A run of this many consecutive invisible characters is not plausibly typographic.
    _INVISIBLE_RUN_THRESHOLD = 4

    def __init__(self, signatures: Sequence[Signature]) -> None:
        self._signatures = tuple(signatures)

    @classmethod
    def from_catalogue(cls, path: Path) -> InjectionScanner:
        return cls(_cached_signatures(path))

    def scan(self, text: str, artifacts: Sequence[ExtractionArtifact] = ()) -> InjectionReport:
        """Score ``text`` and return every contributing signal.

        Matching runs against a homoglyph-folded copy so that evasion via
        lookalike codepoints fails, while all reported offsets remain valid
        against the text that was passed in -- folding is length-preserving by
        construction (see :func:`fold_homoglyphs`; NFKC is applied only when it
        does not change length).
        """
        signals: list[InjectionSignal] = []
        signals.extend(self._structural_signals(text))
        signals.extend(self._lexical_signals(text))
        signals.extend(
            InjectionSignal(
                id=artifact.kind,
                kind=SignalKind.STRUCTURAL,
                category="concealment",
                weight=artifact.weight,
                start=artifact.start,
                end=artifact.end,
                evidence=artifact.detail,
                explanation=artifact.detail,
            )
            for artifact in artifacts
        )

        return InjectionReport(
            score=combine_weights([s.weight for s in signals]),
            signals=tuple(sorted(signals, key=lambda s: s.start)),
            sanitised_text=strip_invisible(text),
        )

    # -------------------------------------------------------------- internals
    def _lexical_signals(self, text: str) -> list[InjectionSignal]:
        folded = fold_homoglyphs(text)
        # Folding must not shift offsets, or reported spans would point at the
        # wrong characters. If NFKC changed the length, fall back to the raw text.
        haystack = folded if len(folded) == len(text) else text
        signals: list[InjectionSignal] = []
        for signature in self._signatures:
            for match in signature.regex.finditer(haystack):
                signals.append(
                    InjectionSignal(
                        id=signature.id,
                        kind=SignalKind.LEXICAL,
                        category=signature.category,
                        weight=signature.weight,
                        start=match.start(),
                        end=match.end(),
                        evidence=text[match.start() : match.end()][:200],
                        explanation=signature.explanation,
                    )
                )
        return signals

    def _structural_signals(self, text: str) -> list[InjectionSignal]:
        signals: list[InjectionSignal] = []

        for start, end in _runs(text, _INVISIBLE):
            if end - start >= self._INVISIBLE_RUN_THRESHOLD:
                signals.append(
                    InjectionSignal(
                        id="invisible_character_run",
                        kind=SignalKind.STRUCTURAL,
                        category="concealment",
                        weight=self._INVISIBLE_RUN_WEIGHT,
                        start=start,
                        end=end,
                        evidence=f"{end - start} zero-width characters",
                        explanation=(
                            "A run of characters that occupy no space on the page. "
                            "These are invisible to a reader but not to software."
                        ),
                    )
                )

        for start, end in _runs(text, _BIDI_CONTROL):
            signals.append(
                InjectionSignal(
                    id="bidi_control",
                    kind=SignalKind.STRUCTURAL,
                    category="concealment",
                    weight=self._BIDI_WEIGHT,
                    start=start,
                    end=end,
                    evidence=f"{end - start} bidirectional override characters",
                    explanation=(
                        "Characters that reorder how text is displayed, so what a "
                        "person reads can differ from what software receives."
                    ),
                )
            )

        signals.extend(self._homoglyph_signals(text))
        return signals

    #: Words shorter than this cannot be meaningfully script-mixed; a two-letter
    #: token with one Cyrillic character is noise, not evasion.
    _MIN_HOMOGLYPH_WORD = 3

    def _homoglyph_signals(self, text: str) -> list[InjectionSignal]:
        """Flag words that mix scripts -- a Cyrillic letter inside a Latin word."""
        signals: list[InjectionSignal] = []
        for match in re.finditer(r"\w+", text):
            word = match.group(0)
            if len(word) < self._MIN_HOMOGLYPH_WORD:
                continue
            mixed = any(ch in _HOMOGLYPHS for ch in word)
            has_latin = any("a" <= ch.lower() <= "z" for ch in word)
            if mixed and has_latin:
                signals.append(
                    InjectionSignal(
                        id="homoglyph_word",
                        kind=SignalKind.STRUCTURAL,
                        category="evasion",
                        weight=self._HOMOGLYPH_WEIGHT,
                        start=match.start(),
                        end=match.end(),
                        evidence=word[:60],
                        explanation=(
                            "A word mixing letters from different alphabets that look "
                            "identical, a technique used to slip past keyword checks."
                        ),
                    )
                )
        return signals


def _runs(text: str, charset: frozenset[str]) -> list[tuple[int, int]]:
    """Maximal runs of characters drawn from ``charset``."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, char in enumerate(text):
        if char in charset:
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(text)))
    return runs


def combine_weights(weights: Sequence[float]) -> float:
    """Noisy-OR combination of independent evidence.

    ``1 - Π(1 - wᵢ)``.  Summing would let six innocuous matches cross any
    threshold; taking the maximum would ignore corroboration entirely.  This sits
    between: each additional signal moves the score by less than the last, and the
    result is bounded by 1 without clamping.
    """
    if not weights:
        return 0.0
    return round(1.0 - prod(1.0 - min(max(w, 0.0), 1.0) for w in weights), 6)
