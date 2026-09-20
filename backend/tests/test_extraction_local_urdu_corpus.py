"""The real documents, when this machine has them.

WHY THIS FILE SKIPS INSTEAD OF FAILING

The Urdu source PDFs are gitignored local artefacts. A test that required them
would fail for every other developer and in CI, which would make it a nuisance
rather than a check. Everything these assert is also covered deterministically
by `test_extraction_text_layer_trust.py` and
`test_extraction_untrusted_pdf_endtoend.py`, using synthetic pages that need no
document bytes.

What this file adds is the one thing a synthetic fixture cannot give: proof
that the rule still behaves on the ACTUAL files it was measured against, and on
the actual English corpus it must not damage. Run locally, it is the regression
test for the measurement itself.

The English statutes here are public law, checked into the repository. No
client document is touched: `backend/uploads/docs/` holds real client uploads
and is never read by these tests.
"""
from __future__ import annotations

import glob

import pytest

from app.ai import extraction as E

_URDU = sorted(glob.glob("ocr_eval/fixtures/urdu_candidates_2026_09_14/*.pdf"))
_ENGLISH = sorted(glob.glob("knowledge_base/raw/**/*.pdf", recursive=True))

needs_urdu = pytest.mark.skipif(
    len(_URDU) < 3, reason="local Urdu corpus not present on this machine")
needs_english = pytest.mark.skipif(
    not _ENGLISH, reason="public English statute corpus not present")


# ══════════════════════════════════════════════════════════════════════════════
# The three NOORI documents must stay out of the analysis entirely
# ══════════════════════════════════════════════════════════════════════════════

@needs_urdu
@pytest.mark.parametrize("path", _URDU)
def test_every_local_noori_document_is_blocked_from_the_prompt(path):
    """MEASURED: 38 pages across 3 documents, every one typeset in Noori and
    every one yielding zero Urdu. Not a character of it may reach the model."""
    result = E.extract_file(path)

    assert result.error_code == E.ERR_UNEXTRACTABLE_TEXT_ENCODING
    assert result.completeness == E.NONE
    assert result.pages_with_text == 0
    assert result.pages_text_untrusted > 0
    # The prompt is built from `result.text`. It must be empty.
    assert result.text.strip() == ""


@needs_urdu
def test_the_local_corpus_is_the_38_pages_that_were_measured():
    """If the corpus on this machine has changed, the measured thresholds no
    longer describe it and the numbers in the code comments are stale."""
    total = sum(E.extract_file(p).pages_text_untrusted for p in _URDU)

    assert total == 38, (
        f"expected the measured 38 undecodable pages, found {total} — "
        "re-measure before trusting the thresholds")


# ══════════════════════════════════════════════════════════════════════════════
# The English corpus must be untouched
# ══════════════════════════════════════════════════════════════════════════════

@needs_english
@pytest.mark.parametrize("path", _ENGLISH)
def test_no_english_statute_page_is_ever_discarded(path):
    """THE FALSE-POSITIVE GUARD. An earlier coherence-only rule discarded 7
    real pages of these documents. Zero may be discarded now."""
    result = E.extract_file(path)

    assert result.pages_text_untrusted == 0, (
        "an English statute page was thrown away")
    assert result.error_code != E.ERR_UNEXTRACTABLE_TEXT_ENCODING
    assert result.pages_with_text > 0


@needs_english
def test_the_seven_previously_rejected_pages_are_kept_now():
    """The exact pages the old rule deleted, named so the regression cannot
    come back quietly. Each is kept; each is at most SUSPECT."""
    from pypdf import PdfReader

    cases = [
        ("knowledge_base/raw/criminal/Police Law.pdf", 80),
        ("knowledge_base/raw/criminal/PAKISTAN PENAL CODE.pdf", 212),
        ("knowledge_base/raw/criminal/PAKISTAN PENAL CODE.pdf", 213),
        ("knowledge_base/raw/civil/TRANSFER  PROPERTY Act.pdf", 57),
        ("knowledge_base/raw/civil/TRANSFER  PROPERTY Act.pdf", 58),
        ("knowledge_base/raw/civil/TRANSFER  PROPERTY Act.pdf", 59),
        ("knowledge_base/raw/civil/TRANSFER  PROPERTY Act.pdf", 61),
    ]
    missing = [c for c in cases if not glob.glob(c[0])]
    if missing:
        pytest.skip(f"corpus incomplete: {missing}")

    for path, number in cases:
        page = PdfReader(path).pages[number - 1]
        text = (page.extract_text() or "").strip()

        verdict = E._assess_text_layer(page, text)

        assert verdict != E.TEXT_UNUSABLE, f"{path} p{number} was discarded"
        assert E._legacy_urdu_font_ratio(page) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# The measurement behind the thresholds
# ══════════════════════════════════════════════════════════════════════════════

@needs_urdu
@needs_english
def test_the_measured_false_positive_rate_is_still_zero():
    """The whole trade, on the real corpora, in one assertion.

    MEASURED at the time of writing: 38 of 38 Noori pages discarded, 0 of 937
    English pages discarded, 7 English pages kept as suspect.
    """
    from pypdf import PdfReader

    def tally(paths):
        counts = {E.TEXT_OK: 0, E.TEXT_SUSPECT: 0, E.TEXT_UNUSABLE: 0}
        for path in paths:
            for page in PdfReader(path).pages:
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                counts[E._assess_text_layer(page, text)] += 1
        return counts

    urdu = tally(_URDU)
    english = tally(_ENGLISH)

    assert urdu[E.TEXT_OK] == 0 and urdu[E.TEXT_SUSPECT] == 0, (
        f"a Noori page escaped detection: {urdu}")
    assert urdu[E.TEXT_UNUSABLE] == 38, urdu
    assert english[E.TEXT_UNUSABLE] == 0, (
        f"{english[E.TEXT_UNUSABLE]} English pages were discarded")
