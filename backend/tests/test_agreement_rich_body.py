"""The `html` agreement body format (2026-10-11).

A rich body is sanitised to a small allowlist, must already be canonical when
it is sent (so the creator signs exactly what they reviewed), and prints into
the executed PDF without any user text being parsed as markup. Plain-text
agreements are unchanged by all of it.
"""
from __future__ import annotations

from io import BytesIO

import pytest

from app.core.exceptions import AppValidationError
from app.services import agreement_html, agreement_service
from app.services.agreement_pdf import _rich_body
from app.services.pdf_generator import _styles


# ── sanitising ──────────────────────────────────────────────────────────────

def test_the_toolbar_formatting_survives():
    body = ('<h1>Lease</h1><p style="text-align:center"><b>Bold</b> <i>it</i> '
            '<u>u</u> <s>s</s></p><ul><li>one</li></ul><ol><li>two</li></ol>'
            '<blockquote>q</blockquote><hr><div>line<br>break</div>')
    assert agreement_html.sanitise(body) == body


@pytest.mark.parametrize("hostile, gone", [
    ('<p>x</p><script>alert(1)</script>', "alert"),
    ('<img src="file:///etc/passwd" onerror="alert(1)">', "img"),
    ('<a href="javascript:alert(1)">l</a>', "javascript"),
    ('<p onclick="steal()">x</p>', "onclick"),
    ('<p style="background:url(http://x/y)">x</p>', "url("),
    ('<iframe src="http://x"></iframe>', "iframe"),
    ('<style>p{display:none}</style><p>x</p>', "display"),
])
def test_anything_outside_the_allowlist_is_removed(hostile, gone):
    assert gone not in agreement_html.sanitise(hostile)


def test_only_alignment_survives_in_a_style():
    out = agreement_html.sanitise('<p style="text-align:right;color:red;font-size:40px">x</p>')
    assert out == '<p style="text-align:right">x</p>'


def test_sanitising_is_stable_under_a_second_pass():
    once = agreement_html.sanitise('<p>a &lt; b &amp; c<br>d</p><x-y>z</x-y><img src=x>')
    assert agreement_html.sanitise(once) == once


def test_visible_text_reads_the_words():
    assert agreement_html.visible_text("<p>Pay <b>Rs 5</b></p><p>&lt;now&gt;</p>") == "Pay Rs 5 <now>"
    assert agreement_html.visible_text("<p><br></p><hr>") == ""


# ── what is signed is what was reviewed ─────────────────────────────────────

def test_a_canonical_body_is_accepted_unchanged():
    body = agreement_service.preview_body("<p>Rent is <b>due</b></p>")["body_html"]
    assert agreement_service.canonical_html_or_refuse(body) == body


def test_a_body_sanitising_would_change_is_refused_not_cleaned():
    with pytest.raises(AppValidationError):
        agreement_service.canonical_html_or_refuse("<p>x</p><script>alert(1)</script>")


def test_an_empty_rich_body_is_refused():
    with pytest.raises(AppValidationError):
        agreement_service.canonical_html_or_refuse("<p><br></p>")


def test_preview_returns_the_canonical_form():
    out = agreement_service.preview_body('<p onclick="x()">Hi</p>\r\n<script>1</script>')
    assert out == {"body_html": "<p>Hi</p>\n", "has_text": True}


def test_plain_text_fingerprints_are_unchanged_and_html_differs():
    common = dict(title="T", body_sha256="d", parties=["u1"], case_id=None,
                  signature_data="s", consent=True)
    plain_default = agreement_service._send_fingerprint(**common)
    plain_named = agreement_service._send_fingerprint(**common, body_format="plain_text")
    rich = agreement_service._send_fingerprint(**common, body_format="html")
    assert plain_default == plain_named
    assert rich != plain_default


# ── the PDF ─────────────────────────────────────────────────────────────────

def _pdf_text(flowables) -> str:
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(flowables)
    return "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(buf.getvalue())).pages)


def test_the_rich_body_prints_its_words():
    text = _pdf_text(_rich_body(
        "<h2>Rent</h2><p>Pay <b>Rs 150,000</b> by the 5th.</p>"
        "<ol><li>First</li><li>Second</li></ol><ul><li>Point</li></ul><hr><p>End</p>",
        _styles()))
    for words in ("Rent", "Pay", "Rs 150,000", "1.", "First", "2.", "Second", "Point", "End"):
        assert words in text


def test_user_text_in_a_rich_body_is_printed_not_interpreted():
    # Escaped in the stored body, so it is text: it must print, and must not
    # open a file or break the parser.
    text = _pdf_text(_rich_body(
        "<p>if x &lt; 5 &amp; &lt;img src=\"/etc/passwd\"&gt; then</p>", _styles()))
    assert 'if x < 5 & <img src="/etc/passwd"> then' in text


def test_blocks_carry_alignment_lists_and_quotes():
    blocks = agreement_html.pdf_blocks(
        '<p style="text-align:center">c</p><ol><li>a</li><li>b</li></ol>'
        "<blockquote><p>q</p></blockquote>")
    assert blocks[0]["align"] == "center"
    assert [b["bullet"] for b in blocks[1:3]] == ["1.", "2."]
    assert blocks[3]["quote"] == 1


# ── colour, size, font, sub/sup and links (the wider toolbar) ───────────────

def test_span_styles_are_rebuilt_in_one_canonical_form():
    out = agreement_html.sanitise(
        '<p><span style="color: rgb(255, 0, 0); font-size: 18px; font-family: Arial, sans-serif; position:absolute">x</span></p>')
    assert out == '<p><span style="font-family:arial;font-size:18px;color:#ff0000">x</span></p>'
    assert agreement_html.sanitise(out) == out


@pytest.mark.parametrize("style", [
    "color:url(http://x/y)", "font-size:400px", "font-family:Comic Sans MS",
    "background:red", "color:expression(alert(1))",
])
def test_a_style_value_outside_the_patterns_is_dropped(style):
    assert agreement_html.sanitise(f'<span style="{style}">x</span>') == "<span>x</span>"


def test_only_web_and_mail_links_survive():
    out = agreement_html.sanitise(
        '<a href="https://x.pk/a" onclick="z()">ok</a><a href="mailto:a@b.pk">m</a>'
        '<a href="javascript:alert(1)">bad</a><a href="data:text/html,x">d</a>')
    assert 'href="https://x.pk/a"' in out and 'href="mailto:a@b.pk"' in out
    assert "javascript" not in out and "data:" not in out and "onclick" not in out


def test_sub_and_superscript_survive():
    body = "<p>H<sub>2</sub>O and x<sup>2</sup></p>"
    assert agreement_html.sanitise(body) == body


def test_the_pdf_carries_colour_size_links_and_scripts():
    blocks = agreement_html.pdf_blocks(
        '<p><span style="color:#ff0000;font-size:16px;font-family:courier new">r</span>'
        ' <a href="https://x.pk">l</a> H<sub>2</sub>O x<sup>2</sup></p>')
    markup = blocks[0]["markup"]
    assert '<font color="#ff0000" size="12.0" face="Courier">r</font>' in markup
    assert '<a href="https://x.pk"' in markup
    assert "<sub>2</sub>" in markup and "<super>2</super>" in markup
    text = _pdf_text(_rich_body(
        '<p><span style="color:#ff0000">Red</span> <a href="https://x.pk">link</a> H<sub>2</sub>O</p>',
        _styles()))
    assert "Red" in text and "link" in text and "H" in text
