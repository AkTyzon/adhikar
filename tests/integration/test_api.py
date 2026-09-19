"""HTTP surface: routes, security headers, limits and error handling."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from adhikar.api.app import create_app
from adhikar.config import Settings


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def uploaded(client: TestClient, benign_pdf: bytes) -> str:
    response = client.post(
        "/api/documents", files={"file": ("msa.pdf", benign_pdf, "application/pdf")}
    )
    assert response.status_code == 201
    return response.json()["document_id"]


class TestHealth:
    def test_reports_configuration_without_secrets(self, client: TestClient) -> None:
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["engine"] == "offline"
        assert "api_key" not in str(body).lower()


class TestUpload:
    def test_accepts_a_pdf(self, client: TestClient, benign_pdf: bytes) -> None:
        response = client.post(
            "/api/documents", files={"file": ("msa.pdf", benign_pdf, "application/pdf")}
        )
        assert response.status_code == 201
        body = response.json()
        assert body["clause_count"] > 0
        assert body["injection_score"] == 0.0

    def test_quarantines_a_poisoned_document(self, client: TestClient, poisoned_pdf: bytes) -> None:
        """The document is refused, not analysed with a warning attached."""
        response = client.post(
            "/api/documents", files={"file": ("bad.pdf", poisoned_pdf, "application/pdf")}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "document_quarantined"

    def test_rejects_an_unsupported_format(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents",
            files={"file": ("payload.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/pdf")},
        )
        assert response.status_code == 415

    def test_the_declared_content_type_is_not_trusted(self, client: TestClient) -> None:
        """Content-Type is attacker-controlled; the bytes decide."""
        response = client.post(
            "/api/documents",
            files={"file": ("fake.pdf", b"\x00\x01\x02binary garbage", "application/pdf")},
        )
        assert response.status_code == 415

    def test_rejects_an_empty_file(self, client: TestClient) -> None:
        response = client.post("/api/documents", files={"file": ("empty.txt", b"", "text/plain")})
        assert response.status_code == 400

    def test_enforces_the_size_limit(self, settings: Settings) -> None:
        small = settings.model_copy(update={"max_upload_bytes": 1024})
        with TestClient(create_app(small)) as client:
            response = client.post(
                "/api/documents",
                files={"file": ("big.txt", b"A clause. " * 500, "text/plain")},
            )
            assert response.status_code in (400, 413)

    def test_a_path_traversal_filename_is_neutralised(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents",
            files={
                "file": (
                    "../../../etc/passwd",
                    b"1. Term. This Agreement runs for twelve (12) months from signature.\n",
                    "text/plain",
                )
            },
        )
        assert response.status_code == 201
        assert "/" not in response.json()["filename"]


class TestAnalysis:
    def test_returns_findings_with_evidence(self, client: TestClient, uploaded: str) -> None:
        body = client.get(f"/api/documents/{uploaded}/analysis").json()

        assert body["findings"]
        for finding in body["findings"]:
            assert finding["evidence"], "every finding must be citable"
            assert finding["evidence"][0]["text"]

    def test_reports_unresolved_deadline_anchors(self, client: TestClient, uploaded: str) -> None:
        body = client.get(f"/api/documents/{uploaded}/analysis").json()
        assert "unresolved_anchors" in body

    def test_an_unknown_document_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/documents/nope/analysis").status_code == 404


class TestQuestions:
    def test_answers_carry_evidence(self, client: TestClient, uploaded: str) -> None:
        body = client.post(
            f"/api/documents/{uploaded}/questions",
            data={"question": "What are the payment terms?"},
        ).json()

        assert body["answer"]
        for claim in body["answer"]:
            assert claim["evidence"]
            assert claim["verdict"] == "supported"

    def test_an_advice_question_is_routed_not_answered_as_advice(
        self, client: TestClient, uploaded: str
    ) -> None:
        body = client.post(
            f"/api/documents/{uploaded}/questions", data={"question": "Should I sign this?"}
        ).json()

        assert body["intent"] == "advice"
        assert body["mode"] == "inform_and_prepare"

    def test_a_prediction_question_is_refused_before_any_model_call(
        self, client: TestClient, uploaded: str
    ) -> None:
        body = client.post(
            f"/api/documents/{uploaded}/questions",
            data={"question": "Will I win if I take them to court?"},
        ).json()

        assert body["mode"] == "refer_out"
        assert body["abstained"]
        assert body["answer"] == []
        assert "professional" in body["notice"].lower()

    def test_a_question_about_absent_content_abstains(
        self, client: TestClient, uploaded: str
    ) -> None:
        """Abstention rather than confabulation is the whole point."""
        body = client.post(
            f"/api/documents/{uploaded}/questions",
            data={"question": "What does the arbitration clause say about Singapore?"},
        ).json()
        assert body["answer"] == []

    def test_rejects_an_over_long_question(self, client: TestClient, uploaded: str) -> None:
        response = client.post(
            f"/api/documents/{uploaded}/questions", data={"question": "x" * 5000}
        )
        assert response.status_code == 422


class TestDocumentLifecycle:
    def test_a_document_can_be_deleted_immediately(self, client: TestClient, uploaded: str) -> None:
        assert client.delete(f"/api/documents/{uploaded}").status_code == 204
        assert client.get(f"/api/documents/{uploaded}/analysis").status_code == 404


class TestAuditEndpoint:
    def test_chain_verifies_after_real_operations(self, client: TestClient, uploaded: str) -> None:
        client.get(f"/api/documents/{uploaded}/analysis")
        client.post(
            f"/api/documents/{uploaded}/questions", data={"question": "When is payment due?"}
        )
        body = client.get("/api/audit").json()

        assert body["chain_valid"]
        assert body["records_checked"] >= 3

    def test_audit_records_expose_no_document_text(self, client: TestClient, uploaded: str) -> None:
        client.get(f"/api/documents/{uploaded}/analysis")
        assert "indemnify" not in str(client.get("/api/audit").json()).lower()


class TestSecurityHeaders:
    def test_every_response_carries_the_policy(self, client: TestClient) -> None:
        headers = client.get("/").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]

    def test_the_csp_permits_no_inline_script(self, client: TestClient) -> None:
        """An escaping bug must not be able to become script execution."""
        policy = client.get("/").headers["Content-Security-Policy"]
        assert "unsafe-inline" not in policy
        assert "unsafe-eval" not in policy

    def test_document_responses_are_not_cached(self, client: TestClient, uploaded: str) -> None:
        response = client.get(f"/documents/{uploaded}")
        assert "no-store" in response.headers["Cache-Control"]

    def test_every_response_carries_a_request_id(self, client: TestClient) -> None:
        assert client.get("/api/health").headers["X-Request-ID"]


class TestRateLimiting:
    def test_uploads_are_limited(self, settings: Settings, benign_pdf: bytes) -> None:
        tight = settings.model_copy(update={"upload_rate_limit_requests": 2})
        with TestClient(create_app(tight)) as client:
            statuses = [
                client.post(
                    "/api/documents",
                    files={"file": (f"c{i}.pdf", benign_pdf, "application/pdf")},
                ).status_code
                for i in range(4)
            ]
            assert 429 in statuses

    def test_a_limited_response_says_when_to_retry(
        self, settings: Settings, benign_pdf: bytes
    ) -> None:
        tight = settings.model_copy(update={"upload_rate_limit_requests": 1})
        with TestClient(create_app(tight)) as client:
            for _ in range(3):
                response = client.post(
                    "/api/documents", files={"file": ("c.pdf", benign_pdf, "application/pdf")}
                )
                if response.status_code == 429:
                    assert int(response.headers["Retry-After"]) > 0
                    return
        pytest.fail("rate limit was never reached")


class TestErrorHandling:
    def test_errors_are_uniform_and_carry_a_request_id(self, client: TestClient) -> None:
        body = client.get("/api/documents/missing/analysis").json()
        assert set(body["error"]) >= {"code", "message", "request_id"}

    def test_errors_do_not_leak_internals(self, client: TestClient) -> None:
        message = client.get("/api/documents/missing/analysis").json()["error"]["message"]
        assert "Traceback" not in message
        assert "/Users/" not in message
        assert "sqlite" not in message.lower()


class TestWebPages:
    def test_home_renders(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "Skip to main content" in response.text

    def test_report_renders(self, client: TestClient, uploaded: str) -> None:
        response = client.get(f"/documents/{uploaded}")
        assert response.status_code == 200
        assert "What carries risk" in response.text

    def test_the_report_warns_about_a_quarantined_upload(
        self, client: TestClient, poisoned_pdf: bytes
    ) -> None:
        response = client.post(
            "/documents",
            files={"file": ("bad.pdf", poisoned_pdf, "application/pdf")},
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert "There is a problem" in response.text

    def test_asking_without_javascript_re_renders_the_report(
        self, client: TestClient, uploaded: str
    ) -> None:
        """Progressive enhancement: the form POST must work on its own."""
        response = client.post(
            f"/documents/{uploaded}/ask",
            data={"question": "What are the payment terms?"},
        )
        assert response.status_code == 200
        assert "Answer" in response.text

    def test_audit_page_renders(self, client: TestClient) -> None:
        assert client.get("/audit").status_code == 200
