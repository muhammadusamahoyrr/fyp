"""The one builder whose input is markup rather than field values.

`P()` documents the hole this shape creates: reportlab's Paragraph parses a
markup language, so `<img src="...">` inside a paragraph OPENS THAT PATH ON THE
SERVER and embeds the file in the generated PDF. Every other builder is safe
because `P()` escapes field values by default. This one calls `P(..., raw=True)`,
which suppresses that escape — so the escaping is its own responsibility, and
these tests are what hold it to that.

The second concern is availability. A lawyer's contentEditable emits unbalanced
markup routinely, and reportlab raises on unbalanced markup. A draft that cannot
be rendered is a draft that cannot be filed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.pdf_generator import (
    _DRAFT_INLINE,
    _draft_blocks,
    extract_pdf_text,
    lawyer_draft,
)


def _render(tmp_path, monkeypatch, html: str, **fields) -> str:
    """Render a draft and return the text recovered from the real PDF."""
    import app.services.pdf_generator as gen
    monkeypatch.setattr(gen, "UPLOADS_DIR", tmp_path)
    out = lawyer_draft("draft-test", {"title": "A Draft", "body_html": html,
                                      **fields})
    assert Path(out).exists()
    text, status = extract_pdf_text(out)
    assert status == "ok"
    return text


# ── nothing from the draft reaches reportlab as markup ───────────────────────

def test_an_image_tag_cannot_open_a_file_on_the_server(tmp_path, monkeypatch):
    """THE test this builder exists to survive.

    reportlab's paraparser resolves <img src> against the filesystem. If the
    draft's markup were forwarded, a lawyer — or anything that could write into
    a draft — could read a server file into a PDF they then download.
    """
    html = '<p>before <img src="/etc/passwd"/> after</p>'

    # DROPPED, not escaped. `img` is in neither table, so handle_starttag emits
    # nothing for it and its attributes are never even read. Asserted on the
    # emitted markup rather than on the rendered text, because "the words either
    # side survived" would pass just as happily if the tag HAD been forwarded.
    for _kind, markup in _draft_blocks(html):
        assert "img" not in markup
        assert "passwd" not in markup

    text = _render(tmp_path, monkeypatch, html)
    assert "before" in text and "after" in text
    assert "passwd" not in text


def test_a_typed_out_tag_is_escaped_rather_than_interpreted(tmp_path, monkeypatch):
    """The other half of the defence, and the one that needs the escape.

    A lawyer who WRITES about a tag — or a draft whose sanitiser already escaped
    one — sends the characters through `handle_data`, not `handle_starttag`.
    Dropping unknown tags does nothing here: the text is already text, and
    without `_xml_escape` it would be handed to reportlab as markup and
    interpreted on the way out.
    """
    text = _render(tmp_path, monkeypatch,
                   "<p>the notice said &lt;img src=&quot;x&quot;&gt; verbatim</p>")
    assert "img" in text          # visible, as the words the lawyer typed
    assert "verbatim" in text


def test_an_unknown_tag_contributes_text_and_nothing_else(tmp_path, monkeypatch):
    text = _render(tmp_path, monkeypatch,
                   "<p>hello <script>alert(1)</script> world</p>")
    assert "hello" in text
    assert "world" in text


def test_a_bare_angle_bracket_does_not_break_generation(tmp_path, monkeypatch):
    """The failure `P()` was written for: an unclosed '<' in ordinary legal text
    ("the defendant paid <50% of what was owed") raised a paraparser ValueError
    and made the document impossible to generate."""
    text = _render(tmp_path, monkeypatch,
                   "<p>the defendant paid &lt;50% of what was owed</p>")
    assert "50%" in text


def test_only_the_allowlisted_tags_are_ever_emitted():
    # The allowlist IS the security boundary — it is the only place a tag can
    # enter the output. Everything in it must be a tag reportlab's paragraph
    # parser understands, or a legitimate draft fails to render.
    assert set(_DRAFT_INLINE.values()) <= {
        "b", "i", "u", "strike", "sub", "super"}


# ── a real editor's markup renders ───────────────────────────────────────────

def test_unbalanced_markup_still_renders(tmp_path, monkeypatch):
    # A contentEditable emits this constantly. reportlab raises on it.
    text = _render(tmp_path, monkeypatch, "<p><b>bold never closed</p><p>next</p>")
    assert "bold never closed" in text
    assert "next" in text


def test_a_tag_left_open_across_a_block_is_closed_and_reopened(tmp_path, monkeypatch):
    blocks = _draft_blocks("<p><b>one</p><p>two</b></p>")
    for _kind, markup in blocks:
        assert markup.count("<b>") == markup.count("</b>"), (
            f"unbalanced markup would fail to render: {markup!r}")


def test_crossed_tags_are_not_emitted_crossed():
    # <i><b>x</i></b> is what an editor produces and what reportlab refuses.
    for _kind, markup in _draft_blocks("<p><i><b>x</i></b></p>"):
        assert markup.count("<b>") == markup.count("</b>")
        assert markup.count("<i>") == markup.count("</i>")


def test_formatting_survives_where_it_can(tmp_path, monkeypatch):
    text = _render(tmp_path, monkeypatch,
                   "<h2>PRAYER</h2><p>It is <b>respectfully</b> prayed</p>"
                   "<ul><li>first relief</li><li>second relief</li></ul>")
    for expected in ("PRAYER", "respectfully", "first relief", "second relief"):
        assert expected in text


def test_a_font_tag_is_dropped_rather_than_forwarded(tmp_path, monkeypatch):
    # The draft sanitiser permits face and size. A filed document should carry
    # the document's typography, and forwarding a face name into reportlab's
    # font resolver is surface with no reason to exist.
    blocks = _draft_blocks('<p><font face="Comic Sans MS">text</font></p>')
    assert blocks
    for _kind, markup in blocks:
        assert "font" not in markup
        assert "Comic Sans" not in markup
    assert "text" in blocks[0][1]


# ── honest about what it is ──────────────────────────────────────────────────

def test_an_empty_draft_says_so(tmp_path, monkeypatch):
    # A page containing only a title reads as a rendering failure. A lawyer
    # pressing Save on a blank editor is a real outcome and deserves a sentence.
    text = _render(tmp_path, monkeypatch, "")
    assert "This draft is empty" in text


def test_no_statutory_completeness_is_claimed_for_free_prose():
    """The system does not know what instrument this is, so it must not check
    one. `check_pleading` returning `checked: false` is the correct answer, and
    the registry entry says so in words."""
    from app.services import pleading_rules, template_registry
    report = pleading_rules.check_pleading("lawyer_draft", {"body_html": "<p>x</p>"})
    assert report["checked"] is False
    assert "no statutory completeness check" in (
        template_registry.spec("lawyer_draft")["description"])
