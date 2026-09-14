"""Born-digital PDFs whose text layer does not decode must not read as readable.

THE DEFECT, REPRODUCED AGAINST THE REAL EXTRACTOR

A Pakistani statute typeset in InPage's Noori Nastaliq is born-digital: vector
text, no images, a real text layer. Extracting it returns thousands of
characters and ZERO usable Urdu -- the glyphs are mapped onto Latin and symbol
codepoints, so what comes back is mojibake. Measured on a real file before the
fix:

    outcome          succeeded
    completeness     complete        <-- the defect
    pages_with_text  9 of 9
    extracted chars  9019
    usable Urdu      0

`complete` is what the analysis prompt trusts, so nine pages of glyph soup were
handed to the model as the client's evidence. The rule that produced this was
`if stripped:` -- any non-empty string counted as a page of text.

WHY DISCARDING TAKES MORE EVIDENCE THAN SUSPECTING

Deleting a page of a client's evidence is destructive, so it requires positive,
measured proof of a specific known-bad encoding: a legacy Urdu font that
produced no Urdu. An earlier version rejected on the SHAPE of the text alone,
and measurement showed it wrongly discarded 7 real English pages. Text that
merely looks odd is now kept, and only the document's completeness claim is
withdrawn.

WHY THESE TESTS USE SYNTHETIC PAGES

The real Urdu PDFs are gitignored local artefacts, so a test that needs them
cannot run anywhere else. The page objects here are duck-typed: the assessor
reads exactly one thing from a page -- its font dictionary -- so a fake carrying
a font dictionary exercises the real code path deterministically, on any
machine, with no document bytes.

`test_extraction_local_urdu_corpus.py` additionally runs the real files when
they are present, and skips when they are not.
"""
from __future__ import annotations

import pytest

from app.ai import extraction as E


# ── duck-typed pages ────────────────────────────────────────────────────────

class _Font(dict):
    """A PDF font dictionary. `get_object()` is what pypdf hands back."""
    def get_object(self):
        return self


class _Page(dict):
    """Just enough page for the assessor: `page["/Resources"]["/Font"]`."""
    def __init__(self, fonts):
        super().__init__({"/Resources": {"/Font": fonts}})


def _noori_page(total=10, legacy=10):
    """A page typeset mostly in Noori, as the real documents are.

    Real Noori pages run 94-98% legacy fonts, never 100% -- they mix in an
    Arial for Latin numerals -- so this mirrors that shape.
    """
    fonts = {}
    for i in range(total):
        name = f"/CXOYBI+NOORIN{i:02d}" if i < legacy else "/MFZMRR+Arial"
        fonts[f"/F{i}"] = _Font({"/BaseFont": name})
    return _Page(fonts)


def _ordinary_page(total=5):
    names = ["/Arial-BoldMT", "/TimesNewRomanPSMT", "/ABCDEE+Calibri",
             "/ArialMT", "/CourierNewPSMT"]
    return _Page({f"/F{i}": _Font({"/BaseFont": names[i % len(names)]})
                  for i in range(total)})


#: Glyph soup of the shape a legacy InPage font produces: letter-bearing tokens
#: heavily littered with symbols, at the length of a real page. Deliberately
#: meaningless -- no document content.
_SOUP_TOKENS = ('Z}5i]w#@', '[O~2}q!', '}[O5i#w', '%^&*l1', ']q2~O[', '@#w]i5}Z',
                '~q[2O}', 'w#5i]Z', '}O[~q2', '!i5w#]', '2~O}[q', 'l1*&^%')
MOJIBAKE = " ".join(
    ['!!!!**', '""""$$', '$$4477', '9999', '1111', '((((']
    + [_SOUP_TOKENS[i % len(_SOUP_TOKENS)] for i in range(84)])

ENGLISH = (
    "The total fine of 1000 rupees only is imposed on the respondent today "
    "under section 302 of the Act, and the appeal shall lie to the High Court "
    "within thirty days of the date on which the order was communicated to the "
    "party aggrieved by it, failing which the right of appeal shall stand "
    "forfeited and the order shall become final for all purposes under the said "
    "Act and the rules framed thereunder by the competent authority."
)

