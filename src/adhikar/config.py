"""Runtime configuration.

Settings come from the environment (12-factor) with safe defaults, so a fresh
clone runs with no secrets at all: the offline engine is selected automatically
when no API key is present.  Every limit that protects the server -- upload size,
page count, token budget, rate limits -- is a setting rather than a literal
buried in a handler, so an operator can tighten them without a code change.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Engine(StrEnum):
    """Which inference backend serves analysis requests."""

    #: Deterministic, dependency-free engine. No network, no key, fully reproducible.
    #: This is what CI and the test suite run against.
    OFFLINE = "offline"
    #: Anthropic Claude via the official SDK.
    ANTHROPIC = "anthropic"
    #: Pick Anthropic when a key is configured, otherwise offline.
    AUTO = "auto"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ADHIKAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ------------------------------------------------------------------ app
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    base_path: Path = Field(default_factory=Path.cwd)

    # ------------------------------------------------------------------ model
    engine: Engine = Engine.AUTO
    anthropic_api_key: SecretStr | None = None
    #: Primary reasoning model. Extraction, clause typing and drafting run here.
    model: str = "claude-opus-5"
    #: Verifier model. Deliberately configurable so the entailment gate can be run
    #: on a *different* model from the generator -- an independent checker is
    #: harder to talk past than the model that produced the claim.
    verifier_model: str = "claude-opus-5"
    effort: str = "high"
    max_output_tokens: int = 16_000
    request_timeout_seconds: float = 120.0
    max_retries: int = 2
    #: Cache the document prefix so follow-up questions on the same contract do not
    #: re-pay for the full text. Verified via usage.cache_read_input_tokens.
    enable_prompt_caching: bool = True

    # ------------------------------------------------------------------ storage
    database_url: str = "sqlite+aiosqlite:///./adhikar.db"

    # ------------------------------------------------------------------ ingest limits
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 300
    max_document_chars: int = 1_500_000
    #: A PDF whose text expands beyond this ratio of its byte size is treated as a
    #: decompression bomb and rejected before parsing completes.
    max_expansion_ratio: float = 200.0

    # ------------------------------------------------------------------ security
    #: Documents scoring at or above this are refused outright.
    injection_block_threshold: float = 0.80
    #: Documents at or above this are analysed but flagged prominently to the user.
    injection_warn_threshold: float = 0.35
    redact_pii: bool = True
    #: Minimum verifier confidence for a claim to be shown as fact.
    verification_threshold: float = 0.70
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60
    upload_rate_limit_requests: int = 10
    #: Comma-separated origins for CORS. Empty means same-origin only, which is the
    #: correct default for a server-rendered app.
    cors_origins: tuple[str, ...] = ()

    # ------------------------------------------------------------------ knowledge
    #: Directory holding the clause catalogue, baselines and injection signatures.
    #: All domain knowledge lives here as data; no clause text appears in Python.
    knowledge_dir: Path | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @field_validator("effort")
    @classmethod
    def _known_effort(cls, value: str) -> str:
        allowed = {"low", "medium", "high", "xhigh", "max"}
        if value not in allowed:
            raise ValueError(f"effort must be one of {sorted(allowed)}")
        return value

    @model_validator(mode="after")
    def _production_is_strict(self) -> Self:
        """Refuse to start a production server in a knowingly unsafe posture."""
        if self.environment is Environment.PRODUCTION:
            if self.debug:
                raise ValueError("debug must be disabled in production")
            if not self.redact_pii:
                raise ValueError("PII redaction cannot be disabled in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not a supported production database")
        return self

    @property
    def resolved_engine(self) -> Engine:
        """The engine that will actually serve requests."""
        if self.engine is not Engine.AUTO:
            return self.engine
        return Engine.ANTHROPIC if self.anthropic_api_key else Engine.OFFLINE

    @property
    def knowledge_path(self) -> Path:
        """Where clause knowledge is loaded from."""
        if self.knowledge_dir is not None:
            return self.knowledge_dir
        return Path(__file__).parent / "analysis" / "knowledge"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that reading configuration is free at call sites; tests clear the
    cache via :func:`reset_settings` rather than mutating a global.
    """
    return Settings()


def reset_settings() -> None:
    """Drop the cached settings. For tests and for reload-on-signal."""
    get_settings.cache_clear()
