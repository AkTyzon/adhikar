"""Segmentation, catalogue rules, risk detection, deadlines and comparison."""

from __future__ import annotations

from datetime import date

import pytest

from adhikar.analysis.catalog import ClauseCatalog, load_catalog
from adhikar.analysis.compare import ChangeKind, compare
from adhikar.analysis.deadlines import (
    add_business_days,
    add_duration,
    find_ambiguous_dates,
    find_dates,
    parse_duration,
)
from adhikar.analysis.glossary import get_glossary
from adhikar.analysis.obligations import extract, find_contradictions
from adhikar.analysis.risk import analyse, type_clauses
from adhikar.analysis.rules import Condition, compile_condition
from adhikar.config import Settings
from adhikar.domain import Document, Severity, TriggerKind
from adhikar.errors import CatalogError
from adhikar.ingest.segment import segment


class TestSegmentation:
    def test_clause_spans_tile_without_overlapping(self, document: Document) -> None:
        """The invariant every downstream citation depends on."""
        previous_end = 0
        for clause in document.clauses:
            assert clause.span.start >= previous_end
            assert clause.span.end <= len(document.text)
            previous_end = clause.span.end

    def test_every_clause_span_resolves(self, document: Document) -> None:
        for clause in document.clauses:
            assert clause.span.resolve(document.text) == clause.text

    def test_numbered_clauses_are_split(self, document: Document) -> None:
        headings = [c.heading for c in document.clauses if c.heading]
        assert "2" in headings
        assert "5" in headings

    def test_unnumbered_text_still_yields_clauses(self, settings: Settings) -> None:
        """A terms-of-service page with no numbering still needs citable units."""
        text = (
            "We may change this policy at any time.\n\n"
            "Your data is stored on our servers indefinitely and may be shared.\n\n"
            "You agree to these terms by continuing to use the service."
        )
        clauses = segment(text, "d1", settings.knowledge_path / "segmentation.yaml")
        assert len(clauses) >= 2

    def test_empty_document_yields_no_clauses(self, settings: Settings) -> None:
        assert segment("   ", "d1", settings.knowledge_path / "segmentation.yaml") == ()


class TestConditionLanguage:
    def test_any_matches_one_alternative(self) -> None:
        condition = compile_condition({"any": [r"\bfoo\b", r"\bbar\b"]}, context="t")
        assert condition.evaluate("this has foo in it") is not None
        assert condition.evaluate("this has neither") is None

    def test_all_requires_every_pattern(self) -> None:
        condition = compile_condition({"all": [r"\bfoo\b", r"\bbar\b"]}, context="t")
        assert condition.evaluate("foo and bar") is not None
        assert condition.evaluate("only foo") is None

    def test_none_vetoes(self) -> None:
        condition = compile_condition(
            {"all": [r"\bindemnif"], "none": [r"\bmutual(?:ly)?\b"]}, context="t"
        )
        assert condition.evaluate("shall indemnify the client") is not None
        assert condition.evaluate("shall mutually indemnify") is None
        assert condition.evaluate("mutual indemnity applies") is None

    def test_near_requires_proximity(self) -> None:
        condition = compile_condition(
            {"near": {"left": r"\bindemnif", "right": r"\bunlimited\b", "window": 40}},
            context="t",
        )
        assert condition.evaluate("indemnify for unlimited losses") is not None
        assert condition.evaluate("indemnify" + " x" * 80 + " unlimited") is None

    def test_near_evidence_spans_both_matches(self) -> None:
        """Proximity rules must cite the passage, not two disconnected fragments."""
        condition = compile_condition(
            {"near": {"left": r"\bindemnif", "right": r"\bunlimited\b", "window": 60}},
            context="t",
        )
        text = "The Provider shall indemnify against unlimited claims."
        match = condition.evaluate(text)

        assert match is not None
        start, end = match.merged_ranges()[0]
        assert "indemnify against unlimited" in text[start:end]

    def test_an_empty_condition_never_matches(self) -> None:
        """A mistyped rule must detect nothing, not everything."""
        assert Condition().evaluate("any text at all") is None

    def test_an_unknown_key_is_rejected(self) -> None:
        with pytest.raises(CatalogError, match="unknown condition key"):
            compile_condition({"sometimes": ["x"]}, context="t")

    def test_an_invalid_regex_is_rejected_at_load(self) -> None:
        with pytest.raises(CatalogError, match="invalid regex"):
            compile_condition({"any": ["[unclosed"]}, context="t")


