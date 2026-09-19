"""Anthropic Claude backend.

Three API features do real architectural work here rather than being decoration:

**Structured outputs** (``messages.parse`` with a Pydantic model) mean the
provider returns a validated object or raises.  There is no response parsing
anywhere in this codebase, and therefore no class of bug where a malformed
response is half-understood.

**Prompt caching** on the document block.  A contract is large and constant
across a session; the question is small and varies.  Marking the document as the
cache breakpoint means the second and subsequent questions about the same
document re-read it at a fraction of the cost.  The effect is measured, not
assumed -- ``cache_read_input_tokens`` is recorded in every audit record, and the
efficiency view shows it.

**Mid-conversation system messages.**  The operator's reassertion after untrusted
content is sent with the ``system`` role, which carries authority a user-role
message does not. This is the API-level half of the boundary that
:mod:`adhikar.llm.transcript` builds.

The SDK is called through ``client.beta.messages`` only where a beta feature is
actually required; everything else uses the stable surface.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ValidationError

from adhikar.config import Settings
from adhikar.errors import ProviderError, ProviderTimeoutError, SchemaViolationError
from adhikar.llm import transcript
from adhikar.llm.base import ModelRequest, ModelResponse, Task, Usage
from adhikar.llm.prompts import load

#: Per-task effort. Verification is a narrow judgement on a short passage and
#: does not repay deep reasoning; extraction over a whole contract does.
_TASK_EFFORT: Final[dict[Task, str]] = {
    Task.VERIFY: "low",
    Task.CLAUSE_TYPING: "low",
    Task.SIMPLIFY: "medium",
    Task.ANSWER: "high",
    Task.OBLIGATIONS: "high",
    Task.LAWYER_QUESTIONS: "medium",
}

#: Prompt template per task.
_TASK_PROMPT: Final[dict[Task, str]] = {
    Task.ANSWER: "answer",
    Task.VERIFY: "verify",
    Task.OBLIGATIONS: "obligations",
    Task.SIMPLIFY: "simplify",
    Task.LAWYER_QUESTIONS: "lawyer_questions",
    Task.CLAUSE_TYPING: "answer",
}


class AnthropicProvider:
    """Claude-backed implementation of :class:`~adhikar.llm.base.ModelProvider`."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or self._build_client(settings)
        self._model = settings.model

    @staticmethod
    def _build_client(settings: Settings) -> Any:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError(
                "the 'anthropic' package is required for the Anthropic engine; "
                "install with: pip install 'adhikar[anthropic]'"
            ) from exc

        key = settings.anthropic_api_key
        return anthropic.AsyncAnthropic(
            api_key=key.get_secret_value() if key else None,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        )

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model_id(self) -> str | None:
        return self._model

    async def generate[TOut: BaseModel](
        self, request: ModelRequest, schema: type[TOut]
    ) -> ModelResponse[TOut]:
        """Issue one structured call, with the document isolated as data."""
        model = self._settings.verifier_model if request.task is Task.VERIFY else self._model
        payload = self._build_payload(request, schema, model)

        try:
            response = await self._client.messages.parse(**payload)
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"model call for {request.task} timed out") from exc
        except Exception as exc:
            raise self._translate(exc, request) from exc

        return self._interpret(response, schema, model)

    # ------------------------------------------------------------------ build
    def _build_payload(
        self, request: ModelRequest, schema: type[BaseModel], model: str
    ) -> dict[str, Any]:
        system_prompt = load("system").text
        template = load(_TASK_PROMPT[request.task])
        instruction = self._render(template, request)

        built = transcript.build(
            system_prompt=system_prompt,
            instruction=instruction,
            documents=request.documents,
            # Claude supports a mid-conversation system role, which is the
            # strongest available operator channel after untrusted content.
            supports_system_turn=True,
            cacheable=request.cacheable and self._settings.enable_prompt_caching,
        )

        messages = [dict(message) for message in built.messages]
        if built.cache_breakpoint is not None:
            messages[built.cache_breakpoint] = _with_cache_control(messages[built.cache_breakpoint])

        return {
            "model": model,
            "max_tokens": request.max_output_tokens or self._settings.max_output_tokens,
            "system": [
                {
                    "type": "text",
                    "text": built.system,
                    # The system prompt is byte-identical across every call, so
                    # it is the outermost stable prefix worth caching.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": messages,
            "output_format": schema,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": _TASK_EFFORT.get(request.task, self._settings.effort)},
        }

    def _render(self, template: Any, request: ModelRequest) -> str:
        substitutions = {
            key.upper(): str(value)
            for key, value in request.params.items()
            if isinstance(value, (str, int, float))
        }
        substitutions.setdefault("QUESTION", request.instruction)
        substitutions.setdefault("MODE_GUIDANCE", "")
        try:
            body = template.render(**substitutions)
        except Exception:
            # A template whose placeholders do not match the caller is a
            # configuration fault, not a model fault -- fall back to the raw
            # instruction rather than sending a half-rendered prompt.
            body = request.instruction
        return body if request.task is not Task.VERIFY else f"{body}\n\n{request.instruction}"

    # ------------------------------------------------------------------ read
    def _interpret[TOut: BaseModel](
        self, response: Any, schema: type[TOut], model: str
    ) -> ModelResponse[TOut]:
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise ProviderError(
                "the model declined this request"
                + (f" ({details.category})" if details is not None else "")
            )

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise SchemaViolationError(
                f"model returned no structured output for schema {schema.__name__}"
            )
        if not isinstance(parsed, schema):
            try:
                parsed = schema.model_validate(parsed)
            except ValidationError as exc:
                raise SchemaViolationError(
                    f"model output did not satisfy {schema.__name__}: {exc.error_count()} errors"
                ) from exc

        usage = getattr(response, "usage", None)
        return ModelResponse(
            output=parsed,
            usage=Usage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            ),
            model=model,
        )

    # ------------------------------------------------------------------ errors
    @staticmethod
    def _translate(  # noqa: PLR0911 - a mapping table reads best as flat returns
        exc: Exception, request: ModelRequest
    ) -> ProviderError:
        """Map SDK exceptions onto the local hierarchy.

        Handled most-specific-first so a 404 is not retried as though it were a
        429, and so nothing from the SDK reaches a caller unmapped.
        """
        try:
            import anthropic
        except ImportError:  # pragma: no cover
            return ProviderError(f"model call for {request.task} failed: {exc}")

        if isinstance(exc, anthropic.APITimeoutError):
            return ProviderTimeoutError(f"model call for {request.task} timed out")
        if isinstance(exc, anthropic.AuthenticationError):
            return ProviderError("the configured Anthropic API key was rejected")
        if isinstance(exc, anthropic.RateLimitError):
            return ProviderError("the model backend is rate limited; retry shortly")
        if isinstance(exc, anthropic.BadRequestError):
            return SchemaViolationError(f"the model rejected the request: {exc}")
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderError(f"model backend returned HTTP {exc.status_code}")
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError("could not reach the model backend")
        return ProviderError(f"model call for {request.task} failed")


def _with_cache_control(message: dict[str, Any]) -> dict[str, Any]:
    """Convert a text message into a content block carrying a cache breakpoint."""
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    blocks = [dict(block) for block in content]
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return {**message, "content": blocks}