#: Valid Unicode Urdu. Must stay readable: text is never distrusted for not
#: being English, and a modern Urdu PDF is exactly what this must not break.
URDU_UNICODE = (
    "یہ ایک قانونی دستاویز ہے۔ دفعہ 302 کے تحت مقدمہ درج کیا گیا۔ "
    "عدالت نے فیصلہ سنایا اور جرمانہ عائد کیا۔ "
    "درخواست گزار نے اپنے وکیل کے ذریعے اپیل دائر کی اور عدالت نے "
    "فریقین کو سننے کے بعد حکم صادر فرمایا کہ مقدمہ قانون کے مطابق "
    "چلایا جائے اور تمام دستاویزات ریکارڈ پر لائی جائیں۔"
)

#: A statute page of section numbers and omission markers. An earlier metric
#: scored this 0.686 and distrusted it -- digits and legal punctuation are
#: CONTENT, not evidence of a broken encoding.
NUMERIC_STATUTE = (
    "1\n[(4)] Sections 26 and 27 and the definition of easement in section 2 "
    "shall not apply to cases arising in territories to which the Indian "
    "Easements Act, 1882\n2\n, may for the time being extend.\n3\n[30. "
    "Provision for suits] 1877.– * * * ] 4 [31. * * * * * * ] 5"
)


# ══════════════════════════════════════════════════════════════════════════════
# What may be DISCARDED: a legacy Urdu font that produced no Urdu
# ══════════════════════════════════════════════════════════════════════════════

def test_noori_font_yielding_no_urdu_is_unusable():
    """THE DEFECT. Both facts hold: the page is typeset in Noori, and no Urdu
    survived the glyph mapping."""
    assert E._assess_text_layer(_noori_page(), MOJIBAKE) == E.TEXT_UNUSABLE


@pytest.mark.parametrize("basefont", [
    "/CXOYBI+NOORIN22", "/PPMMCL+NOORIC", "/ABCDEF+InPageUrdu",
    "/XXXXXX+NastaliqRegular", "/YYYYYY+JameelNooriNastaleeq",
    "noorin48", "Noori Nastaliq",
])
def test_the_legacy_families_are_recognised_whatever_the_subset_tag(basefont):
    """PDF subset tags are random six-letter prefixes and the same family is
    written a dozen ways. Normalisation is what makes the marker list usable."""
    page = _Page({"/F0": _Font({"/BaseFont": basefont})})

    assert E._assess_text_layer(page, MOJIBAKE) == E.TEXT_UNUSABLE


def test_a_mostly_noori_page_still_counts_as_legacy():
    """Real Noori pages mix in an Arial for Latin numerals -- 94-98%, never
    100%. Requiring every font to match would detect nothing."""
    page = _noori_page(total=10, legacy=6)      # 0.6, above the 0.5 floor

    assert E._assess_text_layer(page, MOJIBAKE) == E.TEXT_UNUSABLE


# ══════════════════════════════════════════════════════════════════════════════
# What must SURVIVE
# ══════════════════════════════════════════════════════════════════════════════

def test_valid_unicode_urdu_in_a_noori_named_font_is_kept():
    """THE GUARD THAT MATTERS MOST FOR URDU CLIENTS. The font name alone never
    discards: if the Urdu actually arrived, the text is real and is kept."""
    assert E._assess_text_layer(_noori_page(), URDU_UNICODE) == E.TEXT_OK


def test_valid_unicode_urdu_in_an_ordinary_font_is_kept():
    """Text is never distrusted for not being English."""
    assert E._assess_text_layer(_ordinary_page(), URDU_UNICODE) == E.TEXT_OK


def test_ordinary_english_is_kept():
    assert E._assess_text_layer(_ordinary_page(), ENGLISH) == E.TEXT_OK


def test_a_statute_page_of_numbers_and_markers_is_kept():
    """A false positive an earlier metric produced. Tokens with no letters are
    excluded from the denominator rather than counted against the text."""
    assert E._assess_text_layer(_ordinary_page(), NUMERIC_STATUTE) == E.TEXT_OK


def test_odd_looking_text_without_a_legacy_font_is_suspect_not_discarded():
    """THE SEVEN ENGLISH PAGES. Measured coherence 0.800-0.890 on real English
    statute pages, which the old coherence-only rule DELETED. They are kept
    now, and only the document's completeness claim is withdrawn."""
    assert E._assess_text_layer(_ordinary_page(), MOJIBAKE) == E.TEXT_SUSPECT


