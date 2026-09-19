"""HTML rendering safety, the document store, and configuration validation."""

from __future__ import annotations

import asyncio

import pytest

from adhikar.config import Environment, Settings
from adhikar.domain import Span
from adhikar.errors import NotFoundError
from adhikar.store import MemoryAuditStore, MemoryDocumentStore
from adhikar.web.render import Highlight, excerpt_around, render_highlighted

XSS = '<script>alert("xss")</script>'


class TestHighlightRendering:
    def test_document_text_is_escaped(self) -> None:
        """Document text is attacker-controlled and is rendered on every page."""
        output = str(render_highlighted(f"Clause 1: {XSS} applies.", []))
        assert "<script>" not in output
        assert "&lt;script&gt;" in output

    def test_escaping_survives_highlighting(self) -> None:
        text = f"Clause 1: {XSS} applies here."
        start = text.index("applies")
        output = str(
            render_highlighted(
                text, [Highlight(start=start, end=start + 7, label="Risk", kind="high")]
            )
        )
        assert "<script>" not in output
        assert "<mark" in output

    def test_a_label_containing_markup_is_escaped(self) -> None:
        output = str(
            render_highlighted(
                "Some clause text here.",
                [Highlight(start=0, end=4, label=XSS, kind="high")],
            )
        )
        assert "<script>" not in output

    def test_the_reason_for_a_highlight_is_available_to_assistive_technology(
        self,
    ) -> None:
        """Colour alone does not convey the meaning of a mark."""
        output = str(
            render_highlighted(
                "The Provider shall indemnify.",
                [Highlight(start=13, end=28, label="Critical risk", kind="critical")],
            )
        )
        assert 'class="visually-hidden">Critical risk: ' in output

    def test_overlapping_highlights_do_not_nest(self) -> None:
        """Nested <mark> is announced inconsistently and adds no visual meaning."""
        output = str(
            render_highlighted(
                "The Provider shall indemnify the Client here.",
                [
                    Highlight(start=0, end=20, label="A", kind="high"),
                    Highlight(start=10, end=30, label="B", kind="low"),
                ],
            )
        )
        assert output.count("<mark") == 1

    def test_out_of_range_highlights_are_dropped(self) -> None:
        output = str(render_highlighted("Short text.", [Highlight(start=100, end=200, label="X")]))
        assert "<mark" not in output

    def test_empty_text_renders_empty(self) -> None:
        assert str(render_highlighted("", [Highlight(0, 5, "X")])) == ""

    def test_all_text_is_preserved(self) -> None:
        text = "One. Two. Three. Four."
        output = str(render_highlighted(text, [Highlight(5, 9, "X", "high")]))
        for word in ("One", "Two", "Three", "Four"):
            assert word in output


class TestExcerpt:
    def test_returns_context_around_a_span(self) -> None:
        text = "A. " * 40 + "The critical clause. " + "B. " * 40
        start = text.index("The critical clause.")
        span = Span.over("d1", text, start, start + 20)
        before, quote, after = excerpt_around(text, span, context=30)

        assert quote == "The critical clause."
        assert before.startswith("…")
        assert after.endswith("…")

    def test_does_not_ellipsize_at_the_document_edges(self) -> None:
        text = "The critical clause here."
        span = Span.over("d1", text, 0, 3)
        before, _, after = excerpt_around(text, span, context=100)
        assert not before.startswith("…")
        assert not after.endswith("…")