class TestCatalog:
    def test_loads_without_error(self, catalog: ClauseCatalog) -> None:
        assert len(catalog) >= 10
        assert catalog.all_risks()

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("The Provider shall indemnify the Client against all claims.", "indemnity"),
            (
                "In no event shall aggregate liability exceed the fees paid.",
                "limitation_of_liability",
            ),
            ("This Agreement renews automatically for successive terms.", "auto_renewal"),
            ("Either party may terminate for material breach.", "termination"),
            (
                "The Company reserves the right to amend these terms at any time.",
                "unilateral_amendment",
            ),
            ("All personal data shall be processed under GDPR.", "data_protection"),
        ],
    )
    def test_classifies_clause_types(
        self, catalog: ClauseCatalog, text: str, expected: str
    ) -> None:
        assert catalog.classify(text)[0] == expected

    def test_unrelated_text_is_not_classified(self, catalog: ClauseCatalog) -> None:
        assert catalog.classify("The meeting is scheduled for Tuesday.")[0] is None

    def test_candidates_returns_every_matching_type(self, catalog: ClauseCatalog) -> None:
        """Real clauses are multi-typed; single-typing hides the second risk."""
        text = (
            "The Provider shall indemnify the Client, and such indemnity shall apply "
            "notwithstanding any limitation of liability in this Agreement."
        )
        ids = {clause_type.id for clause_type, _ in catalog.candidates(text)}
        assert {"indemnity", "limitation_of_liability"} <= ids

    def test_a_rule_with_an_empty_condition_is_rejected(self, tmp_path) -> None:
        """A rule that could never fire must fail at load.

        Silently skipping it is worse than refusing to start: a rule that never
        fires looks exactly like a clean contract.
        """
        broken = tmp_path / "broken.yaml"
        broken.write_text(
            "version: 1\n"
            "clause_types:\n"
            "  - id: example\n"
            "    title: Example\n"
            "    plain_language: An example clause.\n"
            "    detectors:\n"
            "      any: ['\\bexample\\b']\n"
            "    risks:\n"
            "      - id: never_fires\n"
            "        severity: high\n"
            "        title: This rule has no condition\n"
            "        when: {}\n"
            "        why_it_matters: It could never match anything.\n"
        )
        with pytest.raises(CatalogError, match="empty condition"):
            load_catalog(broken)

    def test_an_unknown_severity_is_rejected(self, tmp_path) -> None:
        broken = tmp_path / "severity.yaml"
        broken.write_text(
            "version: 1\n"
            "clause_types:\n"
            "  - id: example\n"
            "    title: Example\n"
            "    plain_language: An example clause.\n"
            "    detectors:\n"
            "      any: ['\\bexample\\b']\n"
            "    risks:\n"
            "      - id: bad_severity\n"
            "        severity: catastrophic\n"
            "        title: Unknown severity\n"
            "        when:\n"
            "          any: ['\\bfoo\\b']\n"
            "        why_it_matters: Severity is not in the enum.\n"
        )
        with pytest.raises(CatalogError, match="unknown severity"):
            load_catalog(broken)


class TestRiskAnalysis:
    def test_finds_the_unlimited_indemnity(self, document: Document, catalog) -> None:
        report = analyse(document, catalog)
        titles = [f.title for f in report.findings]
        assert any("unlimited" in title.lower() for title in titles)

    def test_critical_findings_sort_first(self, document: Document, catalog) -> None:
        ordered = analyse(document, catalog).by_severity()
        if ordered:
            assert ordered[0].severity is Severity.CRITICAL

    def test_every_finding_carries_resolvable_evidence(self, document: Document, catalog) -> None:
        """No finding may be uncitable; that is the system's core invariant."""
        for finding in analyse(document, catalog).findings:
            assert finding.spans
            for span in finding.spans:
                assert span.resolve(document.text)

    def test_evidence_stays_inside_its_clause(self, document: Document, catalog) -> None:
        """A greedy regex must not let a finding highlight the next clause."""
        report = analyse(document, catalog)
        for finding in report.findings:
            clause = next(
                (
                    c
                    for c in report.typed_clauses
                    if c.clause_type == finding.clause_type
                    and c.span.start <= finding.spans[0].start < c.span.end
                ),
                None,
            )
            if clause is not None:
                assert finding.spans[0].end <= clause.span.end

    def test_risk_score_saturates(self, document: Document, catalog) -> None:
        assert 0.0 <= analyse(document, catalog).score <= 1.0

    def test_a_clean_document_scores_zero(self, settings: Settings, catalog) -> None:
        from datetime import UTC, datetime

        text = "1. Definitions. In this Agreement, 'Business Day' means a weekday."
        clauses = segment(text, "d1", settings.knowledge_path / "segmentation.yaml")
        clean = Document(
            id="d1",
            filename="d.txt",
            media_type="text/plain",
            content_sha256="b" * 64,
            text=text,
            clauses=clauses,
            ingested_at=datetime.now(UTC),
        )
        assert analyse(clean, catalog).score == 0.0

    def test_missing_clause_types_are_reported(self, document: Document, catalog) -> None:
        assert analyse(document, catalog).missing_clause_types

    def test_baseline_comparison_is_attached(self, document: Document, catalog) -> None:
        findings = analyse(document, catalog).findings
        with_baseline = [f for f in findings if f.baseline_deviation]
        assert with_baseline
        assert with_baseline[0].baseline_deviation.expected

    def test_typing_returns_new_objects(self, document: Document, catalog) -> None:
        """Domain objects are frozen; stages return values rather than mutate."""
        typed = type_clauses(document.clauses, catalog)
        assert typed is not document.clauses
        assert any(c.clause_type for c in typed)


