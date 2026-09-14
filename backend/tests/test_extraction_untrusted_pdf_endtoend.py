"""The defect, driven through the real PDF extractor on real PDF bytes.

WHY THIS FILE EXISTS SEPARATELY FROM THE UNIT TESTS

`test_extraction_text_layer_trust.py` covers the classifier and the intake
mapping. Mutation testing showed that suite could not see the defect at all:
reverting the page loop to the original `if stripped:` rule, letting untrusted
pages still count as read, and dropping the terminal error code ALL survived it.
Every one of those breaks lives in the SEAM between the classifier and the
extraction pipeline, and nothing that hands `ExtractionResult` objects to the
intake layer by hand ever crosses that seam.

So these tests build actual PDF bytes and run `extract_pdf` over them.

WHAT THE SYNTHETIC PDF IS, AND WHAT IT IS NOT

It is a minimal born-digital PDF: a Type1 font with no `/ToUnicode` CMap and a
text-showing operator, which is structurally what an InPage/Noori Nastaliq
document is. The characters it draws are ASCII symbol soup, chosen so the
round-trip through pypdf is exact and deterministic on every machine.

It is NOT an Urdu fixture. It contains no Urdu, claims no transcription, and
carries no ground truth -- it is a PDF whose FONT METADATA is undecodable, which
is the only property under test here. The real Urdu files remain gitignored
local artefacts, used only for the separately reported local verification.
"""
from __future__ import annotations

import io

import pytest

from app.ai import extraction as E

#: A minimal but valid identity CMap, so the "fonts look normal" control is a
#: real `/ToUnicode` entry rather than a dangling reference.
_CMAP = (b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
         b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
         b"1 beginbfrange\n<00> <FF> <0000>\nendbfrange\n"
         b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend")

#: The legacy family the real documents are typeset in, and an ordinary one.
#: Which font a page declares is now the signal that decides whether its text
#: may be DISCARDED, so the builder takes it as a parameter.
NOORI_FONT = "NOORIN22"
ORDINARY_FONT = "TimesNewRomanPSMT"

_BACKSLASH = bytes([0x5C])


def _escape(text: str) -> bytes:
    raw = text.encode("latin-1", "replace")
    raw = raw.replace(_BACKSLASH, _BACKSLASH * 2)
    raw = raw.replace(b"(", _BACKSLASH + b"(")
    return raw.replace(b")", _BACKSLASH + b")")


def _build_pdf(pages: list[str], *, tounicode: bool,
               basefont: str = NOORI_FONT) -> bytes:
    """A real PDF: one Type1 font, one text operator per page, a valid xref."""
    objects: dict[int, bytes] = {}
    counter = [0]

    def add(body: bytes) -> int:
        counter[0] += 1
        objects[counter[0]] = body
        return counter[0]

    cmap_id = None
    if tounicode:
        cmap_id = add(b"<< /Length %d >>\nstream\n" % len(_CMAP)
                      + _CMAP + b"\nendstream")

    font_body = (b"<< /Type /Font /Subtype /Type1 /BaseFont /ABCDEF+"
                 + basefont.encode("ascii")
                 + b" /Encoding /WinAnsiEncoding")
    if cmap_id:
        font_body += b" /ToUnicode %d 0 R" % cmap_id
    font_id = add(font_body + b" >>")

    content_ids = []
    for text in pages:
        stream = b"BT /F1 12 Tf 72 720 Td (" + _escape(text) + b") Tj ET"
        content_ids.append(
            add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))

    # The page objects must name their parent, which is allocated after them.
    pages_id = counter[0] + len(content_ids) + 1
    kids = [add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792]"
                b" /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_id, font_id, cid)) for cid in content_ids]

    actual_pages_id = add(b"<< /Type /Pages /Kids ["
                          + b" ".join(b"%d 0 R" % k for k in kids)
                          + b"] /Count %d >>" % len(kids))
    assert actual_pages_id == pages_id, "page tree id was mispredicted"
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for oid in range(1, counter[0] + 1):
        offsets[oid] = out.tell()
        out.write(b"%d 0 obj\n" % oid + objects[oid] + b"\nendobj\n")
    xref_at = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (counter[0] + 1))
    for oid in range(1, counter[0] + 1):
        out.write(b"%010d 00000 n \n" % offsets[oid])
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (counter[0] + 1, catalog_id, xref_at))
    return out.getvalue()


#: Symbol soup whose letter-bearing tokens are mostly NOT letters -- the shape a
#: legacy custom-encoded font produces, at the length of a real page. MEASURED:
#: every real undecodable page carries at least 81 letter-bearing tokens, and
#: the assessor refuses to judge anything shorter. Deliberately meaningless.
_SOUP_TOKENS = ('Z}5i]w#@', '[O~2}q!', '}[O5i#w', '%^&*l1', ']q2~O[', '@#w]i5}Z',
                '~q[2O}', 'w#5i]Z', '}O[~q2', '!i5w#]', '2~O}[q', 'l1*&^%')
GLYPH_SOUP = " ".join(
    ['!!!!**', '$$4477', '9999', '1111', '((((']
    + [_SOUP_TOKENS[i % len(_SOUP_TOKENS)] for i in range(84)])

ENGLISH = (
    "The total fine of 1000 rupees only is imposed on the respondent today "
    "under section 302 of the Act, and the appeal shall lie to the High Court "
    "within thirty days of the date on which the order was communicated to the "
    "party aggrieved by it, failing which the right of appeal shall stand "
    "forfeited and the order shall become final for all purposes."
)


