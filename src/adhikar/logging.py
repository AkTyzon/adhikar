"""Structured logging with PII scrubbing.

Logs outlive the requests that produced them and are routinely copied into
systems with weaker access control than the application itself.  A legal-document
service that writes contract text, party names or identifiers into a log has
moved the user's data somewhere they never agreed to -- so the scrubber is a
processor in the pipeline rather than a convention people are asked to follow.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from adhikar.config import Environment, Settings

#: Strings shorter than this cannot contain a redactable identifier, and
#: scanning every short field would cost more than it protects.
_MIN_SCRUBBABLE_CHARS = 8


def _scrub_processor(redactor_path: Any) -> Any:
    """Build a structlog processor that redacts PII from every rendered value."""
    from adhikar.security.redaction import Redactor

    redactor = Redactor.from_catalogue(redactor_path)

    def scrub(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        for key, value in event_dict.items():
            if isinstance(value, str) and len(value) > _MIN_SCRUBBABLE_CHARS:
                event_dict[key] = redactor.redact(value).text
        return event_dict

    return scrub


def configure(settings: Settings) -> None:
    """Configure structlog once, at startup."""
    renderer = (
        structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
        if settings.environment is not Environment.PRODUCTION
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            # Scrubbing runs last before rendering, so it also covers values added
            # by earlier processors and by exception formatting.
            _scrub_processor(settings.knowledge_path / "pii_patterns.yaml"),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
