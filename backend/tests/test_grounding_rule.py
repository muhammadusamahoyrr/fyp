"""The PROPOSED grounding veto (app/ai/grounding.py). Not yet wired in.

The rule exists because bm25_confidence == 0.0 -- "not one distinctive term of
this question appears anywhere in the evidence" -- currently means the signal is
DROPPED from arbitration rather than counted against the answer. In
FAILURE_CASE_001 that let a wrong statutory citation ship as grounded at
confidence 0.85.

The tests are written around the thing that makes this hard: a zero is
ambiguous. The corpus is English, so an Urdu query's terms can never appear in
it and score 0.0 for a reason unrelated to retrieval quality. On the recorded
pool, 5 of 5 non-English turns scored zero. A rule that treats every zero as
failure would caution or refuse every Urdu query the system receives -- so the
false-zero cases below are not edge cases, they are the majority behaviour for a
core user group.
"""
import pytest

from app.ai.grounding import (LexicalSupport, caution_reason, lexical_support,
                              may_be_grounded)


class TestWhenTheSignalMaySpeak:
    def test_english_with_overlap_is_supported(self):
        assert lexical_support(bm25_confidence=0.58, language="en") \
            is LexicalSupport.SUPPORTED

    def test_english_with_zero_overlap_is_contradicted(self):
        """The case the rule exists for: overlap was possible, there was none."""
        assert lexical_support(bm25_confidence=0.0, language="en") \
            is LexicalSupport.CONTRADICTED

    def test_urdu_zero_says_nothing(self):
        """The corpus is English. An Urdu term cannot appear in it, so zero is
        not evidence of anything."""
        assert lexical_support(bm25_confidence=0.0, language="ur") \
            is LexicalSupport.NOT_APPLICABLE

    def test_roman_urdu_zero_says_nothing(self):
        """Latin script, but 'chori ki saza' shares no vocabulary with an
        English corpus. Script detection alone would miss this, which is why
        the language label is what gates applicability."""
        assert lexical_support(bm25_confidence=0.0, language="roman_urdu") \
            is LexicalSupport.NOT_APPLICABLE

    def test_urdu_script_under_an_en_label_still_says_nothing(self):
        """triage has mislabelled language before (hence _reconcile_language).
        A mislabel must not turn a false zero into a caution."""
        assert lexical_support(
            bm25_confidence=0.0, language="en",
            query="چوری کی سزا پاکستان پینل کوڈ میں کیا ہے؟",
        ) is LexicalSupport.NOT_APPLICABLE

    def test_engine_backed_answers_are_exempt(self):
        """A court-fee figure is computed, not retrieved; it has no reason to
        share vocabulary with a statute chunk. hallucination_node already
        treats engine output as ground truth."""
        assert lexical_support(
            bm25_confidence=0.0, language="en", has_engine_results=True,
        ) is LexicalSupport.NOT_APPLICABLE

    def test_the_floor_is_exact_zero_by_default(self):
        """Anything above zero is some support. Raising the floor trades false
        answers for false cautions and must be measured, not assumed."""
        assert lexical_support(bm25_confidence=0.0001, language="en") \
            is LexicalSupport.SUPPORTED

    def test_the_floor_is_configurable_for_measurement(self):
        assert lexical_support(bm25_confidence=0.05, language="en", floor=0.1) \
            is LexicalSupport.CONTRADICTED


class TestTheVeto:
    def test_it_overrides_a_grounded_verdict_on_zero_overlap(self):
        assert may_be_grounded(LexicalSupport.CONTRADICTED, True) is False

    def test_it_never_rescues_an_ungrounded_verdict(self):
        """A veto only ever turns True into False. Lexical overlap is not
        evidence that the legal reasoning is right."""
        assert may_be_grounded(LexicalSupport.SUPPORTED, False) is False
        assert may_be_grounded(LexicalSupport.NOT_APPLICABLE, False) is False

    def test_it_leaves_the_model_in_charge_where_it_cannot_speak(self):
        """Urdu turns must behave exactly as they do today."""
        assert may_be_grounded(LexicalSupport.NOT_APPLICABLE, True) is True

    def test_supported_does_not_force_grounded(self):
        assert may_be_grounded(LexicalSupport.SUPPORTED, True) is True


class TestFailureCase001:
    """The recorded turn, end to end through the proposed rule."""

    def test_the_recorded_turn_would_have_been_vetoed(self):
        support = lexical_support(
            bm25_confidence=0.0,     # as recorded
            language="en",           # as recorded
            query="What is the punishment for theft under the Pakistan Penal Code?",
            has_engine_results=False,
        )
        assert support is LexicalSupport.CONTRADICTED
        assert may_be_grounded(support, model_says_grounded=True) is False
        assert "bm25_confidence = 0.0" in caution_reason(support)

    def test_a_reason_is_recorded_for_audit(self):
        assert caution_reason(LexicalSupport.SUPPORTED) is None
        assert caution_reason(LexicalSupport.NOT_APPLICABLE) is None
        assert caution_reason(LexicalSupport.CONTRADICTED)


class TestItIsNotWiredIn:
    def test_the_request_path_does_not_import_it_yet(self):
        """This module is a proposal. If something starts importing it, that is
        a deliberate decision and this test should be deleted in the same
        commit -- not left passing by accident."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        importers = [
            p for p in root.rglob("*.py")
            if "grounding" in p.read_text(encoding="utf-8", errors="ignore")
            and p.name != "grounding.py"
            and "import" in p.read_text(encoding="utf-8", errors="ignore")
            and ("from app.ai.grounding" in p.read_text(encoding="utf-8", errors="ignore")
                 or "from app.ai import grounding" in p.read_text(encoding="utf-8", errors="ignore"))
        ]
        assert importers == [], f"grounding.py is now wired into {importers}"