class TestDeadlines:
    @pytest.mark.parametrize(
        ("text", "quantity", "unit", "business"),
        [
            ("within thirty (30) days of receipt", 30, "day", False),
            ("no later than 5 business days", 5, "day", True),
            ("sixty (60) days written notice", 60, "day", False),
            ("twelve (12) months", 12, "month", False),
            ("one hundred and eighty days", 180, "day", False),
            ("two weeks", 2, "week", False),
            ("3 working days", 3, "day", True),
        ],
    )
    def test_parses_contract_durations(
        self, text: str, quantity: int, unit: str, business: bool
    ) -> None:
        duration = parse_duration(text)
        assert duration is not None
        assert (duration.quantity, duration.unit, duration.business_days) == (
            quantity,
            unit,
            business,
        )

    def test_parenthetical_digits_win_over_words(self) -> None:
        """Contracts write "thirty (30) days"; the digits are authoritative."""
        duration = parse_duration("thirty (45) days")
        assert duration is not None
        assert duration.quantity == 45

    def test_returns_none_when_there_is_no_duration(self) -> None:
        assert parse_duration("payable upon receipt of a valid invoice") is None

    def test_business_days_skip_weekends(self) -> None:
        # Friday 13 March 2026 + 3 business days = Wednesday 18 March.
        assert add_business_days(date(2026, 3, 13), 3) == date(2026, 3, 18)

    def test_business_days_skip_holidays(self) -> None:
        holidays = frozenset({date(2026, 3, 17)})
        assert add_business_days(date(2026, 3, 13), 3, holidays=holidays) == date(2026, 3, 19)

    def test_calendar_deadlines_roll_off_weekends(self) -> None:
        duration = parse_duration("30 days")
        assert duration is not None
        due = add_duration(date(2026, 3, 14), duration)
        assert due.weekday() < 5

    def test_month_arithmetic_uses_calendar_months(self) -> None:
        duration = parse_duration("12 months")
        assert duration is not None
        assert add_duration(date(2026, 3, 14), duration).year == 2027

    def test_finds_unambiguous_dates(self) -> None:
        found = find_dates("commences on 14 March 2026 and ends 2027-03-13")
        assert [d[0] for d in found] == [date(2026, 3, 14), date(2027, 3, 13)]

    def test_ambiguous_numeric_dates_are_not_guessed(self) -> None:
        """03/04/2026 is 3 April or 4 March depending on the reader."""
        assert find_dates("dated 03/04/2026") == ()
        assert find_ambiguous_dates("dated 03/04/2026")

    def test_a_day_above_twelve_disambiguates(self) -> None:
        assert not find_ambiguous_dates("dated 25/12/2026")


class TestObligations:
    def test_extracts_party_action_and_period(self, document: Document) -> None:
        result = extract(document)
        payment = next((o for o in result.obligations if "pay" in o.action.lower()), None)
        assert payment is not None
        assert payment.obligor == "Client"
        assert payment.offset_days == 30

    def test_finds_the_effective_date_anchor(self, document: Document) -> None:
        assert extract(document).anchors["effective date"] == date(2026, 3, 14)

    def test_unknown_anchors_are_reported_not_guessed(self, document: Document) -> None:
        """Deadlines relative to an unstated event must not be invented."""
        result = extract(document)
        assert "receipt" in result.unresolved_anchors

        receipt_based = [
            o
            for o in result.obligations
            if o.trigger_event == "receipt" and o.trigger_kind is TriggerKind.RELATIVE_TO_EVENT
        ]
        assert receipt_based
        assert all(o.computed_due is None for o in receipt_based)

    def test_obligations_carry_resolvable_evidence(self, document: Document) -> None:
        for obligation in extract(document).obligations:
            assert obligation.spans
            assert obligation.spans[0].resolve(document.text)

    def test_sentence_subjects_are_not_read_as_parties(self, document: Document) -> None:
        obligors = {o.obligor.lower() for o in extract(document).obligations}
        assert "this" not in obligors
        assert "agreement" not in obligors

    def test_conflicting_periods_are_detected(self, settings: Settings) -> None:
        from datetime import UTC, datetime

        text = (
            "1. Notice. The Client shall give sixty (60) days notice of termination.\n\n"
            "2. Notice. The Client shall give thirty (30) days notice of termination.\n"
        )
        clauses = segment(text, "d1", settings.knowledge_path / "segmentation.yaml")
        doc = Document(
            id="d1",
            filename="d.txt",
            media_type="text/plain",
            content_sha256="c" * 64,
            text=text,
            clauses=clauses,
            ingested_at=datetime.now(UTC),
        )
        contradictions = find_contradictions(extract(doc).obligations, (doc,))
        assert any(c.kind == "conflicting_period" for c in contradictions)

    def test_unrelated_obligations_are_not_flagged(self, document: Document) -> None:
        """Different topics differing is a contract, not a contradiction."""
        result = extract(document)
        for contradiction in find_contradictions(result.obligations, (document,)):
            assert contradiction.left.obligor == contradiction.right.obligor


