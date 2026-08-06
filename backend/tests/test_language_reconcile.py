"""Language label vs. script actually present.

Observed in production: a Roman-Urdu maintenance query was labelled "ur" (Urdu
script) despite containing no Urdu characters. Triage only transliterates when
it believes the input is Roman Urdu, and generation answers in the language it
was told — so the mislabel both skipped normalisation and replied in the wrong
script. Which script a string uses is a fact, so it overrides the model.
"""
import pytest

from app.ai.nodes.triage_node import _URDU_SCRIPT_RE, _reconcile_language

ROMAN_URDU = "mera shohar mujhe kharch nahi deta, maintenance ka kya tareeqa hai?"
URDU_SCRIPT = "میرے والد کی جائیداد میں میرا حصہ کتنا ہے؟"
ENGLISH = "What is the punishment for theft under the Pakistan Penal Code?"


# ── the observed failure ──────────────────────────────────────────────────────

def test_the_production_mislabel_is_corrected():
    """Regression pin: this exact query was labelled 'ur' and refused."""
    assert _reconcile_language(ROMAN_URDU, "ur") == "roman_urdu"


def test_latin_text_can_never_be_labelled_urdu_script():
    for text in (ROMAN_URDU, ENGLISH, "theek hai", "shukria"):
        assert _reconcile_language(text, "ur") == "roman_urdu"


def test_urdu_script_is_not_mislabelled_as_roman():
    assert _reconcile_language(URDU_SCRIPT, "roman_urdu") == "ur"


# ── correct labels are left alone ─────────────────────────────────────────────

@pytest.mark.parametrize("text,label", [
    (ROMAN_URDU, "roman_urdu"),
    (URDU_SCRIPT, "ur"),
    (ENGLISH, "en"),
])
def test_correct_labels_pass_through_unchanged(text, label):
    assert _reconcile_language(text, label) == label


def test_english_label_is_never_overridden():
    """The check only arbitrates between ur and roman_urdu. An English label on
    Urdu-script text is a different problem and is left to the model."""
    assert _reconcile_language(URDU_SCRIPT, "en") == "en"
    assert _reconcile_language(ENGLISH, "en") == "en"


# ── the script detector itself ────────────────────────────────────────────────

def test_script_detector_finds_urdu_characters():
    assert _URDU_SCRIPT_RE.search(URDU_SCRIPT)
    assert _URDU_SCRIPT_RE.search("قتل")


def test_script_detector_ignores_latin_and_digits():
    for text in (ROMAN_URDU, ENGLISH, "PPC 302", "35202-1234567-1", ""):
        assert not _URDU_SCRIPT_RE.search(text)


def test_mixed_script_counts_as_urdu_script():
    """A query mixing scripts still contains Urdu, so transliteration is not
    needed and 'ur' is the right label."""
    assert _reconcile_language("PPC 302 کے تحت سزا کیا ہے؟", "roman_urdu") == "ur"
