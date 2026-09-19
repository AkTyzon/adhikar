"""Exception hierarchy.

Every exception carries an HTTP status and a stable ``code``.  The API layer
renders these into a uniform problem response; nothing else in the codebase
formats an error string for the wire.  The distinction that matters for security
is :attr:`AdhikarError.safe_detail` -- what may be shown to a caller -- versus the
exception's full message, which goes only to the server log.  Path names, SQL
fragments and document contents must never cross that line.
"""

from __future__ import annotations

from typing import Any


class AdhikarError(Exception):
    """Base class. Subclasses set ``status_code`` and ``code``."""

    status_code: int = 500
    code: str = "internal_error"
    #: Message shown to the caller. Overridden per-subclass; deliberately generic
    #: on server-side failures so internals cannot leak through an error path.
    safe_detail: str = "An internal error occurred."

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #


class IngestError(AdhikarError):
    status_code = 400
    code = "ingest_failed"
    safe_detail = "The document could not be read."


class UnsupportedMediaTypeError(IngestError):
    status_code = 415
    code = "unsupported_media_type"
    safe_detail = "Only PDF, DOCX and plain-text documents are accepted."


class DocumentTooLargeError(IngestError):
    status_code = 413
    code = "document_too_large"
    safe_detail = "The document exceeds the configured size limit."


class MalformedDocumentError(IngestError):
    code = "malformed_document"
    safe_detail = "The document is corrupt or could not be parsed."


class EmptyDocumentError(IngestError):
    code = "empty_document"
    safe_detail = "No extractable text was found in the document."


# --------------------------------------------------------------------------- #
# Security
# --------------------------------------------------------------------------- #


class SecurityError(AdhikarError):
    status_code = 400
    code = "security_violation"
    safe_detail = "The request was rejected by a security control."


class DocumentQuarantinedError(SecurityError):
    """Raised when a document's embedded-instruction risk exceeds the block threshold."""

    status_code = 422
    code = "document_quarantined"
    safe_detail = (
        "This document contains text that appears designed to manipulate an AI system. "
        "It has been quarantined rather than analysed."
    )


class RateLimitedError(AdhikarError):
    status_code = 429
    code = "rate_limited"
    safe_detail = "Too many requests. Please retry shortly."

    def __init__(self, message: str, *, retry_after: int, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


# --------------------------------------------------------------------------- #
# Provenance and verification
# --------------------------------------------------------------------------- #


class SpanResolutionError(AdhikarError):
    """A span does not resolve against its document.

    In practice this means either the document changed underneath a stored
    analysis, or a model invented offsets.  Both are integrity failures and both
    must stop the pipeline rather than degrade it.
    """

    status_code = 500
    code = "span_resolution_failed"
    safe_detail = "A cited passage could not be verified against the source document."


class VerificationError(AdhikarError):
    status_code = 502
    code = "verification_failed"
    safe_detail = "The answer could not be verified and has been withheld."


# --------------------------------------------------------------------------- #
# Model providers
# --------------------------------------------------------------------------- #


class ProviderError(AdhikarError):
    status_code = 502
    code = "provider_error"
    safe_detail = "The language model backend is unavailable."


class ProviderTimeoutError(ProviderError):
    status_code = 504
    code = "provider_timeout"
    safe_detail = "The language model backend timed out."


class SchemaViolationError(ProviderError):
    """The model returned output that does not satisfy the requested schema."""

    code = "schema_violation"
    safe_detail = "The language model returned an unusable response."


# --------------------------------------------------------------------------- #
# Configuration and lookup
# --------------------------------------------------------------------------- #


class ConfigurationError(AdhikarError):
    code = "configuration_error"
    safe_detail = "The server is misconfigured."


class CatalogError(ConfigurationError):
    code = "catalog_error"
    safe_detail = "The server is misconfigured."


class NotFoundError(AdhikarError):
    status_code = 404
    code = "not_found"
    safe_detail = "The requested resource does not exist."
