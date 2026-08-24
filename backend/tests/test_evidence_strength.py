"""Documents are not interchangeable, and since 2026 they are less so.

The evidence list was flat, which implied a power of attorney and a title deed
carry the same weight. The Punjab Land Revenue (Amendment) Ordinance 2026
(18 Feb 2026) moved transfers to e-registration, stopped mutations being entered
without a registered deed, and limited patwaris to inheritance transfers.

Flattering weak evidence is the expensive direction to be wrong in: a user
encouraged to file on a POA alone now carries the false-complaint exposure the
POIP Amendment created (Rs 500,000 and up to five years).
"""
import pytest

from app.services.dispute_intake import DOCUMENT_STRENGTH, assess_documents


class TestTitleEvidence:
    def test_a_registered_deed_shows_title(self):
        a = assess_documents(["registered_deed"])
        assert a["registry_backed"] is True
        assert a["title_evidence_shown"] is True
        assert a["recommended_next"] == []

    def test_a_fard_shows_title(self):
        assert assess_documents(["title_deed_fard"])["title_evidence_shown"] is True

    def test_a_power_of_attorney_does_not(self):
        """A POA is authority to act for someone else. poa_misuse exists as a
        grievance category precisely because it gets treated as ownership."""
        a = assess_documents(["power_of_attorney"])
        assert a["title_evidence_shown"] is False
        assert "power of attorney" in a["summary"].lower()
        assert a["recommended_next"]

    def test_a_cnic_does_not(self):
        assert assess_documents(["cnic_nicop"])["title_evidence_shown"] is False

    def test_a_poa_plus_cnic_is_still_not_title(self):
        """Two documents that each prove nothing about ownership do not add up
        to one that does."""
        a = assess_documents(["power_of_attorney", "cnic_nicop"])
        assert a["title_evidence_shown"] is False
        assert "will not do it" in a["summary"]


class TestThe2026Rules:
    def test_a_mutation_alone_is_flagged_as_insufficient(self):
        """Post-2026 a mutation cannot be entered without a registered deed, so a
        mutation with no registry behind it is a gap, not a proof."""
        a = assess_documents(["mutation_inteqal"])
        assert a["registry_backed"] is False
        assert "registered deed" in a["summary"]

    def test_a_mutation_with_the_registry_is_registry_backed(self):
        a = assess_documents(["mutation_inteqal", "registered_deed"])
        assert a["registry_backed"] is True

    def test_an_unregistered_agreement_carries_no_weight(self):
        assert DOCUMENT_STRENGTH["unregistered_agreement"]["weight"] == 0

    def test_the_ordinance_is_cited_for_audit(self):
        a = assess_documents(["fir"])
        assert "Punjab Land Revenue (Amendment) Ordinance 2026" in a["source"]
        assert "18 February 2026" in a["source"]


class TestOrderingAndEdges:
    def test_the_strongest_document_is_identified(self):
        a = assess_documents(["cnic_nicop", "registered_deed", "fir"])
        assert a["strongest"] == "registered_deed"
        assert a["held"][0]["code"] == "registered_deed"

    def test_no_documents_is_handled(self):
        for empty in ([], None, ["none"]):
            a = assess_documents(empty)
            assert a["title_evidence_shown"] is False
            assert a["strongest"] is None

    def test_unknown_codes_are_ignored_not_crashed_on(self):
        a = assess_documents(["registered_deed", "something_new"])
        assert a["registry_backed"] is True

    def test_supporting_documents_are_not_mistaken_for_title(self):
        """An FIR and tax receipts tell a story; neither says who owns it."""
        a = assess_documents(["fir", "tax_receipts"])
        assert a["title_evidence_shown"] is False
        assert "do not establish title" in a["summary"]
