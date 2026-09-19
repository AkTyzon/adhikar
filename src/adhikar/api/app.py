"""Application factory.

Dependencies are constructed once at startup and attached to ``app.state``, then
handed to routes through FastAPI's dependency system.  Nothing reaches for a
module-level global, which is what makes the whole application constructible in a
test with different settings and a different engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.templating import Jinja2Templates

from adhikar import __version__
from adhikar import logging as app_logging
from adhikar.api.security import SecurityHeadersMiddleware, build_limiters
from adhikar.config import Environment, Settings, get_settings
from adhikar.errors import AdhikarError, RateLimitedError
from adhikar.llm.registry import build_provider
from adhikar.pipeline import Pipeline
from adhikar.store import MemoryAuditStore, MemoryDocumentStore

WEB_DIR = Path(__file__).parent.parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: Override configuration. Tests pass their own rather than
            mutating the environment.
    """
    resolved = settings or get_settings()
    app_logging.configure(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        provider = build_provider(resolved)
        app.state.settings = resolved
        app.state.provider = provider
        app.state.pipeline = Pipeline(resolved, provider)
        app.state.documents = MemoryDocumentStore()
        app.state.audit = MemoryAuditStore()
        general, uploads = build_limiters(resolved)
        app.state.limiter = general
        app.state.upload_limiter = uploads
        yield
        # Documents are held only in memory; dropping the store is the whole of
        # shutdown cleanup, and it is also the privacy guarantee.
        app.state.documents = None

    app = FastAPI(
        title="Adhikar",
        version=__version__,
        description=(
            "Verifiable legal-document analysis. Every statement is anchored to a "
            "passage in your document and checked against it before you see it."
        ),
        lifespan=lifespan,
        # Interactive docs are useful in development and are attack surface in
        # production, where the UI is the product.
        docs_url="/api/docs" if resolved.environment is not Environment.PRODUCTION else None,
        redoc_url=None,
        openapi_url=(
            "/api/openapi.json" if resolved.environment is not Environment.PRODUCTION else None
        ),
    )

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=resolved.environment is Environment.PRODUCTION,
    )
    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    # Autoescaping is on by default in Jinja2Templates; this makes the guarantee
    # explicit, because every page renders untrusted document text.
    templates.env.autoescape = True
    app.state.templates = templates

    _register_error_handlers(app, resolved)

    from adhikar.api.routes import router as api_router
    from adhikar.web.routes import router as web_router

    app.include_router(api_router)
    app.include_router(web_router)
    return app


def _register_error_handlers(app: FastAPI, settings: Settings) -> None:
    """Render every error through one uniform, non-leaking path."""

    @app.exception_handler(AdhikarError)
    async def _handle_known(request: Request, exc: AdhikarError) -> JSONResponse:
        log = app_logging.get_logger("adhikar.error")
        log.warning(
            "request_failed",
            code=exc.code,
            operation=request.url.path,
            request_id=getattr(request.state, "request_id", None),
            # The full message goes to the log; only safe_detail goes to the client.
            detail=exc.message,
        )
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitedError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.safe_detail,
                    "request_id": getattr(request.state, "request_id", None),
                    **({"context": exc.context} if exc.context else {}),
                }
            },
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log = app_logging.get_logger("adhikar.error")
        log.error(
            "unhandled_exception",
            operation=request.url.path,
            request_id=getattr(request.state, "request_id", None),
            exc_info=exc,
        )
        # Never echo an unexpected exception: its message may contain a path, a
        # query fragment, or document text.
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An internal error occurred.",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )


def get_pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline  # type: ignore[no-any-return]


def get_documents(request: Request) -> Any:
    return request.app.state.documents


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def enforce_rate_limit(request: Request, *, upload: bool = False) -> None:
    """Apply the appropriate bucket, raising if the client is over budget."""
    from adhikar.api.security import client_key

    limiter = request.app.state.upload_limiter if upload else request.app.state.limiter
    allowed, retry_after = limiter.check(client_key(request))
    if not allowed:
        raise RateLimitedError("rate limit exceeded", retry_after=retry_after)
