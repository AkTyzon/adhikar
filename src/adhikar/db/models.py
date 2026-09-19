"""Persistence for audit records.

Only audit records are persisted. Documents are not -- see :mod:`adhikar.store`
for why that is a deliberate privacy posture rather than an omission.

The schema stores the hash chain alongside the payload so that
:func:`adhikar.security.audit.verify_chain` can be run against what is on disk,
not merely against what is in memory. An audit log you cannot verify after a
restart is decoration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from adhikar.security.audit import AuditRecord, StageTiming


class Base(DeclarativeBase):
    pass


class AuditRecordRow(Base):
    """One sealed audit record."""

    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    #: Hash of the document, never the document. Lets an operator correlate runs
    #: on the same file without the file being recoverable from the log.
    document_sha256: Mapped[str] = mapped_column(String(64), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    injection_score: Mapped[float] = mapped_column(Float, default=0.0)
    claims_admitted: Mapped[int] = mapped_column(Integer, default=0)
    claims_withheld: Mapped[int] = mapped_column(Integer, default=0)
    span_integrity_failures: Mapped[int] = mapped_column(Integer, default=0)
    #: The full canonical payload, so the record's hash can be recomputed exactly.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)

    __table_args__ = (Index("ix_audit_chain", "prev_hash", "record_hash"),)

    @classmethod
    def from_record(cls, record: AuditRecord) -> AuditRecordRow:
        return cls(
            run_id=record.run_id,
            created_at=record.created_at,
            operation=record.operation,
            document_sha256=record.document_sha256,
            engine=record.engine,
            model=record.model,
            scope_intent=record.scope_intent,
            scope_mode=record.scope_mode,
            injection_score=record.injection_score,
            claims_admitted=record.claims_admitted,
            claims_withheld=record.claims_withheld,
            span_integrity_failures=record.span_integrity_failures,
            payload=record.payload(),
            prev_hash=record.prev_hash,
            record_hash=record.record_hash,
        )

    def to_record(self) -> AuditRecord:
        """Rebuild the domain object, including its timings, for verification."""
        payload = self.payload if isinstance(self.payload, dict) else json.loads(self.payload)
        return AuditRecord(
            run_id=payload["run_id"],
            created_at=datetime.fromisoformat(payload["created_at"]).astimezone(UTC),
            operation=payload["operation"],
            document_sha256=payload["document_sha256"],
            engine=payload["engine"],
            model=payload["model"],
            prompt_versions=payload.get("prompt_versions", {}),
            scope_intent=payload.get("scope_intent"),
            scope_mode=payload.get("scope_mode"),
            injection_score=payload.get("injection_score", 0.0),
            injection_signal_ids=tuple(payload.get("injection_signal_ids", ())),
            redaction_counts=payload.get("redaction_counts", {}),
            claims_admitted=payload.get("claims_admitted", 0),
            claims_withheld=payload.get("claims_withheld", 0),
            span_integrity_failures=payload.get("span_integrity_failures", 0),
            timings=tuple(
                StageTiming(
                    stage=t["stage"],
                    duration_ms=t["duration_ms"],
                    input_tokens=t.get("input_tokens"),
                    output_tokens=t.get("output_tokens"),
                    cached_input_tokens=t.get("cached_input_tokens"),
                )
                for t in payload.get("timings", ())
            ),
            prev_hash=payload["prev_hash"],
            record_hash=self.record_hash,
        )
