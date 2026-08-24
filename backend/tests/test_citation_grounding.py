"""Citation groundedness — a measurement, and the traps found while building it.

Every test here encodes something that actually went wrong or was actually
observed in this system's recorded answers. None of it is hypothetical.
"""
import pytest

from app.ai.citation_grounding import (extract_citations, grounding_report,
                                       retrieved_citations)


class TestTheParser:
    def test_family_first(self):
        assert extract_citations("punishable under PPC Section 379") == {"PPC 1860 s.379"}

    def test_section_first(self):
        assert extract_citations("under section 154 of the Code of Criminal Procedure") \
            == {"CrPC 1898 s.154"}

    def test_abbreviated_forms(self):
        assert extract_citations("see s.302 PPC and CrPC s.497") \
            == {"PPC 1860 s.302", "CrPC 1898 s.497"}

    def test_the_statute_year_is_never_a_section(self):
        """The bug that manufactured findings out of nothing: an early version
        reported 'PPC 1860 s.1860' and 'CrPC 1898 s.1898' as hallucinated
        citations. They were the parser reading the statute's own year."""
        assert extract_citations("under the PPC 1860 and the CrPC 1898") == set()

    def test_year_after_family_does_not_shift_the_section(self):
        assert extract_citations("PPC 1860 Section 302") == {"PPC 1860 s.302"}

    def test_a_bare_number_is_not_a_citation(self):
        """"PPC 302" without a section marker is the same shape as "PPC 1860".
        Under-counting is the safe direction when the output is an accusation."""
        assert extract_citations("under PPC 302 he is liable") == set()

    def test_sub_sections_resolve_to_their_section(self):
        assert extract_citations("bail under section 497(2) CrPC") == {"CrPC 1898 s.497"}

    def test_empty_and_none_are_safe(self):
        assert extract_citations("") == set()
        assert extract_citations(None) == set()


class TestTheReport:
    CHUNKS = [{"statute": "PPC 1860", "section_number": "379"},
              {"statute": "CrPC 1898", "section_number": "154"}]

    def test_a_fully_grounded_answer(self):
        r = grounding_report("theft under PPC Section 379", self.CHUNKS)
        assert r["measurable"] and r["ungrounded"] == [] and r["grounded_ratio"] == 1.0

    def test_an_ungrounded_citation_is_identified(self):
        r = grounding_report("theft under PPC Section 382", self.CHUNKS)
        assert r["ungrounded"] == ["PPC 1860 s.382"]
        assert r["grounded_ratio"] == 0.0

    def test_a_mixed_answer_reports_a_ratio(self):
        r = grounding_report("PPC Section 379 and PPC Section 411", self.CHUNKS)
        assert r["grounded"] == ["PPC 1860 s.379"]
        assert r["ungrounded"] == ["PPC 1860 s.411"]
        assert r["grounded_ratio"] == 0.5

    def test_no_citation_is_not_a_pass(self):
        """An answer asserting law without citing any has nothing to ground.
        Calling that 'grounded' would flatter exactly the worst answers."""
        r = grounding_report("You will probably win this case.", self.CHUNKS)
        assert r["measurable"] is False
        assert r["grounded_ratio"] is None
        assert "not a finding of groundedness" in r["reason"]

    def test_no_retrieval_makes_every_citation_ungrounded(self):
        r = grounding_report("PPC Section 379", [])
        assert r["ungrounded"] == ["PPC 1860 s.379"]


class TestItRefusesToBeAVerdict:
    def test_correct_law_recalled_from_memory_still_reads_as_ungrounded(self):
        """Observed in the recorded data: asked how to file an FIR, the system
        cited CrPC s.154 — exactly the right provision — which retrieval had not
        supplied. The report must not present this as an error."""
        r = grounding_report("File under section 154 of the Code of Criminal Procedure",
                             [{"statute": "CrPC 1898", "section_number": "156"}])
        assert r["ungrounded"] == ["CrPC 1898 s.154"]
        assert "does NOT mean the citation is wrong" in r["note"]

    def test_the_module_carries_its_own_warning(self):
        """83% of recorded answers with citations would flag. Anyone reaching for
        this as a gate must hit the reason not to, in the file itself."""
        import app.ai.citation_grounding as cg
        assert "MEASUREMENT, NOT A GATE" in cg.__doc__
        assert "83%" in cg.__doc__


class TestFailureCase001:
    def test_the_recorded_failure_is_detected(self):
        """The wrong citation from FAILURE_CASE_001: PPC 382 asserted as theft,
        never retrieved. It passed the LLM hallucination check, is_grounded and
        convergence at 0.85 confidence."""
        chunks = [{"statute": "CrPC 1898", "section_number": s}
                  for s in ("15", "3", "221", "234", "68", "367", "555", "108", "260", "235")]
        chunks += [{"statute": "PPC 1860", "section_number": s} for s in ("184", "161", "511")]
        r = grounding_report(
            "Applicable Law: PPC Section 382 — Theft. According to CrPC Section 15...",
            chunks)
        assert "PPC 1860 s.382" in r["ungrounded"]
        assert "CrPC 1898 s.15" in r["grounded"]