class TestDocumentStore:
    async def test_stores_and_retrieves(self, pipeline, benign_pdf: bytes) -> None:
        store = MemoryDocumentStore()
        outcome = pipeline.ingest(benign_pdf, "c.pdf")
        document_id = await store.put(outcome)
        assert (await store.get(document_id)).document.id == outcome.document.id

    async def test_an_unknown_id_raises(self) -> None:
        with pytest.raises(NotFoundError):
            await MemoryDocumentStore().get("nope")

    async def test_expired_documents_are_evicted(self, pipeline, benign_pdf: bytes) -> None:
        """Documents are held only as long as a session needs them."""
        store = MemoryDocumentStore(ttl_seconds=-1)
        document_id = await store.put(pipeline.ingest(benign_pdf, "c.pdf"))
        with pytest.raises(NotFoundError):
            await store.get(document_id)

    async def test_capacity_is_bounded(self, pipeline, benign_pdf: bytes) -> None:
        """Without a cap, an upload endpoint is a memory-exhaustion DoS."""
        store = MemoryDocumentStore(max_documents=2)
        for _ in range(5):
            await store.put(pipeline.ingest(benign_pdf, "c.pdf"))
        assert store.size <= 2

    async def test_deletion_is_immediate(self, pipeline, benign_pdf: bytes) -> None:
        store = MemoryDocumentStore()
        document_id = await store.put(pipeline.ingest(benign_pdf, "c.pdf"))
        assert await store.delete(document_id)
        assert not await store.delete(document_id)

    async def test_concurrent_writes_are_safe(self, pipeline, benign_pdf: bytes) -> None:
        store = MemoryDocumentStore(max_documents=20)
        outcomes = [pipeline.ingest(benign_pdf, f"c{i}.pdf") for i in range(8)]
        await asyncio.gather(*(store.put(o) for o in outcomes))
        assert len(await store.list_ids()) == 8


class TestAuditStore:
    async def test_records_come_back_newest_first(self) -> None:
        from adhikar.security.audit import AuditChain, start_record

        store = MemoryAuditStore()
        chain = AuditChain()
        for index in range(3):
            await store.append(
                chain.append(
                    start_record(
                        f"op{index}", document_sha256="a" * 64, engine="offline", model=None
                    )
                )
            )
        recent = await store.recent()
        assert [r.operation for r in recent] == ["op2", "op1", "op0"]

    async def test_head_tracks_the_latest_record(self) -> None:
        from adhikar.security.audit import GENESIS

        store = MemoryAuditStore()
        assert await store.head() == GENESIS


class TestConfiguration:
    def test_effort_is_validated(self) -> None:
        with pytest.raises(ValueError, match="effort must be one of"):
            Settings(_env_file=None, effort="turbo")

    def test_cors_origins_parse_from_a_comma_list(self) -> None:
        settings = Settings(_env_file=None, cors_origins="https://a.example,https://b.example")
        assert settings.cors_origins == ("https://a.example", "https://b.example")

    def test_production_refuses_debug(self) -> None:
        with pytest.raises(ValueError, match="debug must be disabled"):
            Settings(
                _env_file=None,
                environment=Environment.PRODUCTION,
                debug=True,
                database_url="postgresql+asyncpg://localhost/adhikar",
            )

    def test_production_refuses_to_disable_pii_redaction(self) -> None:
        """A knowingly unsafe posture must fail at startup, not at runtime."""
        with pytest.raises(ValueError, match="PII redaction"):
            Settings(
                _env_file=None,
                environment=Environment.PRODUCTION,
                redact_pii=False,
                database_url="postgresql+asyncpg://localhost/adhikar",
            )

    def test_production_refuses_sqlite(self) -> None:
        with pytest.raises(ValueError, match="SQLite"):
            Settings(_env_file=None, environment=Environment.PRODUCTION)

    def test_the_api_key_does_not_appear_in_a_repr(self) -> None:
        """SecretStr keeps the key out of logs, tracebacks and error messages."""
        settings = Settings(_env_file=None, anthropic_api_key="sk-ant-super-secret")
        assert "sk-ant-super-secret" not in repr(settings)
        assert "sk-ant-super-secret" not in str(settings.anthropic_api_key)

    def test_settings_are_immutable(self) -> None:
        settings = Settings(_env_file=None)
        with pytest.raises(ValueError, match="frozen"):
            settings.debug = True  # type: ignore[misc]
