"""Legal vocabulary: query expansion and plain-language lookup.

The gap between how a person asks ("what are the payment terms?") and how a
contract is drafted ("Fees", "remuneration", "consideration") is not a search
problem to be optimised away -- it is the substance of what makes legal documents
inaccessible.  Closing it is a product feature, and the same data serves the
on-page glossary that explains terms where they appear.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from adhikar.errors import CatalogError


@dataclass(frozen=True, slots=True)
class Term:
    term: str
    plain: str
    synonyms: tuple[str, ...]

    @property
    def all_forms(self) -> tuple[str, ...]:
        return (self.term, *self.synonyms)


class Glossary:
    """Bidirectional vocabulary between plain language and legal drafting."""

    __slots__ = ("_by_form", "_terms")

    def __init__(self, terms: tuple[Term, ...]) -> None:
        self._terms = terms
        self._by_form: dict[str, Term] = {}
        for entry in terms:
            for form in entry.all_forms:
                self._by_form.setdefault(form.casefold(), entry)

    def __iter__(self) -> Iterator[Term]:
        return iter(self._terms)

    def __len__(self) -> int:
        return len(self._terms)

    def lookup(self, word: str) -> Term | None:
        return self._by_form.get(word.casefold())

    def expand(self, query: str) -> tuple[str, ...]:
        """Add drafting-language equivalents to a plain-language query.

        Multi-word terms are matched first so "payment terms" expands as a phrase
        rather than as "payment" and "terms" separately.
        """
        lowered = query.casefold()
        expansions: list[str] = []

        for entry in self._terms:
            for form in entry.all_forms:
                if len(form.split()) > 1 and form.casefold() in lowered:
                    expansions.extend(entry.all_forms)
                    break

        for word in re.findall(r"[a-z]+", lowered):
            match = self._by_form.get(word)
            if match is not None:
                expansions.extend(match.all_forms)

        seen: dict[str, None] = {}
        for item in expansions:
            for word in re.findall(r"[a-z]+", item.casefold()):
                seen.setdefault(word, None)
        return tuple(seen)

    def present_in(self, text: str, limit: int = 20) -> tuple[Term, ...]:
        """Terms from the glossary that actually occur in a document."""
        lowered = text.casefold()
        found = [
            entry
            for entry in self._terms
            if any(form.casefold() in lowered for form in entry.all_forms)
        ]
        return tuple(found[:limit])


def load_glossary(path: Path) -> Glossary:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"glossary not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"glossary at {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "terms" not in raw:
        raise CatalogError(f"glossary at {path} has no 'terms' key")

    return Glossary(
        tuple(
            Term(
                term=entry["term"],
                plain=entry["plain"].strip(),
                synonyms=tuple(entry.get("synonyms", ())),
            )
            for entry in raw["terms"]
        )
    )


@lru_cache(maxsize=4)
def get_glossary(path: Path) -> Glossary:
    return load_glossary(path)
