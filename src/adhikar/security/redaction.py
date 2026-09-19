"""Reversible PII pseudonymisation.

Two properties make this useful rather than merely destructive:

**It is reversible.** Values are replaced with stable placeholders and kept in a
per-document vault that never leaves the process.  The analysis pipeline reasons
about ``[[PERSON_1]]``; the user reads the real name because the placeholder is
expanded on the way out.  Destructive redaction would make the output incoherent
("the party shall notify ████ within ██ days").

**It is coreference-preserving.** The same value always gets the same
placeholder, so a model can still tell that the signatory in clause 3 and the
notice recipient in clause 12 are one person -- which matters, because that is
exactly the kind of cross-clause reasoning the product exists to do.

The catalogue of what counts as PII lives in ``knowledge/pii_patterns.yaml``.
This module contains matching, conflict resolution and vaulting -- no patterns.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from adhikar.errors import CatalogError
from adhikar.security.checksums import VALIDATORS
from adhikar.security.textmap import OffsetMap, Replacement

_PLACEHOLDER_RE = re.compile(r"\[\[([A-Z_]+)_(\d+)\]\]")


class Sensitivity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_SENSITIVITY_RANK: dict[Sensitivity, int] = {
    Sensitivity.LOW: 0,
    Sensitivity.MEDIUM: 1,
    Sensitivity.HIGH: 2,
}


@dataclass(frozen=True, slots=True)
class PiiPattern:
    """One catalogue entry, compiled and ready to match."""

    id: str
    label: str
    regex: re.Pattern[str]
    validator: Callable[[str], bool]
    sensitivity: Sensitivity
    description: str
    requires_context: tuple[str, ...] = ()
    context_window: int = 60

    def context_satisfied(self, text: str, start: int, end: int) -> bool:
        """Whether a required context keyword sits near the match.

        Generic shapes -- a run of digits, a six-digit postcode -- are only PII
        when something nearby says so.  Without this gate the redactor eats
        clause numbers and monetary amounts.
        """
        if not self.requires_context:
            return True
        window_start = max(0, start - self.context_window)
        window = text[window_start : end + self.context_window].lower()
        return any(keyword in window for keyword in self.requires_context)


@dataclass(frozen=True, slots=True)
class PiiMatch:
    """A validated occurrence of PII in a text."""

    start: int
    end: int
    pattern_id: str
    label: str
    raw: str
    sensitivity: Sensitivity

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Rewritten text plus everything needed to undo and audit the rewrite."""

    text: str
    offset_map: OffsetMap
    matches: tuple[PiiMatch, ...]
    #: placeholder -> original value. Never serialised to disk or sent to a model.
    vault: Mapping[str, str] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return bool(self.matches)

    def counts_by_type(self) -> dict[str, int]:
        """Summary for the UI and the audit record -- types and counts, never values."""
        counts: dict[str, int] = {}
        for match in self.matches:
            counts[match.pattern_id] = counts.get(match.pattern_id, 0) + 1
        return counts

    def restore(self, text: str) -> str:
        """Expand placeholders back to their original values."""
        if not self.vault:
            return text
        return _PLACEHOLDER_RE.sub(
            lambda m: self.vault.get(m.group(0), m.group(0)),
            text,
        )


