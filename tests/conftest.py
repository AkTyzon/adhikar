"""Shared fixtures.

Every fixture here builds real objects against the real catalogues. There is no
mocked model anywhere in the suite: the offline engine has specified behaviour,
so tests assert on what the system actually does rather than on what a mock was
told to return. A test that pins a mock's response tests the mock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from adhikar.analysis.catalog import ClauseCatalog, get_catalog
from adhikar.config import Settings
from adhikar.domain import Document
from adhikar.ingest.extract import extract
from adhikar.ingest.segment import segment
from adhikar.llm.base import ModelProvider
from adhikar.llm.registry import build_provider
from adhikar.pipeline import Pipeline

FIXTURE_DIR = Path(__file__).parent / "fixtures"

#: A contract with genuinely one-sided terms and no hidden text. Used wherever a
#: test needs a realistic document that is not itself an attack.
SAMPLE_CONTRACT = """SERVICES AGREEMENT

1. Term. This Agreement commences on 14 March 2026 and continues for twelve (12)
months, renewing automatically unless either party gives sixty (60) days written
notice prior to the renewal date.

2. Fees. The Client shall pay each invoice within thirty (30) days of receipt.
Late payment shall accrue interest at 5% per month.

3. Indemnity. The Provider shall indemnify the Client against any and all claims
arising out of this agreement, without limit.

4. Liability. In no event shall the Client's aggregate liability exceed the fees
paid in the three (3) months preceding the claim.

5. Termination. The Client may terminate for convenience on seven (7) days
notice. The Provider may terminate only for material breach.

6. Intellectual Property. The Provider assigns to the Client all intellectual
property created under this Agreement.

7. Confidentiality. The Provider shall keep all Client information confidential
in perpetuity.
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings isolated from the developer's own environment.

    ``_env_file=None`` matters: without it a local .env would leak into the
    suite and tests would pass or fail depending on whose machine ran them.
    """
    return Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
    )


@pytest.fixture
def catalog(settings: Settings) -> ClauseCatalog:
    return get_catalog(settings.knowledge_path / "clauses.yaml")


@pytest.fixture
def provider(settings: Settings) -> ModelProvider:
    return build_provider(settings)


@pytest.fixture
def pipeline(settings: Settings, provider: ModelProvider) -> Pipeline:
    return Pipeline(settings, provider)


@pytest.fixture
def document(settings: Settings) -> Document:
    """The sample contract, segmented, as a domain object."""
    clauses = segment(SAMPLE_CONTRACT, "testdoc", settings.knowledge_path / "segmentation.yaml")
    return Document(
        id="testdoc",
        filename="sample.txt",
        media_type="text/plain",
        content_sha256="a" * 64,
        text=SAMPLE_CONTRACT,
        clauses=clauses,
        ingested_at=datetime.now(UTC),
    )


@pytest.fixture(scope="session")
def fixture_pdfs() -> dict[str, bytes]:
    """The generated PDF fixtures, built on demand if absent.

    Generating rather than committing keeps the repository small and makes each
    attack readable in scripts/make_fixtures.py instead of opaque inside a blob.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import make_fixtures  # type: ignore[import-not-found]

    if not (FIXTURE_DIR / "contract_benign.pdf").exists():
        make_fixtures.main(["make_fixtures.py", str(FIXTURE_DIR)])

    return {path.name: path.read_bytes() for path in FIXTURE_DIR.glob("*.pdf")}


@pytest.fixture
def benign_pdf(fixture_pdfs: dict[str, bytes]) -> bytes:
    return fixture_pdfs["contract_benign.pdf"]


@pytest.fixture
def poisoned_pdf(fixture_pdfs: dict[str, bytes]) -> bytes:
    return fixture_pdfs["contract_poisoned_white.pdf"]


@pytest.fixture
def extracted_text(benign_pdf: bytes, settings: Settings) -> str:
    return extract(benign_pdf, settings, "contract.pdf").text
