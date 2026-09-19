"""Document and audit storage.

The storage split is a privacy decision, not an implementation convenience:

**Documents are never written to disk.**  They live in a per-process store with a
time-to-live and are evicted automatically.  A contract is the most sensitive
thing a user owns, and the safest place for it is nowhere -- if the service is
compromised tomorrow, yesterday's uploads are not in it.  This costs horizontal
scalability, which is the right trade for a tool handling other people's legal
documents, and the boundary is drawn here so that adding a shared cache later is
a deliberate decision someone has to make rather than a default someone inherits.

**Audit records are persisted.**  They contain hashes, counts and decisions --
never document text, never PII -- so they are safe to keep, and keeping them is
the whole point of an audit trail.

Both stores are behind protocols so tests and future backends substitute cleanly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from adhikar.errors import NotFoundError
from adhikar.pipeline import IngestOutcome
from adhikar.security.audit import AuditRecord


@dataclass(slots=True)
class _Entry:
    outcome: IngestOutcome
    expires_at: float


class DocumentStore(Protocol):
    """Somewhere to keep a document between requests in one session."""

    async def put(self, outcome: IngestOutcome) -> str: ...
    async def get(self, document_id: str) -> IngestOutcome: ...
    async def delete(self, document_id: str) -> bool: ...
    async def list_ids(self) -> tuple[str, ...]: ...


class MemoryDocumentStore:
    """In-process store with TTL eviction and a hard capacity limit.

    The capacity limit matters: without it, an unauthenticated upload endpoint is
    a memory-exhaustion denial of service. Eviction is oldest-first once the cap
    is reached, which is correct for a working store where the newest document is
    the one being analysed.
    """

    def __init__(self, *, ttl_seconds: float = 3600.0, max_documents: int = 50) -> None:
        self._entries: dict[str, _Entry] = {}
        self._ttl = ttl_seconds
        self._max = max_documents
        self._lock = asyncio.Lock()

    async def put(self, outcome: IngestOutcome) -> str:
        async with self._lock:
            self._evict_expired()
            while len(self._entries) >= self._max:
                oldest = min(self._entries, key=lambda k: self._entries[k].expires_at)
                del self._entries[oldest]
            self._entries[outcome.document.id] = _Entry(
                outcome=outcome, expires_at=time.monotonic() + self._ttl
            )
            return outcome.document.id

    async def get(self, document_id: str) -> IngestOutcome:
        async with self._lock:
            self._evict_expired()
            entry = self._entries.get(document_id)
            if entry is None:
                raise NotFoundError(f"document {document_id} is not available")
            return entry.outcome

    async def delete(self, document_id: str) -> bool:
        async with self._lock:
            return self._entries.pop(document_id, None) is not None

    async def list_ids(self) -> tuple[str, ...]:
        async with self._lock:
            self._evict_expired()
            return tuple(self._entries)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._entries.items() if v.expires_at <= now]:
            del self._entries[key]

    @property
    def size(self) -> int:
        return len(self._entries)


class AuditStore(Protocol):
    """Durable, append-only storage for audit records."""

    async def append(self, record: AuditRecord) -> None: ...
    async def recent(self, limit: int = 50) -> tuple[AuditRecord, ...]: ...
    async def head(self) -> str: ...


class MemoryAuditStore:
    """Audit store for tests and for running without a database."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = asyncio.Lock()

    async def append(self, record: AuditRecord) -> None:
        async with self._lock:
            self._records.append(record)

    async def recent(self, limit: int = 50) -> tuple[AuditRecord, ...]:
        async with self._lock:
            return tuple(self._records[-limit:][::-1])

    async def head(self) -> str:
        from adhikar.security.audit import GENESIS

        async with self._lock:
            return self._records[-1].record_hash if self._records else GENESIS

    async def extend(self, records: Iterable[AuditRecord]) -> None:
        async with self._lock:
            self._records.extend(records)
