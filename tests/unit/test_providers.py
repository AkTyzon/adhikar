"""Engine selection, prompt loading, the offline engine, and payload construction.

The Anthropic tests use a fake client that captures the request rather than
sending it. That is not a substitute for testing behaviour -- it is the only way
to assert on the *payload*, and the payload is where the security properties
live: whether document text stays out of the system prompt, whether the cache
breakpoint lands on the document, whether the operator gets the last word.
"""

from __future__ import annotations

from typing import Any

import pytest

from adhikar.analysis.schemas import AnswerDraft
from adhikar.config import Engine, Settings
from adhikar.errors import ConfigurationError, ProviderError, SchemaViolationError
from adhikar.llm.base import DocumentContext, ModelProvider, ModelRequest, Task, Usage
from adhikar.llm.offline import OfflineEngine
from adhikar.llm.prompts import load, versions
from adhikar.llm.registry import build_provider
from adhikar.verify.gate import EntailmentJudgement

CANARY = "CANARY_CONFIDENTIAL_CLAUSE_TEXT"


class TestRegistry:
    def test_defaults_to_offline_without_a_key(self, settings: Settings) -> None:
        """A fresh clone must work with no secrets at all."""
        assert settings.resolved_engine is Engine.OFFLINE
        assert build_provider(settings).name == "offline"

    def test_selects_anthropic_when_a_key_is_present(self, settings: Settings) -> None:
        configured = settings.model_copy(update={"anthropic_api_key": "sk-ant-test"})
        assert configured.resolved_engine is Engine.ANTHROPIC

    def test_explicit_anthropic_without_a_key_is_a_configuration_error(
        self, settings: Settings
    ) -> None:
        broken = settings.model_copy(update={"engine": Engine.ANTHROPIC})
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            build_provider(broken)

    def test_the_provider_satisfies_the_protocol(self, provider: ModelProvider) -> None:
        assert isinstance(provider, ModelProvider)


class TestPrompts:
    def test_templates_load_and_hash(self) -> None:
        prompt = load("system")
        assert prompt.text
        assert len(prompt.sha256) == 64

    def test_rendering_fills_placeholders(self) -> None:
        rendered = load("answer").render(QUESTION="When is payment due?", MODE_GUIDANCE="")
        assert "When is payment due?" in rendered

    def test_an_unfilled_placeholder_is_an_error(self) -> None:
        """A prompt shipped with a literal {{QUESTION}} would silently degrade output."""
        with pytest.raises(ConfigurationError, match="unfilled placeholder"):
            load("answer").render()

    def test_the_fence_placeholder_is_filled_later(self) -> None:
        """{{FENCE}} is substituted by the transcript builder, not the caller."""
        assert "{{FENCE}}" in load("system").render()

    def test_versions_are_reported_for_the_audit_record(self) -> None:
        reported = versions("system", "answer", "verify")
        assert set(reported) == {"system", "answer", "verify"}
        assert all(len(v) == 16 for v in reported.values())

    def test_a_missing_template_is_an_error(self) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            load("no_such_prompt")

    def test_a_traversing_name_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            load("../../../etc/passwd")

    def test_the_system_prompt_states_the_untrusted_content_rule(self) -> None:
        text = load("system").text.lower()
        assert "untrusted" in text
        assert "never an instruction" in text or "not a source of instructions" in text