@pytest.mark.parametrize("text", [
    "p0",                      # the real regression: a one-token page
    "Annexure A",
    "1000",
    "Schedule II - continued",
])
def test_a_short_page_is_never_judged_on_a_token_or_two(text):
    """FOUND BY AN EXISTING EXTRACTOR TEST. `p0` is one letter of two
    characters, which the coherence metric scores 0.0."""
    assert E._assess_text_layer(_ordinary_page(), text) == E.TEXT_OK


@pytest.mark.parametrize("page", [
    _Page({}),                                    # no fonts
    {"/Resources": {}},                           # no font key
    {},                                           # no resources
    None,                                         # not a page at all
])
def test_malformed_metadata_fails_open_without_crashing(page):
    """Unknown is not evidence. A page we could not inspect keeps its text --
    refusing a document we merely failed to examine is its own dishonesty."""
    assert E._assess_text_layer(page, ENGLISH) == E.TEXT_OK
    assert E._assess_text_layer(page, MOJIBAKE) != E.TEXT_UNUSABLE


def test_empty_text_is_not_judged_here():
    """"No text" is a different finding with a different remedy, handled by the
    completeness rules rather than by trust."""
    assert E._assess_text_layer(_noori_page(), "   ") == E.TEXT_OK


# ══════════════════════════════════════════════════════════════════════════════
# The measured signals
# ══════════════════════════════════════════════════════════════════════════════

def test_the_urdu_script_fraction_separates_real_urdu_from_mojibake():
    assert E._urdu_script_fraction(URDU_UNICODE) > E._URDU_SCRIPT_FLOOR
    assert E._urdu_script_fraction(MOJIBAKE) == 0.0
    assert E._urdu_script_fraction(ENGLISH) == 0.0
    assert E._urdu_script_fraction("") == 0.0


def test_the_legacy_ratio_is_zero_for_every_real_english_basefont():
    """MEASURED: 23 distinct BaseFont names across 937 real English pages, none
    matching. This pins the exact names that were checked."""
    real_english = [
        "/Arial-BoldMT", "/TimesNewRomanPSMT", "/Arial", "/ABCDEE+Calibri",
        "/TimesNewRomanPS-BoldMT", "/ABCDEE+Calibri,Bold", "/Arial-ItalicMT",
        "/ArialMT", "/TimesNewRomanPS-ItalicMT", "/ABCDEE+Calibri,Italic",
        "/BCDEEE+Calibri", "/Arial-BoldItalicMT", "/BCDEEE+SegoeUISymbol",
        "/BCDFEE+SegoeUISymbol", "/TimesNewRomanPS-BoldItalicMT",
        "/ABCDEE+Tahoma", "/CLOIDH+SymbolMT", "/BCDFEE+Calibri-Bold",
        "/CourierNewPSMT", "/Arial-Black", "/ArialNarrow-Bold",
        "/ALFBNJ+SymbolMT", "/ABCDEE+Tahoma,Bold",
    ]
    page = _Page({f"/F{i}": _Font({"/BaseFont": n})
                  for i, n in enumerate(real_english)})

    assert E._legacy_urdu_font_ratio(page) == 0.0
    assert E._assess_text_layer(page, MOJIBAKE) != E.TEXT_UNUSABLE


def test_letter_coherence_ignores_tokens_that_carry_no_letters():
    assert E._letter_coherence("1882 [(4)] * * ]") == 1.0
    assert E._letter_coherence(ENGLISH) >= 0.95
    assert E._letter_coherence(URDU_UNICODE) >= 0.95
    assert E._letter_coherence(MOJIBAKE) < E._LETTER_COHERENCE_FLOOR


def test_the_fixtures_are_long_enough_to_be_judged_at_all():
    """The sample floor must not be a hole the fixtures hide in."""
    for text in (MOJIBAKE, ENGLISH, URDU_UNICODE):
        assert len(E._lettered_tokens(text)) >= E._MIN_TOKENS_TO_JUDGE


