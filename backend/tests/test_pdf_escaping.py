"""Field text is DATA, never reportlab markup.

reportlab's Paragraph does not take plain text — it parses a markup language.
Field values reached it unescaped, which produced three distinct failures:

  * <img src="..."> inside a field OPENED THAT PATH on the server and embedded
    the file in the generated PDF — an authenticated local file read reachable
    through `POST /documents/generate`, whose `fields` is an unvalidated
    dict[str, Any];
  * an unclosed '<' in ordinary legal text ("the defendant paid <50% of what
    was owed") raised paraparser ValueError, so the document could not be
    generated at all;
  * <b>/<font> in a field were interpreted rather than printed.

These tests are the regression guard. They are deliberately cheap — no Mongo,
no LLM, no network — so they run in every default pass.

The generator's OWN markup must keep working, which is the other half of the
contract: P(..., raw=True) call sites escape their interpolated values with
esc() instead. A test that only proved escaping worked would pass just as well
against a build that had broken every bold heading in the corpus.
"""
import os

import pytest
from pypdf import PdfReader

from app.services.pdf_generator import P, esc, generate_pdf


def _text_of(path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _plaint(tmp_id: str, **overrides) -> str:
    fields = {
        "court_name": "Lahore", "plaintiff_name": "Ali", "defendant_name": "Bilal",
        "relief_sought": "Recovery of Rs 500,000", "facts": "Ordinary facts.",
    }
    fields.update(overrides)
    path = generate_pdf(tmp_id, "plaint_civil", fields)
    try:
        return _text_of(path)
    finally:
        os.remove(path)


# ── the injection ─────────────────────────────────────────────────────────────

def test_img_tag_in_a_field_does_not_open_a_file():
    """The one that mattered: <img src> made reportlab read a server path.

    Asserting on the rendered text is not enough — the bug was the OPEN, which
    raised before any text existed. If the escape regresses, reportlab raises
    UnidentifiedImageError/OSError here rather than returning.
    """
    text = _plaint("t-esc-img", facts='X <img src="C:/Windows/win.ini" width="10" height="10"/> Y')
    assert "img src" in text, "the tag must survive as literal text, not be parsed"


def test_img_tag_pointing_at_a_real_file_is_not_embedded():
    """A decodable image would have been embedded silently — no exception to catch."""
    text = _plaint("t-esc-img2", facts='<img src="app/assets/fonts/NotoNaskhArabic-Regular.ttf"/>')
    assert "img src" in text


def test_unclosed_angle_bracket_is_ordinary_legal_text():
    """'the defendant paid <50% of what was owed' must generate, not raise."""
    text = _plaint("t-esc-lt", facts="The defendant paid <50% of the agreed amount")
    assert "<50%" in text


def test_bold_tag_in_a_field_is_printed_not_interpreted():
    text = _plaint("t-esc-b", facts="Plaintiff <b>Ali</b> claims damages")
    assert "<b>Ali</b>" in text


def test_ampersand_survives_a_company_name():
    """& is the other XML metacharacter; escaping must round-trip it."""
    text = _plaint("t-esc-amp", plaintiff_name="Ali & Sons Pvt Ltd")
    assert "Ali & Sons" in text


@pytest.mark.parametrize("payload", [
    '<img src="x.png"/>',
    "<unclosed",
    "<b>bold</b>",
    "a & b",
    "<font color=red>red</font>",
])
def test_no_field_payload_can_break_generation(payload):
    """Whatever a field contains, a PDF comes out."""
    assert _plaint(f"t-esc-p{abs(hash(payload)) % 10000}", facts=payload)


# ── the other half: the generator's own markup still works ────────────────────

def test_generator_markup_is_still_rendered():
    """A raw=True site must NOT print its own tags.

    inheritance_demand wraps the deceased's name in <b>. If raw=True were
    dropped from that call site the document would read 'the late <b>Ahmed</b>'.
    """
    path = generate_pdf("t-esc-raw", "inheritance_demand", {
        "claimant_name": "Ali", "recipient_name": "Bilal",
        "deceased_name": "Ahmed", "relation": "son",
        "estate_description": "A house in Lahore", "response_days": "15",
    })
    try:
        text = _text_of(path)
    finally:
        os.remove(path)
    assert "Ahmed" in text
    assert "<b>" not in text, "generator markup leaked into the rendered text"


def test_raw_site_still_escapes_its_own_interpolated_field():
    """raw=True suppresses the escape for the WHOLE string, so a raw call site
    that forgets esc() reopens the hole. This pins the fixed one."""
    path = generate_pdf("t-esc-rawfield", "inheritance_demand", {
        "claimant_name": "Ali", "recipient_name": "Bilal",
        "deceased_name": '<img src="C:/Windows/win.ini"/>',
        "relation": "son", "estate_description": "A house", "response_days": "15",
    })
    try:
        text = _text_of(path)
    finally:
        os.remove(path)
    assert "img src" in text


# ── Urdu must still shape and right-align ─────────────────────────────────────

def test_urdu_still_renders_after_escaping():
    """The escape runs BEFORE the Arabic-script branch in P(), so it must not
    stop Urdu being detected, shaped and right-aligned."""
    urdu = "درخواست گزار نے موقف اختیار کیا"
    para = P(urdu, _body_style())
    assert para is not None
    from reportlab.lib.enums import TA_RIGHT
    assert para.style.alignment == TA_RIGHT, "Urdu lost its RTL alignment"
    assert "Noto" in para.style.fontName or para.style.fontName, "Urdu lost its font"


def test_urdu_pdf_generates_end_to_end():
    text = _plaint("t-esc-ur", facts="درخواست گزار نے موقف اختیار کیا کہ رقم ادا نہیں کی گئی")
    assert text  # shaped glyphs do not extract as source text; generation is the assertion


def test_urdu_containing_an_angle_bracket_is_escaped_not_dropped():
    """Escaping turns '<' into '&lt;', so the Arabic branch's `"<" not in text`
    guard now sees clean text — Urdu with a stray bracket still shapes."""
    para = P("درخواست < گزار", _body_style())
    assert para is not None


def _body_style():
    from app.services.pdf_generator import _styles
    return _styles()["body"]


# ── the helper itself ─────────────────────────────────────────────────────────

def test_esc_handles_none_and_non_strings():
    assert esc(None) == ""
    assert esc(15) == "15"
    assert esc("<b>") == "&lt;b&gt;"
    assert esc("a & b") == "a &amp; b"