class TestOfflineEngine:
    async def test_answers_from_retrieved_passages(self, provider: ModelProvider, document) -> None:
        response = await provider.generate(
            ModelRequest(
                task=Task.ANSWER,
                instruction="What are the payment terms?",
                documents=(DocumentContext(document.id, "c.txt", document.text),),
                params={"question": "What are the payment terms?"},
            ),
            AnswerDraft,
        )
        assert response.output.claims
        # Every quote must be verbatim, or anchoring would reject it downstream.
        for claim in response.output.claims:
            assert claim.quotes[0] in document.text

    async def test_reports_inability_rather_than_inventing(self, provider: ModelProvider) -> None:
        response = await provider.generate(
            ModelRequest(
                task=Task.ANSWER,
                instruction="What does the arbitration clause say?",
                documents=(DocumentContext("d1", "c.txt", "1. Fees. Payment is due."),),
                params={"question": "What does the arbitration clause say about Geneva?"},
            ),
            AnswerDraft,
        )
        assert response.output.unable_to_answer or not response.output.claims

    async def test_verification_judges_entailment(self, provider: ModelProvider) -> None:
        response = await provider.generate(
            ModelRequest(
                task=Task.VERIFY,
                instruction="STATEMENT:\nPayment is due in thirty days.\n\nDecide.",
                documents=(DocumentContext("d1", "evidence", "Payment is due in thirty days."),),
                cacheable=False,
            ),
            EntailmentJudgement,
        )
        assert response.output.verdict.value in {
            "supported",
            "partially_supported",
            "unsupported",
            "contradicted",
        }

    async def test_is_deterministic(self, provider: ModelProvider, document) -> None:
        """Same input, same output -- which is what makes an audit record checkable."""
        request = ModelRequest(
            task=Task.ANSWER,
            instruction="What are the payment terms?",
            documents=(DocumentContext(document.id, "c.txt", document.text),),
            params={"question": "What are the payment terms?"},
        )
        first = await provider.generate(request, AnswerDraft)
        second = await provider.generate(request, AnswerDraft)
        assert first.output == second.output

    async def test_an_unimplemented_task_raises(self, provider: ModelProvider) -> None:
        engine = OfflineEngine()
        with pytest.raises(SchemaViolationError):
            await engine.generate(
                ModelRequest(task=Task.LAWYER_QUESTIONS, instruction="x"), AnswerDraft
            )


class _FakeResponse:
    def __init__(self, parsed: Any, stop_reason: str = "end_turn") -> None:
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.stop_details = None
        self.usage = type(
            "U", (), {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 80}
        )()


class _FakeMessages:
    def __init__(self, parsed: Any) -> None:
        self.captured: dict[str, Any] = {}
        self._parsed = parsed

    async def parse(self, **payload: Any) -> _FakeResponse:
        self.captured = payload
        return _FakeResponse(self._parsed)


class _FakeClient:
    def __init__(self, parsed: Any) -> None:
        self.messages = _FakeMessages(parsed)