def test_the_thresholds_are_the_ones_that_were_measured():
    """PINS THE OPERATING POINT so it cannot drift silently.

    Measured over 975 real pages of public documents: the legacy-font ratio is
    0.940-0.982 on the 38 Noori pages and 0.000 on all 937 English pages, and
    every Noori page yields exactly 0.000 Arabic-script characters. Changing
    any of these requires re-measuring against the real documents -- the Urdu
    files are gitignored, so no test here can catch a regression in the trade.
    """
    assert E._LEGACY_FONT_RATIO_FLOOR == 0.5
    assert E._URDU_SCRIPT_FLOOR == 0.10
    assert E._LETTER_COHERENCE_FLOOR == 0.90
    assert E._MIN_TOKENS_TO_JUDGE == 20
    assert "NOORI" in E._LEGACY_URDU_FONT_MARKERS
    assert "INPAGE" in E._LEGACY_URDU_FONT_MARKERS

    # Below the worst observed Noori page (0.940), above the best English (0.0).
    assert 0.0 < E._LEGACY_FONT_RATIO_FLOOR < 0.940
    # The sample floor sits far below the shortest real Noori page (81 tokens).
    assert E._MIN_TOKENS_TO_JUDGE < 81


def test_the_tounicode_signal_is_gone_entirely():
    """MEASURED: the `/ToUnicode` check passed on 100% of BOTH corpora, so it
    discriminated nothing. It was removed rather than left in place implying a
    corroboration that was never there."""
    assert not hasattr(E, "_NO_TOUNICODE_FLOOR")
    assert not hasattr(E, "_fonts_without_unicode_map")
    assert not hasattr(E, "_text_layer_is_trustworthy")


# ══════════════════════════════════════════════════════════════════════════════
# The error contract
# ══════════════════════════════════════════════════════════════════════════════

LEGACY_MESSAGE = (
    "This document uses an unsupported legacy Urdu text encoding. Urdu OCR is "
    "not currently available. Please provide typed text or an English "
    "translation.")


def test_the_error_code_is_stable_and_machine_readable():
    assert E.ERR_UNEXTRACTABLE_TEXT_ENCODING == "unextractable_text_encoding"


def test_the_user_message_is_the_agreed_wording_and_leaks_nothing():
    message = E.message_for(E.ERR_UNEXTRACTABLE_TEXT_ENCODING)

    assert message == LEGACY_MESSAGE
    lowered = message.lower()
    for leak in (".pdf", "/", "\\", "traceback", "exception", "pypdf",
                 "tounicode", "utf-8", "codec", "noori", "inpage"):
        assert leak not in lowered, f"user message leaks {leak!r}"


def test_the_message_never_asks_for_a_scan_or_photo():
    """Urdu OCR is deferred, so a scan would be exactly as unreadable as the
    original. Advising one sends the client away to do work that cannot help."""
    lowered = E.message_for(E.ERR_UNEXTRACTABLE_TEXT_ENCODING).lower()

    assert "scan" not in lowered and "photo" not in lowered
    assert "translation" in lowered


def test_the_intake_reason_vocabulary_explains_it_without_jargon():
    from app.services.intake_service import _UNREAD_REASONS

    reason = _UNREAD_REASONS["unextractable_encoding"].lower()

    assert "legacy urdu" in reason
    assert "translation" in reason
    assert "scan" not in reason and "photo" not in reason
    for leak in (".pdf", "tounicode", "traceback", "noori"):
        assert leak not in reason


# ══════════════════════════════════════════════════════════════════════════════
# The composed intake path: unusable text must never reach the prompt
# ══════════════════════════════════════════════════════════════════════════════

def _result(**kw):
    """An ExtractionResult shaped like what the runner returns."""
    base = dict(outcome=E.OUTCOME_SUCCEEDED, completeness=E.COMPLETE,
                pages_total=3, pages_attempted=3, pages_with_text=3)
    base.update(kw)
    return E.ExtractionResult(**base)


async def _run_intake(monkeypatch, tmp_path, results):
    """Drive the real `_extract_intake_evidence` over crafted results."""
    from app.ai import extraction_runner
    from app.services import intake_service as S

    monkeypatch.setattr(S, "_EVIDENCE_DIR", tmp_path)
    files = []
    for fid in results:
        p = tmp_path / f"{fid}.pdf"
        p.write_bytes(b"%PDF-1.4 not actually parsed")
        files.append({"file_id": fid, "path": str(p),
                      "content_type": "application/pdf"})

    async def fake_extract_many(owned, **kw):
        return {o["file_id"]: (results[o["file_id"]][0], results[o["file_id"]][1])
                for o in owned}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    return await S._extract_intake_evidence(files, owner_id="owner-1")


