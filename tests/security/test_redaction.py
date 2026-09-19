"""PII detection, pseudonymisation and offset integrity."""

from __future__ import annotations

import pytest

from adhikar.config import Settings
from adhikar.security.checksums import gstin, luhn, mod97, pan, verhoeff
from adhikar.security.redaction import Redactor, Sensitivity
from adhikar.security.textmap import OffsetMap, Replacement

#: Verhoeff-valid Aadhaar numbers, derived by construction rather than invented:
#: exactly one check digit satisfies the algorithm for any 11-digit prefix.
VALID_AADHAAR = ["234567890124", "998877665548", "456123789011"]


@pytest.fixture
def redactor(settings: Settings) -> Redactor:
    return Redactor.from_catalogue(settings.knowledge_path / "pii_patterns.yaml")


class TestChecksums:
    def test_luhn_accepts_a_valid_card(self) -> None:
        assert luhn("4539 1488 0343 6467")

    def test_luhn_rejects_a_bad_check_digit(self) -> None:
        assert not luhn("4539 1488 0343 6468")

    @pytest.mark.parametrize("number", VALID_AADHAAR)
    def test_verhoeff_accepts_valid_aadhaar(self, number: str) -> None:
        assert verhoeff(number)

    @pytest.mark.parametrize("number", ["234567890123", "111111111111", "012345678901"])
    def test_verhoeff_rejects_invalid_aadhaar(self, number: str) -> None:
        assert not verhoeff(number)

    def test_exactly_one_check_digit_is_valid_for_any_prefix(self) -> None:
        """The defining property of a check digit, asserted rather than assumed."""
        for prefix in ("23456789012", "99887766554"):
            valid = [d for d in "0123456789" if verhoeff(prefix + d)]
            assert len(valid) == 1

    def test_pan_requires_a_valid_holder_type_character(self) -> None:
        assert pan("ABCPK1234F")
        assert not pan("ABCXK1234F")

    def test_iban_mod97(self) -> None:
        assert mod97("GB82 WEST 1234 5698 7654 32")
        assert not mod97("GB82 WEST 1234 5698 7654 33")

    def test_gstin_check_digit(self) -> None:
        assert not gstin("27AAPFU0939F1Z0")


class TestDetection:
    def test_finds_identifiers_across_types(self, redactor: Redactor) -> None:
        text = (
            "Contact rajesh@example.com or +91 98765 43210. PAN ABCPK1234F, Aadhaar 2345 6789 0124."
        )
        found = {match.pattern_id for match in redactor.scan(text)}
        assert {"email", "phone_india", "pan", "aadhaar"} <= found

    def test_context_gating_prevents_false_positives(self, redactor: Redactor) -> None:
        """The single most important precision control.

        A bare run of digits is an invoice number far more often than a bank
        account. Redacting it would destroy the contract text this tool exists to
        analyse, so the pattern only fires near a banking keyword.
        """
        invoice = "Invoice 4500123456 is due in 30 days under clause 7.2."
        assert not [m for m in redactor.scan(invoice) if m.pattern_id == "bank_account"]

        banking = "Remit to account 4500123456 at IFSC HDFC0001234."
        assert [m for m in redactor.scan(banking) if m.pattern_id == "bank_account"]

    def test_clause_numbers_and_amounts_survive(self, redactor: Redactor) -> None:
        text = "Under clause 7.2, the fee is 250000 rupees payable over 12 months."
        assert redactor.redact(text).text == text

    def test_checksum_failures_are_not_treated_as_pii(self, redactor: Redactor) -> None:
        """A 12-digit number that fails Verhoeff is not an Aadhaar number."""
        text = "Reference number 234567890123 applies to this order."
        assert not [m for m in redactor.scan(text) if m.pattern_id == "aadhaar"]

    def test_overlapping_matches_resolve_to_the_more_sensitive(self, redactor: Redactor) -> None:
        """A valid Aadhaar also matches the generic account pattern."""
        matches = redactor.scan("Aadhaar 234567890124 on file for the account holder.")
        aadhaar = [m for m in matches if m.pattern_id == "aadhaar"]
        assert aadhaar
        assert aadhaar[0].sensitivity is Sensitivity.HIGH
        assert not any(
            m.pattern_id == "bank_account" and m.start == aadhaar[0].start for m in matches
        )


class TestPseudonymisation:
    def test_round_trip_is_lossless(self, redactor: Redactor) -> None:
        text = "Mr. Rajesh Kumar at rajesh@example.com, PAN ABCPK1234F."
        result = redactor.redact(text)

        assert "rajesh@example.com" not in result.text
        assert result.restore(result.text) == text

    def test_the_same_value_keeps_one_placeholder(self, redactor: Redactor) -> None:
        """Coreference must survive redaction or cross-clause reasoning breaks."""
        text = "Notify a@b.com. Copies go to a@b.com. Escalate to c@d.com."
        result = redactor.redact(text)

        assert result.text.count("[[EMAIL_1]]") == 2
        assert "[[EMAIL_2]]" in result.text

    def test_formatting_variants_share_a_placeholder(self, redactor: Redactor) -> None:
        text = "Aadhaar 2345 6789 0124 and 234567890124 are the same number."
        result = redactor.redact(text)
        assert result.text.count("[[AADHAAR_1]]") == 2

    def test_counts_report_types_never_values(self, redactor: Redactor) -> None:
        """The audit record must be safe to ship to a log aggregator."""
        result = redactor.redact("Email a@b.com and PAN ABCPK1234F.")
        counts = result.counts_by_type()

        assert counts == {"email": 1, "pan": 1}
        assert "a@b.com" not in str(counts)

    def test_clean_text_is_returned_unchanged(self, redactor: Redactor) -> None:
        text = "This Agreement governs the supply of services."
        result = redactor.redact(text)
        assert result.text == text
        assert not result.redacted


class TestOffsetMap:
    """Redaction shifts text; spans must still mean what they meant."""

    def test_offsets_after_a_replacement_map_back_correctly(self) -> None:
        original = "Contact jane@acme.com before Friday."
        new, mapping = OffsetMap.apply(original, [Replacement(8, 21, "[[EMAIL_1]]")])

        index = new.index("before")
        start, end = mapping.to_original_range(index, index + 6)
        assert original[start:end] == "before"

    def test_an_offset_inside_a_placeholder_maps_to_the_whole_value(self) -> None:
        original = "Contact jane@acme.com now."
        new, mapping = OffsetMap.apply(original, [Replacement(8, 21, "[[EMAIL_1]]")])

        index = new.index("[[EMAIL")
        start, end = mapping.to_original_range(index, index + 11)
        assert original[start:end] == "jane@acme.com"

    def test_identity_map_is_a_no_op(self) -> None:
        mapping = OffsetMap.identity(20)
        assert mapping.to_original(7) == 7

    def test_overlapping_replacements_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="overlapping"):
            OffsetMap.apply("abcdefgh", [Replacement(0, 5, "X"), Replacement(3, 7, "Y")])

    def test_offsets_survive_many_replacements(self, redactor: Redactor) -> None:
        """The property that matters, asserted end to end over real PII."""
        text = (
            "Email a@b.com, call +91 98765 43210, PAN ABCPK1234F. "
            "The Provider shall indemnify the Client without limit."
        )
        result = redactor.redact(text)

        target = "indemnify"
        index = result.text.index(target)
        start, end = result.offset_map.to_original_range(index, index + len(target))
        assert text[start:end] == target
