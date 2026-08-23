"""triage must not silently corrupt an English query.

Its own prompt says "If language is 'en': return the original query unchanged",
and until 2026-08-23 nothing enforced it. FAILURE_CASE_001: an English question
about the punishment for theft was labelled "en" and rewritten into corrupted
Urdu that injected "sarkari" (official) three times. normalized_query is what
retrieval searches AND what the answer cache is keyed on, so the corruption sent
retrieval after the wrong concept -- 18 chunks, none of them PPC 379 -- and the
answer cited the wrong section at confidence 0.85 with every gate satisfied.

The repair is deliberate rather than a raise: the contract names the correct
value, so failing the turn would deny a user an answer over a fault we can fix
exactly. What must never happen is a SILENT repair -- a turn built on corrupted
input must not be gradeable as though the pipeline had behaved.
"""
import pytest

from scripts.audit_triage_invariant import VIOLATION, violates


class TestAuditPredicate:
    def test_corrupted_english_is_a_violation(self):
        assert violates({
            "language": "en",
            "query": "What is the punishment for theft under the Pakistan Penal Code?",
            "normalized_query": "ما سرکاری جرائم کے تحت سرکاری قانون میں",
        })

    def test_untouched_english_is_clean(self):
        q = "What is the punishment for theft?"
        assert not violates({"language": "en", "query": q, "normalized_query": q})

    def test_trailing_whitespace_is_not_corruption(self):
        assert not violates({
            "language": "en",
            "query": "What is the limitation period? ",
            "normalized_query": "What is the limitation period?",
        })

    def test_empty_normalized_is_not_a_violation(self):
        """triage falls back to the raw query, which is the correct value."""
        assert not violates({
            "language": "en", "query": "Anything?", "normalized_query": "",
        })

    def test_roman_urdu_transliteration_is_expected(self):
        """The invariant binds 'en' only. Transliterating Roman Urdu into Urdu
        script is the node doing its job, and must not be flagged."""
        assert not violates({
            "language": "roman_urdu",
            "query": "mujhe police ne mara",
            "normalized_query": "مجھے پولیس نے مارا",
        })

    def test_urdu_passthrough_is_expected(self):
        assert not violates({
            "language": "ur",
            "query": "مجھے پولیس نے مارا",
            "normalized_query": "مجھے پولیس نے مارا",
        })

    def test_a_record_with_no_language_is_not_judged(self):
        """Legacy records predate the field; absence is not evidence of a bug."""
        assert not violates({"query": "x", "normalized_query": "y"})


class TestPoolExclusion:
    def test_flagged_turns_are_excluded_from_labelling(self):
        """Annotator time is the scarcest input; spending it on output the
        pipeline itself flagged as corrupt is the one waste that also damages
        the result."""
        from app.services.labeling_service import _ANSWER_TURNS_ONLY
        assert "invariant_violation" in _ANSWER_TURNS_ONLY

    def test_the_filter_still_admits_records_predating_the_field(self):
        """A filter that silently dropped every existing record would empty the
        pool -- the failure mode this project cannot afford twice."""
        from app.services.labeling_service import _ANSWER_TURNS_ONLY
        clause = _ANSWER_TURNS_ONLY["invariant_violation"]
        # In MongoDB, matching null also matches a missing field.
        assert None in clause["$in"]


class TestProvenanceCarriesTheFlag:
    def test_a_clean_turn_records_null(self):
        from app.services.provenance_service import build_record
        rec = build_record({"query": "q", "language": "en"}, "s", "u", "r")
        assert rec["invariant_violation"] is None

    def test_a_violated_turn_records_the_reason(self):
        from app.services.provenance_service import build_record
        rec = build_record(
            {"query": "q", "language": "en", "invariant_violation": VIOLATION},
            "s", "u", "r",
        )
        assert rec["invariant_violation"] == VIOLATION


class TestNodeRepair:
    """The repair itself, as triage_node performs it."""

    def test_corrupted_english_is_repaired_to_the_original(self):
        from app.ai.nodes.triage_node import (EN_INVARIANT_VIOLATION,
                                              _enforce_en_invariant)
        q = "What is the punishment for theft under the Pakistan Penal Code?"
        out, flag = _enforce_en_invariant(q, "en", "ما سرکاری جرائم کے تحت")
        assert out == q, "retrieval must search the question the user asked"
        assert flag == EN_INVARIANT_VIOLATION

    def test_a_clean_english_turn_is_untouched_and_unflagged(self):
        from app.ai.nodes.triage_node import _enforce_en_invariant
        q = "What is the limitation period for a suit for possession?"
        out, flag = _enforce_en_invariant(q, "en", q)
        assert (out, flag) == (q, None)

    def test_roman_urdu_transliteration_survives(self):
        """The invariant binds 'en' only. Clobbering a correct transliteration
        would break the feature it was written to protect."""
        from app.ai.nodes.triage_node import _enforce_en_invariant
        out, flag = _enforce_en_invariant(
            "mujhe police ne mara", "roman_urdu", "مجھے پولیس نے مارا")
        assert out == "مجھے پولیس نے مارا"
        assert flag is None

    def test_empty_normalized_is_left_for_the_callers_fallback(self):
        from app.ai.nodes.triage_node import _enforce_en_invariant
        out, flag = _enforce_en_invariant("Anything?", "en", "")
        assert flag is None

    def test_whitespace_only_difference_is_not_flagged(self):
        from app.ai.nodes.triage_node import _enforce_en_invariant
        out, flag = _enforce_en_invariant("Is bail available? ", "en",
                                          "Is bail available?")
        assert flag is None

    def test_it_logs_at_error_not_quietly(self, caplog):
        """A repair nobody can see is how this bug survived in the first place."""
        import logging

        from app.ai.nodes.triage_node import _enforce_en_invariant
        with caplog.at_level(logging.ERROR):
            _enforce_en_invariant("What is theft?", "en", "ما سرکاری")
        assert any("INVARIANT VIOLATED" in r.message or
                   "INVARIANT VIOLATED" in r.getMessage()
                   for r in caplog.records)