def _unusable_result():
    return _result(completeness=E.NONE, pages_with_text=0,
                   pages_text_untrusted=3,
                   error_code=E.ERR_UNEXTRACTABLE_TEXT_ENCODING)


async def test_unusable_text_never_reaches_the_analysis_prompt(monkeypatch, tmp_path):
    """THE POINT OF ALL OF THIS. Nine pages of glyph soup were being handed to
    the model as the client's evidence."""
    prompt, statuses = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_unusable_result(), "")})

    assert "Z}5i]w" not in prompt and "!!!!" not in prompt
    assert statuses[0]["status"] == "unextractable_encoding"
    assert statuses[0]["status"] not in ("readable", "partially_read")


async def test_the_prompt_names_it_as_not_analysable_rather_than_unreadable(
        monkeypatch, tmp_path):
    """"Could not be read" tells the client to re-upload a file that will fail
    identically. It belongs with the formats that need a different remedy."""
    prompt, _ = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_unusable_result(), "")})

    assert "NOT ANALYSABLE" in prompt
    assert "COULD NOT BE READ" not in prompt


async def test_the_prompt_forbids_the_model_from_asking_for_a_scan(
        monkeypatch, tmp_path):
    """The model writes what the client reads. If the instruction does not say
    so, it will offer the one remedy that cannot work."""
    prompt, _ = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_unusable_result(), "")})

    assert "do not suggest a scan or photo" in prompt.lower()
    assert "English translation" in prompt


async def test_a_mixed_document_keeps_its_readable_pages_and_reports_partial(
        monkeypatch, tmp_path):
    """Some pages decoded, some did not. What survived is real; the document is
    not whole, and the page counts must say so."""
    results = {"f1": (_result(completeness=E.PARTIAL_OR_UNCERTAIN,
                              pages_total=5, pages_attempted=5,
                              pages_with_text=3, pages_text_untrusted=2),
                      "genuine readable text from the pages that decoded")}

    prompt, statuses = await _run_intake(monkeypatch, tmp_path, results)

    assert statuses[0]["status"] == "partially_read"
    assert statuses[0]["pages_with_text"] == 3
    assert statuses[0]["pages_text_untrusted"] == 2
    assert "genuine readable text" in prompt, "readable pages were discarded too"


async def test_normal_english_extraction_is_still_readable(monkeypatch, tmp_path):
    prompt, statuses = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_result(), ENGLISH)})

    assert statuses[0]["status"] == "readable"
    assert ENGLISH in prompt


async def test_valid_unicode_urdu_is_still_readable(monkeypatch, tmp_path):
    """Never distrusted for not being English."""
    prompt, statuses = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_result(), URDU_UNICODE)})

    assert statuses[0]["status"] == "readable"
    assert URDU_UNICODE in prompt


async def test_evidence_coverage_counts_it_as_not_read(monkeypatch, tmp_path):
    """The snapshot written onto the case must not call this file read."""
    from app.services.evidence_coverage import (snapshot_from_statuses,
                                                validate_snapshot)

    _, statuses = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_unusable_result(), "")})

    snap = snapshot_from_statuses(statuses, uploaded_count=1)

    assert validate_snapshot(snap) is not None, "snapshot must stay well-formed"
    assert snap["files_total"] == 1
    assert snap["files_read_in_full"] == 0
    assert snap["files_partially_read"] == 0
    assert snap["files_omitted_for_length"] == 0
    assert snap["files_storage_only"] == 0, (
        "nothing is wrong with the FORMAT; this is a decoding failure")
    assert snap["files_not_read"] == 1
    assert snap["complete"] is False


async def test_the_mixed_document_warning_does_not_call_the_pages_blank(
        monkeypatch, tmp_path):
    """The warning travels inside the prompt beside the excerpt it qualifies.
    "Produced no text" would send the client back to re-upload the same
    born-digital file, which will decode exactly as badly the second time."""
    results = {"f1": (_result(completeness=E.PARTIAL_OR_UNCERTAIN,
                              pages_total=5, pages_attempted=5,
                              pages_with_text=3, pages_text_untrusted=2),
                      "genuine readable text")}

    prompt, _ = await _run_intake(monkeypatch, tmp_path, results)

    assert "WARNING" in prompt
    assert "2 of 5 pages use an unsupported legacy Urdu text encoding" in prompt
    assert "2 of 5 pages produced no text" not in prompt


