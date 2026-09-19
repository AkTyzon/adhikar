"""HTTP-layer security controls.

Three concerns, each small enough to read in full:

**Response headers.** A strict Content-Security-Policy is the main defence
against a document's contents becoming executable in a reader's browser. The
policy here has no ``unsafe-inline``: styles and scripts are served as files, and
the one piece of per-request data the page needs is passed through a
``data-*`` attribute rather than an inline script block.

**Rate limiting.** A token bucket per client, with a tighter bucket for uploads,
because parsing a PDF costs far more than serving a page.

**Request identity.** Every request carries an id, into the response headers and
into every log line, so an error a user reports can be found in the log without
searching by content.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from adhikar.config import Settings

REQUEST_ID_HEADER: Final = "X-Request-ID"

#: No 'unsafe-inline' anywhere. Document text is rendered as escaped text, but a
#: policy that would survive an escaping bug is worth more than one that assumes
#: there will never be one.
CONTENT_SECURITY_POLICY: Final = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        # Uploaded documents must never trigger an outbound request.
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
    )
)

SECURITY_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    # Uploaded documents are confidential; nothing about them should be cached.
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers and a request id to every response."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        response.headers[REQUEST_ID_HEADER] = request_id
        # Static assets are safe to cache and are the bulk of the bytes.
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response


@dataclass
class _Bucket:
    tokens: float
    updated_at: float = field(default_factory=time.monotonic)


class TokenBucketLimiter:
    """Per-client rate limiter.

    In-process by design, matching the in-process document store: this service
    keeps a session's state in one worker. A multi-worker deployment needs a
    shared backend, and :meth:`check` is the single place that would change.
    """

    def __init__(self, *, capacity: int, window_seconds: float) -> None:
        self._capacity = float(capacity)
        self._rate = capacity / window_seconds if window_seconds > 0 else float("inf")
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(tokens=float(capacity)))

    def check(self, key: str, *, cost: float = 1.0) -> tuple[bool, int]:
        """Consume ``cost`` tokens. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        bucket = self._buckets[key]
        elapsed = now - bucket.updated_at
        bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._rate)
        bucket.updated_at = now

        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return True, 0
        deficit = cost - bucket.tokens
        return False, max(1, int(deficit / self._rate) + 1)

    def reset(self) -> None:
        self._buckets.clear()


def client_key(request: Request) -> str:
    """Identify a client for rate limiting.

    Uses the socket address only. ``X-Forwarded-For`` is deliberately ignored:
    it is client-controlled, so trusting it hands any caller an unlimited supply
    of identities. Behind a proxy, configure the proxy to rewrite the socket
    address, or add an explicitly trusted-proxy check here.
    """
    if request.client is None:
        return "unknown"
    return request.client.host


def build_limiters(settings: Settings) -> tuple[TokenBucketLimiter, TokenBucketLimiter]:
    """The general and upload limiters."""
    general = TokenBucketLimiter(
        capacity=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    uploads = TokenBucketLimiter(
        capacity=settings.upload_rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    return general, uploads