def _write(tmp_path, name, pages, *, tounicode=False, basefont=NOORI_FONT):
    path = tmp_path / name
    path.write_bytes(_build_pdf(pages, tounicode=tounicode, basefont=basefont))
    return path


# ══════════════════════════════════════════════════════════════════════════════

def test_an_undecodable_born_digital_pdf_is_not_reported_as_complete(tmp_path):
    """THE DEFECT. Nine such pages extracted, `completeness=complete`, zero
    usable characters, and the analysis was built on it."""
    result = E.extract_pdf(_write(tmp_path, "soup.pdf", [GLYPH_SOUP] * 4))

    assert result.completeness != E.COMPLETE
    assert result.completeness == E.NONE
    assert result.pages_with_text == 0, "undecodable pages are not read pages"
    assert result.pages_text_untrusted == 4
    assert result.error_code == E.ERR_UNEXTRACTABLE_TEXT_ENCODING


def test_the_undecodable_characters_are_discarded_not_returned(tmp_path):
    """`result.text` is what the intake prompt is built from. The glyphs must
    not survive into it -- this is the whole point of the fix."""
    path = _write(tmp_path, "soup.pdf", [GLYPH_SOUP] * 4)

    result = E.extract_pdf(path)
    via_dispatch = E.extract_file(str(path))

    assert result.text.strip() == ""
    assert "Z}5i]w" not in result.text and "!!!!" not in result.text
    # The public entry point the services actually call, not just the PDF arm.
    assert via_dispatch.text.strip() == ""
    assert via_dispatch.error_code == E.ERR_UNEXTRACTABLE_TEXT_ENCODING


def test_an_ordinary_english_pdf_still_reads_completely(tmp_path):
    """THE REGRESSION THAT MATTERS MOST. Every English statute in this
    repository must survive untouched."""
    result = E.extract_pdf(_write(tmp_path, "english.pdf", [ENGLISH] * 4,
                                  basefont=ORDINARY_FONT))

    assert result.completeness == E.COMPLETE
    assert result.pages_with_text == 4
    assert result.pages_text_untrusted == 0
    assert result.pages_text_suspect == 0
    assert result.error_code is None


def test_odd_text_in_an_ordinary_font_is_kept_and_only_marked_uncertain(tmp_path):
    """THE SEVEN ENGLISH PAGES, end to end. Without the legacy-font evidence
    the text is NOT discarded: it stays in the output, and only the claim that
    the document is complete is withdrawn."""
    result = E.extract_pdf(_write(tmp_path, "odd.pdf", [GLYPH_SOUP] * 4,
                                  basefont=ORDINARY_FONT))

    assert result.pages_text_untrusted == 0, "nothing may be thrown away here"
    assert result.pages_with_text == 4
    assert result.pages_text_suspect == 4
    assert "Z}5i]w" in result.text, "the text was kept, not deleted"
    assert result.completeness == E.PARTIAL_OR_UNCERTAIN
    assert result.error_code is None


def test_a_legacy_font_carrying_readable_text_is_not_discarded(tmp_path):
    """The font name alone never discards. If real language came back, the page
    is real whatever the font is called."""
    result = E.extract_pdf(_write(tmp_path, "oddfont.pdf", [ENGLISH] * 4,
                                  basefont=NOORI_FONT))

    assert result.pages_text_untrusted == 0
    assert result.completeness == E.COMPLETE
    assert ENGLISH.split()[0] in result.text


def test_a_mixed_pdf_keeps_its_readable_pages_and_reports_partial(tmp_path):
    """Two pages decoded and two did not. What survived is real, the document
    is not whole, and the counts must say exactly that."""
    result = E.extract_pdf(_write(
        tmp_path, "mixed.pdf", [ENGLISH, GLYPH_SOUP, ENGLISH, GLYPH_SOUP]))

    assert result.completeness == E.PARTIAL_OR_UNCERTAIN
    assert result.pages_total == 4
    assert result.pages_with_text == 2
    assert result.pages_text_untrusted == 2
    assert result.pages_failed == 0, "nothing failed; the glyphs do not decode"
    # Partial, not terminal: there is usable evidence here.
    assert result.error_code is None


def test_the_untrusted_pages_are_named_in_the_page_reports(tmp_path):
    result = E.extract_pdf(_write(
        tmp_path, "mixed.pdf", [ENGLISH, GLYPH_SOUP, ENGLISH, GLYPH_SOUP]))

    untrusted = [p for p in result.page_reports
                 if p.state == E.PAGE_TEXT_UNTRUSTED]

    assert [p.number for p in untrusted] == [2, 4], "wrong pages were blamed"
    assert all(p.error_code == E.ERR_UNEXTRACTABLE_TEXT_ENCODING
               for p in untrusted)


def test_the_counts_reach_the_serialised_result(tmp_path):
    """What the rest of the system actually reads."""
    result = E.extract_pdf(_write(
        tmp_path, "mixed.pdf", [ENGLISH, GLYPH_SOUP, ENGLISH, GLYPH_SOUP]))

    payload = result.as_dict()

    assert payload["pages_text_untrusted"] == 2
    assert payload["pages_with_text"] == 2
    assert payload["completeness"] == E.PARTIAL_OR_UNCERTAIN


def test_an_empty_pdf_is_unchanged_by_any_of_this(tmp_path):
    """"No text" is a different finding with a different remedy. It must not
    start reporting an encoding problem."""
    result = E.extract_pdf(_write(tmp_path, "blank.pdf", ["", ""]))

    assert result.pages_text_untrusted == 0
    assert result.error_code != E.ERR_UNEXTRACTABLE_TEXT_ENCODING