def test_blank_pages_and_undecodable_pages_are_counted_separately():
    """One document can have both. Neither count may absorb the other."""
    from app.services.intake_service import _evidence_gap_sentence

    sentence = _evidence_gap_sentence(
        _result(completeness=E.PARTIAL_OR_UNCERTAIN, pages_total=10,
                pages_attempted=10, pages_with_text=4, pages_text_untrusted=3))

    assert "3 of 10 pages produced no text" in sentence   # 10 - 4 - 3
    assert "3 of 10 pages use an unsupported legacy Urdu text encoding" in sentence


def test_an_ordinary_partial_document_is_worded_exactly_as_before():
    """No undecodable pages: the existing sentence must be untouched."""
    from app.services.intake_service import _evidence_gap_sentence

    sentence = _evidence_gap_sentence(
        _result(completeness=E.PARTIAL_OR_UNCERTAIN, pages_total=10,
                pages_attempted=10, pages_with_text=7))

    assert "3 of 10 pages produced no text" in sentence
    assert "legacy" not in sentence


async def test_a_restored_session_preserves_the_status_and_the_counts(
        monkeypatch, tmp_path):
    """A refresh must not decay the state into "could not be read". The status
    and the page counters travel on the restored intake, not only on the live
    upload response."""
    from app.services.intake_service import _public_evidence

    _, statuses = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_unusable_result(), "")})

    restored = _public_evidence(
        [{"file_id": "f1", "filename": "statute.pdf",
          "content_type": "application/pdf", "path": "/srv/uploads/x.pdf"}],
        statuses)

    entry = restored[0]
    assert entry["extraction_status"] == "unextractable_encoding"
    assert entry["pages_text_untrusted"] == 3
    assert entry["completeness"] == E.NONE
    assert "path" not in entry, "the server path must never be disclosed"


async def test_no_raw_mojibake_reaches_the_restored_evidence_payload(
        monkeypatch, tmp_path):
    """Whatever the API hands a browser, the undecodable characters are not in
    it. The text was discarded at extraction and nothing downstream resurrects
    it."""
    from app.services.intake_service import _public_evidence

    _, statuses = await _run_intake(
        monkeypatch, tmp_path, {"f1": (_unusable_result(), "")})
    restored = _public_evidence(
        [{"file_id": "f1", "filename": "statute.pdf",
          "content_type": "application/pdf"}], statuses)

    blob = repr(statuses) + repr(restored)

    for fragment in ("Z}5i]w", "!!!!", "%^&*l1", "}[O5i#w"):
        assert fragment not in blob, f"raw extracted mojibake leaked: {fragment!r}"


def test_a_legacy_named_font_that_produced_readable_text_is_kept():
    """The font name is never enough on its own. If real language came back,
    the page is real whatever the font is called."""
    assert E._assess_text_layer(_noori_page(), ENGLISH) == E.TEXT_OK


def test_each_signal_alone_is_innocent():
    """The three conditions are load-bearing together, not individually."""
    # legacy font + no Urdu, but the text reads fine
    assert E._assess_text_layer(_noori_page(), ENGLISH) != E.TEXT_UNUSABLE
    # legacy font + incoherent, but the Urdu did arrive
    assert E._assess_text_layer(_noori_page(), URDU_UNICODE) != E.TEXT_UNUSABLE
    # no Urdu + incoherent, but no legacy font
    assert E._assess_text_layer(_ordinary_page(), MOJIBAKE) != E.TEXT_UNUSABLE


def test_a_subset_tag_that_spells_a_marker_is_not_a_false_match():
    """SURFACED BY MUTATION TESTING: removing the subset-strip changed nothing,
    because `/CXOYBI+NOORIN22` contains "NOORI" either way. This is the case
    that makes the strip load-bearing.

    PDF subset tags are six RANDOM uppercase letters, so one can legitimately
    spell `NOORIN` in front of an ordinary font. Matching it would condemn an
    English page on a coincidence.
    """
    page = _Page({
        "/F0": _Font({"/BaseFont": "/NOORIN+Arial"}),
        "/F1": _Font({"/BaseFont": "/NOORIC+TimesNewRomanPSMT"}),
    })

    assert E._normalised_basefont("/NOORIN+Arial") == "ARIAL"
    assert E._legacy_urdu_font_ratio(page) == 0.0
    assert E._assess_text_layer(page, MOJIBAKE) == E.TEXT_SUSPECT
