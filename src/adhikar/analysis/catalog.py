"""Loader for the clause taxonomy.

The catalogue is the product's domain knowledge and this module is its only
reader.  Nothing downstream constructs a clause type, a risk rule or a baseline
position by hand; if it is not in the YAML, the system does not know it.

Validation is strict and happens at load: an unknown severity, an invalid regex
or a risk rule with an empty condition raises rather than being skipped.  A rule
that silently never fires is worse than a server that refuses to start, because
the first looks like a clean contract.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from adhikar.analysis.rules import Condition, compile_condition
from adhikar.domain import Severity
from adhikar.errors import CatalogError


@dataclass(frozen=True, slots=True)
class RiskRule:
    """One detectable problem within a clause type."""

    id: str
    clause_type: str
    severity: Severity
    title: str
    condition: Condition
    why_it_matters: str
    questions_for_lawyer: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Baseline:
    """What a balanced version of this clause looks like."""

    expected: str
    favourable_markers: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True, slots=True)
class ClauseType:
    """A category of contract clause, with how to find it and what can go wrong."""

    id: str
    title: str
    plain_language: str
    detectors: Condition
    baseline: Baseline | None
    risks: tuple[RiskRule, ...]

    def detect(self, text: str) -> float:
        """Confidence that ``text`` is a clause of this type, in [0, 1].

        Confidence is the share of distinct detector alternatives that fire, so a
        clause matching three liability markers outranks one matching a single
        stray keyword. This is what lets the typer pick between candidate types
        without a model call.
        """
        match = self.detectors.evaluate(text)
        if match is None:
            return 0.0
        alternatives = len(self.detectors.any_of) or 1
        hits = len(set(match.ranges))
        return min(1.0, 0.5 + 0.5 * min(hits, alternatives) / alternatives)


class ClauseCatalog:
    """The loaded taxonomy."""

    __slots__ = ("_by_id", "_types", "version")

    def __init__(self, types: Sequence[ClauseType], version: int) -> None:
        self._types = tuple(types)
        self._by_id = {t.id: t for t in self._types}
        self.version = version
        if len(self._by_id) != len(self._types):
            raise CatalogError("clause catalogue contains duplicate clause type ids")

    def __iter__(self) -> Iterator[ClauseType]:
        return iter(self._types)

    def __len__(self) -> int:
        return len(self._types)

    def get(self, clause_type_id: str) -> ClauseType | None:
        return self._by_id.get(clause_type_id)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def classify(self, text: str, *, threshold: float = 0.5) -> tuple[str | None, float]:
        """Best-matching clause type for a passage, with confidence."""
        best_id: str | None = None
        best_score = 0.0
        for clause_type in self._types:
            score = clause_type.detect(text)
            if score > best_score:
                best_id, best_score = clause_type.id, score
        return (best_id, best_score) if best_score >= threshold else (None, best_score)

    def candidates(
        self, text: str, *, threshold: float = 0.5
    ) -> tuple[tuple[ClauseType, float], ...]:
        """Every clause type whose detectors fire, strongest first.

        Real clauses are not single-typed. An indemnity clause routinely also
        caps -- or declines to cap -- liability, and a termination clause often
        carries the auto-renewal notice period. Running only the best-matching
        type's rules means the second concern in a clause is never examined,
        which is precisely where uncapped exposure tends to hide.
        """
        scored = [
            (clause_type, score)
            for clause_type in self._types
            if (score := clause_type.detect(text)) >= threshold
        ]
        return tuple(sorted(scored, key=lambda pair: -pair[1]))

    def all_risks(self) -> tuple[RiskRule, ...]:
        return tuple(rule for clause_type in self._types for rule in clause_type.risks)


def load_catalog(path: Path) -> ClauseCatalog:
    """Load and validate the clause taxonomy.

    Raises:
        CatalogError: the file is missing, malformed, or semantically invalid.
    """
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"clause catalogue not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"clause catalogue at {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "clause_types" not in raw:
        raise CatalogError(f"clause catalogue at {path} has no 'clause_types' key")

    types: list[ClauseType] = []
    for entry in raw["clause_types"]:
        type_id = entry.get("id")
        if not type_id:
            raise CatalogError("a clause type is missing its 'id'")
        context = f"clause type '{type_id}'"

        detectors = compile_condition(entry.get("detectors"), context=context)
        if detectors.is_empty:
            raise CatalogError(f"{context}: has no detectors and could never match")

        baseline = None
        if "baseline" in entry:
            block = entry["baseline"]
            baseline = Baseline(
                expected=block["expected"].strip(),
                favourable_markers=tuple(
                    re.compile(p, re.IGNORECASE | re.DOTALL)
                    for p in block.get("favourable_markers", ())
                ),
            )

        risks: list[RiskRule] = []
        for rule in entry.get("risks", ()):
            rule_context = f"{context}, risk '{rule.get('id', '?')}'"
            condition = compile_condition(rule.get("when"), context=rule_context)
            if condition.is_empty:
                raise CatalogError(f"{rule_context}: has an empty condition and could never fire")
            try:
                severity = Severity(rule["severity"])
            except (KeyError, ValueError) as exc:
                raise CatalogError(
                    f"{rule_context}: missing or unknown severity {rule.get('severity')!r}"
                ) from exc
            risks.append(
                RiskRule(
                    id=rule["id"],
                    clause_type=type_id,
                    severity=severity,
                    title=rule["title"].strip(),
                    condition=condition,
                    why_it_matters=rule["why_it_matters"].strip(),
                    questions_for_lawyer=tuple(
                        q.strip() for q in rule.get("questions_for_lawyer", ())
                    ),
                )
            )

        types.append(
            ClauseType(
                id=type_id,
                title=entry["title"].strip(),
                plain_language=entry["plain_language"].strip(),
                detectors=detectors,
                baseline=baseline,
                risks=tuple(risks),
            )
        )

    if not types:
        raise CatalogError(f"clause catalogue at {path} defines no clause types")
    return ClauseCatalog(types, version=int(raw.get("version", 1)))


@lru_cache(maxsize=4)
def get_catalog(path: Path) -> ClauseCatalog:
    """Process-wide cached catalogue."""
    return load_catalog(path)