def load_patterns(path: Path) -> tuple[PiiPattern, ...]:
    """Load and compile the PII catalogue.

    Raises:
        CatalogError: the file is missing, malformed, or names an unknown validator.
    """
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"PII catalogue not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"PII catalogue at {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "patterns" not in raw:
        raise CatalogError(f"PII catalogue at {path} has no 'patterns' key")

    patterns: list[PiiPattern] = []
    for entry in raw["patterns"]:
        try:
            validator = VALIDATORS[entry["validator"]]
        except KeyError as exc:
            raise CatalogError(
                f"pattern '{entry.get('id', '?')}' names unknown validator "
                f"{entry.get('validator')!r}"
            ) from exc
        flags = 0 if entry.get("case_sensitive", False) else re.IGNORECASE
        try:
            regex = re.compile(entry["pattern"], flags)
        except re.error as exc:
            raise CatalogError(
                f"pattern '{entry.get('id', '?')}' has an invalid regex: {exc}"
            ) from exc
        patterns.append(
            PiiPattern(
                id=entry["id"],
                label=entry["label"],
                regex=regex,
                validator=validator,  # type: ignore[arg-type]
                sensitivity=Sensitivity(entry.get("sensitivity", "medium")),
                description=entry.get("description", ""),
                requires_context=tuple(
                    keyword.lower() for keyword in entry.get("requires_context", [])
                ),
                context_window=int(entry.get("context_window", 60)),
            )
        )
    if not patterns:
        raise CatalogError(f"PII catalogue at {path} is empty")
    return tuple(patterns)


@lru_cache(maxsize=4)
def _cached_patterns(path: Path) -> tuple[PiiPattern, ...]:
    return load_patterns(path)


class Redactor:
    """Finds and pseudonymises PII in a text."""

    def __init__(self, patterns: Sequence[PiiPattern]) -> None:
        self._patterns = tuple(patterns)

    @classmethod
    def from_catalogue(cls, path: Path) -> Redactor:
        return cls(_cached_patterns(path))

    # ------------------------------------------------------------------ scan
    def scan(self, text: str) -> tuple[PiiMatch, ...]:
        """All validated, non-overlapping PII matches, in document order."""
        return tuple(self._resolve_overlaps(self._candidates(text)))

    def _candidates(self, text: str) -> Iterator[PiiMatch]:
        for pattern in self._patterns:
            for match in pattern.regex.finditer(text):
                raw = match.group(0)
                if not pattern.validator(raw):
                    continue
                if not pattern.context_satisfied(text, match.start(), match.end()):
                    continue
                yield PiiMatch(
                    start=match.start(),
                    end=match.end(),
                    pattern_id=pattern.id,
                    label=pattern.label,
                    raw=raw,
                    sensitivity=pattern.sensitivity,
                )

    @staticmethod
    def _resolve_overlaps(candidates: Iterator[PiiMatch]) -> list[PiiMatch]:
        """Keep the strongest claim on each stretch of text.

        A twelve-digit Aadhaar also matches the bank-account pattern.  Preferring
        higher sensitivity, then the longer match, means the value is labelled as
        the more dangerous of the two rather than the one that happened to be
        earlier in the catalogue.
        """
        ordered = sorted(
            candidates,
            key=lambda m: (-_SENSITIVITY_RANK[m.sensitivity], -m.length, m.start),
        )
        kept: list[PiiMatch] = []
        for candidate in ordered:
            if any(candidate.start < k.end and k.start < candidate.end for k in kept):
                continue
            kept.append(candidate)
        return sorted(kept, key=lambda m: m.start)

    # ------------------------------------------------------------------ redact
    def redact(self, text: str) -> RedactionResult:
        """Replace PII with stable placeholders, preserving offsets via a map."""
        matches = self.scan(text)
        if not matches:
            return RedactionResult(
                text=text, offset_map=OffsetMap.identity(len(text)), matches=(), vault={}
            )

        counters: dict[str, int] = {}
        assigned: dict[tuple[str, str], str] = {}
        vault: dict[str, str] = {}
        replacements: list[Replacement] = []

        for match in matches:
            # Key on (label, normalised value) so the same person or number keeps
            # one placeholder across the whole document.
            key = (match.label, _normalise(match.raw))
            placeholder = assigned.get(key)
            if placeholder is None:
                counters[match.label] = counters.get(match.label, 0) + 1
                placeholder = f"[[{match.label}_{counters[match.label]}]]"
                assigned[key] = placeholder
                vault[placeholder] = match.raw
            replacements.append(Replacement(match.start, match.end, placeholder))

        redacted_text, offset_map = OffsetMap.apply(text, replacements)
        return RedactionResult(
            text=redacted_text, offset_map=offset_map, matches=matches, vault=vault
        )


def _normalise(value: str) -> str:
    """Fold spacing and case so ``1234 5678`` and ``1234-5678`` share a placeholder."""
    return re.sub(r"[\s\-]", "", value).casefold()


def scrub(value: str, redactor: Redactor) -> str:
    """Strip PII from a string bound for a log sink.

    Logs outlive requests and are copied into systems with weaker access control
    than the application, so nothing identifying goes into one even when the
    request that produced it was legitimate.
    """
    return redactor.redact(value).text
