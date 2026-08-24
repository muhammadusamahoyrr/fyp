"""Case-law references must be something a lawyer can look up.

The pipeline previously rendered `f"LHC {judgment_id}"` — "LHC 2026LHC3442" —
into the citation slot. That is an internal document id with a court prefix
bolted on: unverifiable, uncitable, and sitting exactly where a lawyer would
copy from into a filing. Courts fined lawyers $145,000 in Q1 2026 over citations
that could not be verified.

These judgments are mostly UNREPORTED — recent High Court decisions with no
PLD/SCMR number yet. The correct reference for one is party names, case number,
court and year, and all four are already stored.
"""
import pytest

from app.services.citator_service import format_reference, is_reportable_citation

FULL = {"_id": "2026LHC4480", "title": "Nisar Ahmad Khan Vs The State etc.",
        "case_no": "Crl. Misc. 3189/26", "court": "LHC", "year": 2026}


class TestTheReference:
    def test_a_complete_record_reads_like_a_citation(self):
        assert format_reference(FULL) == \
            "Nisar Ahmad Khan Vs The State etc. — Crl. Misc. 3189/26 (LHC 2026)"

    def test_the_internal_id_never_appears_when_real_fields_exist(self):
        """The id is not a citation and must not be shown as one."""
        assert "2026LHC4480" not in format_reference(FULL)

    def test_missing_case_number_still_gives_a_usable_reference(self):
        r = format_reference({k: v for k, v in FULL.items() if k != "case_no"})
        assert r == "Nisar Ahmad Khan Vs The State etc. (LHC 2026)"

    def test_missing_party_names_falls_back_to_the_case_number(self):
        """Metadata extraction is imperfect — 95 of 502 records have no title."""
        r = format_reference({k: v for k, v in FULL.items() if k != "title"})
        assert r == "Crl. Misc. 3189/26 (LHC 2026)"

    def test_court_and_year_alone_are_marked_as_a_bare_reference(self):
        r = format_reference({"_id": "2026LHC1", "court": "LHC", "year": 2026})
        assert r == "LHC 2026 judgment [ref: 2026LHC1]"

    def test_an_empty_record_says_so_rather_than_inventing(self):
        assert format_reference({}) == "Unidentified judgment"
        assert format_reference({"_id": "x"}) == "Unidentified judgment [ref: x]"


class TestCitabilityIsFlagged:
    def test_a_real_reference_is_citable(self):
        assert is_reportable_citation(format_reference(FULL)) is True

    def test_a_bare_id_reference_is_not_citable(self):
        """Anything carrying [ref:] is an internal handle, not an authority.
        Callers use this to keep such strings out of citation slots."""
        assert is_reportable_citation(format_reference({"_id": "x"})) is False
        assert is_reportable_citation(
            format_reference({"_id": "x", "court": "LHC", "year": 2026})) is False

    def test_empty_is_not_citable(self):
        assert is_reportable_citation("") is False
        assert is_reportable_citation(None) is False


class TestTheNodesNoLongerSynthesise:
    def test_retrieval_node_uses_the_formatter(self):
        import inspect
        from app.ai.nodes import retrieval_node
        src = inspect.getsource(retrieval_node)
        assert '"citation":     _reference(' in src
        # the old pattern must not come back in executable code
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert 'f"LHC {jid}"' not in code

    def test_generation_node_has_no_id_fallback(self):
        import inspect
        from app.ai.nodes import generation_node
        code = "\n".join(l for l in inspect.getsource(generation_node).splitlines()
                         if not l.strip().startswith("#"))
        assert "f\"LHC {c.get('judgment_id'" not in code
        assert '"LHC judgment"' not in code