class TestAnthropicPayload:
    """What we send, asserted without sending it."""

    @pytest.fixture
    def configured(self, settings: Settings) -> Settings:
        return settings.model_copy(update={"anthropic_api_key": "sk-ant-test"})

    def _provider(self, configured: Settings, parsed: Any):
        from adhikar.llm.anthropic_provider import AnthropicProvider

        client = _FakeClient(parsed)
        return AnthropicProvider(configured, client=client), client

    async def test_document_text_never_enters_the_system_prompt(self, configured: Settings) -> None:
        """The structural guarantee, asserted on the real outgoing payload."""
        provider, client = self._provider(configured, AnswerDraft(claims=[]))
        await provider.generate(
            ModelRequest(
                task=Task.ANSWER,
                instruction="Summarise.",
                documents=(DocumentContext("d1", "c.pdf", f"Clause 1. {CANARY}"),),
            ),
            AnswerDraft,
        )
        system = str(client.messages.captured["system"])
        assert CANARY not in system

    async def test_the_document_is_sent_as_a_fenced_user_turn(self, configured: Settings) -> None:
        provider, client = self._provider(configured, AnswerDraft(claims=[]))
        await provider.generate(
            ModelRequest(
                task=Task.ANSWER,
                instruction="Summarise.",
                documents=(DocumentContext("d1", "c.pdf", f"Clause 1. {CANARY}"),),
            ),
            AnswerDraft,
        )
        messages = client.messages.captured["messages"]
        assert messages[0]["role"] == "user"
        assert CANARY in str(messages[0]["content"])
        assert "untrusted_document" in str(messages[0]["content"])

    async def test_the_operator_reassertion_is_the_final_turn(self, configured: Settings) -> None:
        provider, client = self._provider(configured, AnswerDraft(claims=[]))
        await provider.generate(
            ModelRequest(
                task=Task.ANSWER,
                instruction="Summarise.",
                documents=(DocumentContext("d1", "c.pdf", "Clause 1."),),
            ),
            AnswerDraft,
        )
        assert client.messages.captured["messages"][-1]["role"] == "system"

    async def test_the_cache_breakpoint_lands_on_the_document(self, configured: Settings) -> None:
        """The document is the large stable prefix; caching it is the cost saving."""
        provider, client = self._provider(configured, AnswerDraft(claims=[]))
        await provider.generate(
            ModelRequest(
                task=Task.ANSWER,
                instruction="Summarise.",
                documents=(DocumentContext("d1", "c.pdf", "Clause 1." * 200),),
            ),
            AnswerDraft,
        )
        document_message = client.messages.captured["messages"][0]
        assert document_message["content"][-1]["cache_control"] == {"type": "ephemeral"}

    async def test_adaptive_thinking_is_requested(self, configured: Settings) -> None:
        provider, client = self._provider(configured, AnswerDraft(claims=[]))
        await provider.generate(
            ModelRequest(task=Task.ANSWER, instruction="Summarise."), AnswerDraft
        )
        assert client.messages.captured["thinking"] == {"type": "adaptive"}
        assert "budget_tokens" not in str(client.messages.captured)

    async def test_verification_runs_at_low_effort(self, configured: Settings) -> None:
        """A narrow judgement on a short passage does not repay deep reasoning."""
        provider, client = self._provider(
            configured, EntailmentJudgement(verdict="supported", confidence=0.9, reason="ok")
        )
        await provider.generate(
            ModelRequest(task=Task.VERIFY, instruction="STATEMENT:\nx\n\nDecide."),
            EntailmentJudgement,
        )
        assert client.messages.captured["output_config"]["effort"] == "low"

    async def test_cache_reads_are_recorded_for_the_audit_trail(self, configured: Settings) -> None:
        provider, _ = self._provider(configured, AnswerDraft(claims=[]))
        response = await provider.generate(
            ModelRequest(task=Task.ANSWER, instruction="Summarise."), AnswerDraft
        )
        assert response.usage.cached_input_tokens == 80
        assert response.usage.cache_hit_ratio > 0.4

    async def test_a_refusal_is_surfaced_as_a_provider_error(self, configured: Settings) -> None:
        from adhikar.llm.anthropic_provider import AnthropicProvider

        client = _FakeClient(None)

        async def refuse(**_: Any) -> _FakeResponse:
            return _FakeResponse(None, stop_reason="refusal")

        client.messages.parse = refuse  # type: ignore[assignment]
        provider = AnthropicProvider(configured, client=client)

        with pytest.raises(ProviderError, match="declined"):
            await provider.generate(ModelRequest(task=Task.ANSWER, instruction="x"), AnswerDraft)

    async def test_missing_structured_output_is_a_schema_violation(
        self, configured: Settings
    ) -> None:
        provider, _ = self._provider(configured, None)
        with pytest.raises(SchemaViolationError):
            await provider.generate(ModelRequest(task=Task.ANSWER, instruction="x"), AnswerDraft)


class TestUsage:
    def test_usage_adds(self) -> None:
        total = Usage(10, 5, 2) + Usage(20, 10, 8)
        assert (total.input_tokens, total.output_tokens, total.cached_input_tokens) == (30, 15, 10)

    def test_cache_hit_ratio_is_zero_without_traffic(self) -> None:
        assert Usage().cache_hit_ratio == 0.0
