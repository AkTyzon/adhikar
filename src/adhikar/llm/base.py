"""Provider-agnostic model interface.

Every model call in Adhikar is a *structured* call: the caller supplies a Pydantic
model and receives a validated instance or an exception.  There is no code path
that consumes free-form model prose, which removes a whole family of parsing
bugs and makes the offline engine substitutable for a frontier model without any
caller knowing the difference.

The protocol is intentionally narrow -- one method -- so that a new backend is a
single class, and so the test suite can assert behaviour against a deterministic
implementation rather than a network.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Task(StrEnum):
    """What a call is for.

    The offline engine dispatches on this; the Anthropic provider uses it to pick
    a prompt template and an effort level.  Keeping it an enum rather than a free
    string means an unhandled task fails at import-adjacent time rather than
    silently falling through to a generic prompt.
    """

    CLAUSE_TYPING = "clause_typing"
    ANSWER = "answer"
    VERIFY = "verify"
    SIMPLIFY = "simplify"
    OBLIGATIONS = "obligations"
    LAWYER_QUESTIONS = "lawyer_questions"


@dataclass(frozen=True, slots=True)
class DocumentContext:
    """A document made available to a call, as *data*.

    Never rendered into a system prompt. See :mod:`adhikar.llm.transcript` for how
    this is fenced.
    """

    document_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for one call, used by the efficiency view and the audit log."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )

    @property
    def cache_hit_ratio(self) -> float:
        total = self.input_tokens + self.cached_input_tokens
        return self.cached_input_tokens / total if total else 0.0


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One structured model call."""

    task: Task
    #: Operator instruction. Trusted. Never contains document text.
    instruction: str
    #: Documents the call may read. Untrusted. Fenced, never trusted as instruction.
    documents: Sequence[DocumentContext] = ()
    #: Extra trusted parameters interpolated into the prompt template.
    params: dict[str, Any] = field(default_factory=dict)
    max_output_tokens: int | None = None
    #: Whether the document prefix may be cached across calls. Safe for repeated
    #: questions about one contract; pointless for a one-shot extraction.
    cacheable: bool = True


@dataclass(frozen=True, slots=True)
class ModelResponse[TOut: BaseModel]:
    """A validated structured result plus what it cost."""

    output: TOut
    usage: Usage
    model: str
    #: Set when the provider had to repair or retry a schema-invalid response.
    repairs: int = 0


@runtime_checkable
class ModelProvider(Protocol):
    """A backend that answers structured requests.

    Implementations must be safe to call concurrently and must never raise
    anything but :class:`adhikar.errors.ProviderError` subclasses to callers.
    """

    @property
    def name(self) -> str:
        """Short identifier recorded in the audit log, e.g. ``"offline"``."""
        ...

    @property
    def model_id(self) -> str | None:
        """The concrete model, where one exists."""
        ...

    async def generate[TOut: BaseModel](
        self, request: ModelRequest, schema: type[TOut]
    ) -> ModelResponse[TOut]:
        """Answer ``request``, returning an instance of ``schema``.

        Raises:
            SchemaViolationError: the backend could not produce valid output.
            ProviderTimeoutError: the backend did not respond in time.
            ProviderError: any other backend failure.
        """
        ...
