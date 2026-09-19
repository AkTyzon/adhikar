"""Engine selection.

One place decides which backend serves a request, so the decision is testable and
appears in exactly one line of the audit record.  The default is deliberate: with
no API key configured, the system selects the offline engine and works, rather
than failing at startup with a missing-credential error.
"""

from __future__ import annotations

from functools import lru_cache

from adhikar.analysis.catalog import get_catalog
from adhikar.analysis.glossary import get_glossary
from adhikar.config import Engine, Settings
from adhikar.errors import ConfigurationError
from adhikar.llm.base import ModelProvider


def build_provider(settings: Settings) -> ModelProvider:
    """Construct the provider the settings select."""
    engine = settings.resolved_engine

    if engine is Engine.OFFLINE:
        from adhikar.llm.offline import OfflineEngine

        return OfflineEngine(
            catalog=get_catalog(settings.knowledge_path / "clauses.yaml"),
            glossary=get_glossary(settings.knowledge_path / "glossary.yaml"),
        )

    if engine is Engine.ANTHROPIC:
        if settings.anthropic_api_key is None:
            raise ConfigurationError(
                "engine 'anthropic' was selected but ADHIKAR_ANTHROPIC_API_KEY is not set"
            )
        from adhikar.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)

    raise ConfigurationError(f"unknown engine {engine!r}")


@lru_cache(maxsize=2)
def get_provider(settings: Settings) -> ModelProvider:
    """Cached provider for the running process."""
    return build_provider(settings)