class TestComparison:
    def _doc(self, text: str, doc_id: str, settings: Settings, catalog) -> Document:
        from datetime import UTC, datetime

        clauses = segment(text, doc_id, settings.knowledge_path / "segmentation.yaml")
        doc = Document(
            id=doc_id,
            filename=f"{doc_id}.txt",
            media_type="text/plain",
            content_sha256="d" * 64,
            text=text,
            clauses=clauses,
            ingested_at=datetime.now(UTC),
        )
        return doc.model_copy(update={"clauses": type_clauses(doc.clauses, catalog)})

    def test_identical_documents_show_no_changes(self, settings: Settings, catalog) -> None:
        text = "1. Fees. The Client shall pay within thirty (30) days of receipt.\n"
        left = self._doc(text, "a", settings, catalog)
        right = self._doc(text, "b", settings, catalog)
        assert compare(left, right).changes() == ()

    def test_a_reworded_clause_is_paired_not_replaced(self, settings: Settings, catalog) -> None:
        """Text diffing would call this two separate changes; alignment pairs it."""
        left = self._doc(
            "1. Fees. The Client shall pay within thirty (30) days of receipt.\n",
            "a",
            settings,
            catalog,
        )
        right = self._doc(
            "1. Fees. The Client shall pay within sixty (60) days of receipt.\n",
            "b",
            settings,
            catalog,
        )
        pairings = compare(left, right).pairings

        assert len(pairings) == 1
        assert pairings[0].kind is ChangeKind.MODIFIED
        assert "sixty" in pairings[0].added_terms

    def test_a_dropped_clause_is_reported_as_removed(self, settings: Settings, catalog) -> None:
        fees = "1. Fees. The Client shall pay each invoice within thirty (30) days of receipt.\n"
        indemnity = (
            "\n2. Indemnity. Each party shall indemnify the other against third-party "
            "claims to the extent caused by its own breach of this Agreement.\n"
        )
        left = self._doc(fees + indemnity, "a", settings, catalog)
        right = self._doc(fees, "b", settings, catalog)
        kinds = {p.kind for p in compare(left, right).pairings}
        assert ChangeKind.REMOVED in kinds

    def test_renumbering_does_not_create_spurious_changes(
        self, settings: Settings, catalog
    ) -> None:
        left = self._doc(
            "1. Fees. The Client shall pay within thirty (30) days of receipt.\n\n"
            "2. Term. This Agreement runs for twelve (12) months from commencement.\n",
            "a",
            settings,
            catalog,
        )
        right = self._doc(
            "4. Term. This Agreement runs for twelve (12) months from commencement.\n\n"
            "5. Fees. The Client shall pay within thirty (30) days of receipt.\n",
            "b",
            settings,
            catalog,
        )
        assert not any(p.kind is ChangeKind.ADDED for p in compare(left, right).pairings)


class TestGlossary:
    def test_expands_plain_language_into_drafting_language(self, settings: Settings) -> None:
        """The gap this closes is the product, not a search optimisation."""
        glossary = get_glossary(settings.knowledge_path / "glossary.yaml")
        expanded = glossary.expand("What are the payment terms?")
        assert "fees" in expanded
        assert "invoice" in expanded

    def test_lookup_is_case_insensitive(self, settings: Settings) -> None:
        glossary = get_glossary(settings.knowledge_path / "glossary.yaml")
        assert glossary.lookup("INDEMNIFY") is not None

    def test_reports_terms_present_in_a_document(
        self, settings: Settings, document: Document
    ) -> None:
        glossary = get_glossary(settings.knowledge_path / "glossary.yaml")
        found = {term.term for term in glossary.present_in(document.text)}
        assert "indemnify" in found
