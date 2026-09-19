"""Tamper-evident audit records.

Anything that informs a legal decision has to be reconstructable after the fact:
which document, which model, which prompt, which spans, which claims were shown
and which were withheld.  "The AI said so" is not a record.

Each :class:`AuditRecord` is canonicalised to deterministic JSON and hashed
together with the previous record's hash, so the log forms a chain.  Altering or
removing an entry invalidates every hash after it, which :func:`verify_chain`
detects.  This does not stop an attacker who controls the store from rewriting
the whole chain -- for that you would anchor the head externally -- but it does
make silent, selective edits infeasible, which is the realistic threat for an
audit log that mostly protects against mistakes and disputes.

Records deliberately contain **no document text and no PII**: hashes, counts,
identifiers and decisions only.  The log is safe to ship to a monitoring system
that the document itself would never be allowed to reach.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Hash of the empty chain -- the predecessor of the first record.
GENESIS = "0" * 64


def _canonical(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JSON: sorted keys, no insignificant whitespace.

    Canonicalisation is what makes the hash reproducible; a dict that serialises
    differently between runs would produce a chain that fails to verify for
    reasons unrelated to tampering.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class StageTiming:
    """Wall-clock cost of one pipeline stage, for the efficiency view."""

    stage: str
    duration_ms: float
    #: Populated for stages that called a model.
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One analysis run, reduced to what can be checked later."""

    run_id: str
    created_at: datetime
    operation: str
    document_sha256: str
    #: Which engine served the run: "offline" or "anthropic".
    engine: str
    model: str | None
    #: Hashes of the exact prompt templates used, so a prompt change is visible
    #: in the log even though the prompt text itself is not stored.
    prompt_versions: Mapping[str, str] = field(default_factory=dict)
    scope_intent: str | None = None
    scope_mode: str | None = None
    injection_score: float = 0.0
    injection_signal_ids: tuple[str, ...] = ()
    redaction_counts: Mapping[str, int] = field(default_factory=dict)
    claims_admitted: int = 0
    claims_withheld: int = 0
    span_integrity_failures: int = 0
    timings: tuple[StageTiming, ...] = ()
    prev_hash: str = GENESIS
    record_hash: str = ""

    def payload(self) -> dict[str, Any]:
        """The hashed content of this record. Excludes ``record_hash`` itself."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "operation": self.operation,
            "document_sha256": self.document_sha256,
            "engine": self.engine,
            "model": self.model,
            "prompt_versions": dict(sorted(self.prompt_versions.items())),
            "scope_intent": self.scope_intent,
            "scope_mode": self.scope_mode,
            "injection_score": round(self.injection_score, 6),
            "injection_signal_ids": list(self.injection_signal_ids),
            "redaction_counts": dict(sorted(self.redaction_counts.items())),
            "claims_admitted": self.claims_admitted,
            "claims_withheld": self.claims_withheld,
            "span_integrity_failures": self.span_integrity_failures,
            "timings": [
                {
                    "stage": t.stage,
                    "duration_ms": round(t.duration_ms, 3),
                    "input_tokens": t.input_tokens,
                    "output_tokens": t.output_tokens,
                    "cached_input_tokens": t.cached_input_tokens,
                }
                for t in self.timings
            ],
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        return hashlib.sha256(_canonical(self.payload())).hexdigest()

    def sealed(self, prev_hash: str) -> AuditRecord:
        """Return a copy linked to ``prev_hash`` with its hash computed."""
        linked = dataclasses_replace(self, prev_hash=prev_hash, record_hash="")
        return dataclasses_replace(linked, record_hash=linked.compute_hash())

    @property
    def total_duration_ms(self) -> float:
        return round(sum(t.duration_ms for t in self.timings), 3)

    @property
    def cache_hit_tokens(self) -> int:
        return sum(t.cached_input_tokens or 0 for t in self.timings)


def dataclasses_replace(record: AuditRecord, **changes: Any) -> AuditRecord:
    """``dataclasses.replace`` for a slotted frozen dataclass."""
    import dataclasses

    return dataclasses.replace(record, **changes)


def new_run_id() -> str:
    return uuid.uuid4().hex


def start_record(
    operation: str,
    *,
    document_sha256: str,
    engine: str,
    model: str | None,
    **fields: Any,
) -> AuditRecord:
    """Open a record for a run that is about to begin."""
    return AuditRecord(
        run_id=new_run_id(),
        created_at=datetime.now(UTC),
        operation=operation,
        document_sha256=document_sha256,
        engine=engine,
        model=model,
        **fields,
    )


class AuditChain:
    """An append-only, hash-linked sequence of records.

    Kept deliberately small and storage-agnostic: the API holds one of these per
    process for the in-memory case, and :mod:`adhikar.db.repository` persists the
    same records with their hashes intact.
    """

    __slots__ = ("_records",)

    def __init__(self, records: Iterable[AuditRecord] = ()) -> None:
        self._records: list[AuditRecord] = list(records)

    @property
    def head(self) -> str:
        return self._records[-1].record_hash if self._records else GENESIS

    def append(self, record: AuditRecord) -> AuditRecord:
        """Seal ``record`` against the current head and append it."""
        sealed = record.sealed(self.head)
        self._records.append(sealed)
        return sealed

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Any:
        return iter(self._records)

    def records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._records)


@dataclass(frozen=True, slots=True)
class ChainVerification:
    valid: bool
    checked: int
    first_invalid_index: int | None = None
    reason: str | None = None


def verify_chain(records: Sequence[AuditRecord]) -> ChainVerification:
    """Check that every record's hash matches its content and its predecessor.

    Returns the index of the first break rather than raising: a caller showing an
    integrity banner wants to say *where* the log diverged.
    """
    expected_prev = GENESIS
    for index, record in enumerate(records):
        if record.prev_hash != expected_prev:
            return ChainVerification(
                valid=False,
                checked=index,
                first_invalid_index=index,
                reason="record does not link to its predecessor",
            )
        if record.compute_hash() != record.record_hash:
            return ChainVerification(
                valid=False,
                checked=index,
                first_invalid_index=index,
                reason="record contents do not match its recorded hash",
            )
        expected_prev = record.record_hash
    return ChainVerification(valid=True, checked=len(records))
