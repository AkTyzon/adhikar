"""Scope-of-assistance gate.

Adhikar is required -- by the brief it was built for, and by the law in most
jurisdictions -- to provide information rather than legal advice.  A disclaimer
printed beneath an answer does not achieve that: by the time the user reads it,
the advice has already been given.

So the boundary is enforced upstream, as routing.  A question is classified into
an intent, the intent selects a :class:`ResponseMode`, and the mode selects the
*output schema* the generation stage must satisfy.  The advisory modes do not
define a field in which a recommendation could be placed, so an ignored prompt
instruction -- or a successful injection -- still cannot produce one.  The
classification is recorded in the audit trail alongside the answer.

Classification is lexical and deterministic.  That is a deliberate trade: it is
inspectable, testable, costs nothing, and cannot itself be manipulated by the
document under analysis.  It over-triggers on some phrasings, and over-triggering
is the safe direction -- the worst outcome is that a user is handed lawyer
questions alongside an answer they could have had directly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from adhikar.errors import CatalogError


class Intent(StrEnum):
    INFORMATION = "information"
    INTERPRETATION = "interpretation"
    ADVICE = "advice"
    PREDICTION = "prediction"
    REPRESENTATION = "representation"


class ResponseMode(StrEnum):
    """What a response is permitted to contain.

    The generation stage reads this to choose a schema; see
    :mod:`adhikar.analysis.qa`.  ``REFER_OUT`` skips generation altogether.
    """

    ANSWER = "answer"
    EXPLAIN = "explain"
    INFORM_AND_PREPARE = "inform_and_prepare"
    REFER_OUT = "refer_out"


@dataclass(frozen=True, slots=True)
class ModePolicy:
    """The rules attached to a response mode, loaded from the policy catalogue."""

    mode: ResponseMode
    description: str
    allows_claims: bool
    allows_recommendation: bool
    boundary_notice: str | None


@dataclass(frozen=True, slots=True)
class IntentRule:
    intent: Intent
    mode: ResponseMode
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    """The gate's ruling on one question."""

    intent: Intent
    mode: ResponseMode
    policy: ModePolicy
    matched_pattern: str | None

    @property
    def in_scope(self) -> bool:
        """Whether the question can be answered from documents at all."""
        return self.mode is not ResponseMode.REFER_OUT

    @property
    def boundary_notice(self) -> str | None:
        return self.policy.boundary_notice


class ScopeGate:
    """Classifies questions and resolves the policy that governs the answer."""

    def __init__(
        self,
        rules: Sequence[IntentRule],
        policies: dict[ResponseMode, ModePolicy],
        default_intent: Intent,
    ) -> None:
        self._rules = tuple(rules)
        self._policies = policies
        self._default_intent = default_intent
        if ResponseMode.ANSWER not in policies:
            raise CatalogError("policy catalogue must define the 'answer' mode")

    @classmethod
    def from_catalogue(cls, path: Path) -> ScopeGate:
        return _cached_gate(path)

    def classify(self, question: str) -> ScopeDecision:
        """Resolve a question to an intent and the policy that governs it.

        Rules are evaluated in catalogue order and the first match wins, so the
        catalogue's order *is* the precedence rule. It puts the modes that refuse
        a question outright first: a question that reads as both a request for
        advice and a request for a prediction is a prediction, and gets referred
        out rather than partially answered.
        """
        normalised = " ".join(question.split())
        for rule in self._rules:
            for pattern in rule.patterns:
                if pattern.search(normalised):
                    return ScopeDecision(
                        intent=rule.intent,
                        mode=rule.mode,
                        policy=self._policies[rule.mode],
                        matched_pattern=pattern.pattern,
                    )
        default_mode = ResponseMode.ANSWER
        return ScopeDecision(
            intent=self._default_intent,
            mode=default_mode,
            policy=self._policies[default_mode],
            matched_pattern=None,
        )

    def policy_for(self, mode: ResponseMode) -> ModePolicy:
        return self._policies[mode]


def load_gate(path: Path) -> ScopeGate:
    """Load the scope policy catalogue."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"scope policy not found at {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"scope policy at {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict) or "modes" not in raw or "intents" not in raw:
        raise CatalogError(f"scope policy at {path} is missing 'intents' or 'modes'")

    policies: dict[ResponseMode, ModePolicy] = {}
    for name, body in raw["modes"].items():
        try:
            mode = ResponseMode(name)
        except ValueError as exc:
            raise CatalogError(f"scope policy defines unknown mode {name!r}") from exc
        notice = body.get("boundary_notice")
        policies[mode] = ModePolicy(
            mode=mode,
            description=body.get("description", "").strip(),
            allows_claims=bool(body["allows_claims"]),
            allows_recommendation=bool(body["allows_recommendation"]),
            boundary_notice=notice.strip() if isinstance(notice, str) else None,
        )

    # A mode that permitted recommendations would defeat the point of the gate.
    offending = [m.mode for m in policies.values() if m.allows_recommendation]
    if offending:
        raise CatalogError(
            f"scope policy permits recommendations in mode(s) {offending}; "
            "Adhikar does not issue legal advice in any mode"
        )

    rules: list[IntentRule] = []
    for entry in raw["intents"]:
        try:
            intent = Intent(entry["id"])
            mode = ResponseMode(entry["mode"])
        except ValueError as exc:
            raise CatalogError(f"scope policy has an unknown intent or mode: {exc}") from exc
        if mode not in policies:
            raise CatalogError(f"intent {intent} maps to undefined mode {mode}")
        try:
            patterns = tuple(re.compile(p, re.IGNORECASE) for p in entry["patterns"])
        except re.error as exc:
            raise CatalogError(f"intent {intent} has an invalid pattern: {exc}") from exc
        rules.append(IntentRule(intent=intent, mode=mode, patterns=patterns))

    default_intent = Intent(raw.get("default_intent", "information"))
    return ScopeGate(rules, policies, default_intent)


@lru_cache(maxsize=4)
def _cached_gate(path: Path) -> ScopeGate:
    return load_gate(path)
