"""Rich agreement bodies: the ``html`` body format (2026-10-11).

Until now every agreement body was plain text (``body_format: "plain_text"``),
and that note in ``agreement_service`` explains why nh3 was NOT run over it:
sanitising plain text as HTML rewrites it. A rich body is a different declared
format, not a reinterpretation of old rows -- exactly the door that note left
open. Plain-text agreements are untouched by anything here.

WHAT THE SIGNER SEES IS WHAT IS HASHED
--------------------------------------
Sanitising can still change markup. So the server does not sanitise silently on
send: the builder asks ``preview`` for the canonical form, shows THAT at Review,
and sends it back. On send the body must already be canonical --
``sanitise(body) == body`` -- or the send is refused. The output here is stable
under a second pass, so a body that came from ``preview`` always passes, and the
text that is hashed and signed is byte-for-byte the text the creator reviewed.

WHAT IS ALLOWED
---------------
Only what the builder's toolbar can produce: paragraphs and headings, bold,
italic, underline, strikethrough, sub- and superscript, lists, a quote, a
divider, line breaks, alignment, a text colour, a font size, one of four font
families, and a link (http, https or mailto). Every ``style`` is REBUILT from
those few properties with values checked against a pattern, never passed
through -- so no url(), no expression(), no positioning, nothing that fetches
or runs. No images, classes, ids or scripts. The same allowlist bounds what
the PDF renderer below has to understand.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

import nh3

ALLOWED_TAGS = frozenset({
    "p", "div", "br", "h1", "h2", "h3",
    "strong", "b", "em", "i", "u", "s", "strike", "sub", "sup", "span", "a",
    "ul", "ol", "li", "blockquote", "hr",
})
_ALIGNABLE = ("p", "div", "h1", "h2", "h3", "li", "blockquote")
_ATTRIBUTES = {**{tag: {"style"} for tag in _ALIGNABLE}, "span": {"style"}, "a": {"href"}}

# The font families the toolbar offers, by the name it writes.
FONT_FAMILIES = {
    "georgia": "serif", "times new roman": "serif", "garamond": "serif",
    "arial": "sans", "verdana": "sans", "tahoma": "sans",
    "trebuchet ms": "sans", "calibri": "sans",
    "courier new": "mono",
}
_COLOR = re.compile(r"^(#[0-9a-f]{3}|#[0-9a-f]{6}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))$", re.I)
_SIZE = re.compile(r"^(\d{1,2}(?:\.\d+)?)px$", re.I)
_ALIGN_VALUES = {"left", "center", "right", "justify"}
_URL = re.compile(r"^(https?://|mailto:)[^\s\"'<>]+$", re.I)


def _canonical_colour(value: str) -> str | None:
    if not _COLOR.match(value):
        return None
    if value.lower().startswith("rgb"):
        parts = [int(n) for n in re.findall(r"\d+", value)]
        if any(n > 255 for n in parts):
            return None
        return "#" + "".join(f"{n:02x}" for n in parts)
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    return value.lower()


def _canonical_family(value: str) -> str | None:
    first = value.split(",")[0].strip().strip("'\"").lower()
    return first if first in FONT_FAMILIES else None


def _canonical_style(tag: str, raw: str) -> str | None:
    """Only the allowed properties, with valid values, in a fixed order and
    form -- so the result is the same however the browser wrote it."""
    found = {}
    for decl in raw.split(";"):
        if ":" not in decl:
            continue
        prop, value = (x.strip() for x in decl.split(":", 1))
        prop = prop.lower()
        if prop == "text-align" and tag in _ALIGNABLE and value.lower() in _ALIGN_VALUES:
            found["text-align"] = value.lower()
        elif prop == "color" and tag == "span":
            colour = _canonical_colour(value)
            if colour:
                found["color"] = colour
        elif prop == "font-size" and tag == "span":
            m = _SIZE.match(value)
            if m and 8 <= float(m.group(1)) <= 48:
                found["font-size"] = f"{int(round(float(m.group(1))))}px"
        elif prop == "font-family" and tag == "span":
            family = _canonical_family(value)
            if family:
                found["font-family"] = family
    order = ("text-align", "font-family", "font-size", "color")
    out = ";".join(f"{k}:{found[k]}" for k in order if k in found)
    return out or None


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    if attr == "style":
        return _canonical_style(tag, value or "")
    if attr == "href":
        return value if _URL.match((value or "").strip()) else None
    return value


def sanitise(body: str) -> str:
    """The canonical, safe form of a rich body. Idempotent."""
    return nh3.clean(
        body or "",
        tags=set(ALLOWED_TAGS),
        attributes=_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes={"http", "https", "mailto"},
        # A <script> or <style> is removed WITH its content, not unwrapped
        # into visible text.
        clean_content_tags={"script", "style"},
        link_rel=None,
        strip_comments=True,
    )


_TAG = re.compile(r"<[^>]*>")


def visible_text(body: str) -> str:
    """The words a reader would see -- for emptiness checks, never for display."""
    return " ".join(html.unescape(_TAG.sub(" ", body or "")).split())


# ── PDF ──────────────────────────────────────────────────────────────────────

_INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u",
           "s": "strike", "strike": "strike", "sub": "sub", "sup": "super"}
_BLOCKS = {"p", "div", "h1", "h2", "h3", "li", "blockquote"}
# The PDF has only the three standard faces; each family maps to its kind.
_PDF_FACES = {"serif": "Times-Roman", "sans": "Helvetica", "mono": "Courier"}


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _style_map(style: str) -> dict:
    out = {}
    for decl in (style or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


class _BlockReader(HTMLParser):
    """Turns a SANITISED body into blocks of reportlab markup.

    Every piece of text is escaped here, and every attribute this class emits
    is one it built itself from a value the sanitiser already checked, so the
    result is safe to hand to reportlab with ``raw=True``.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.cur: dict | None = None
        self.lists: list[list] = []      # [kind, counter]
        self.inline: list[tuple] = []    # (html tag, opening markup, closing markup)
        self.quote = 0

    def _open(self, kind: str, align: str | None = None, bullet: str | None = None):
        self._close()
        self.cur = {"kind": kind, "align": align, "bullet": bullet,
                    "depth": len(self.lists), "quote": self.quote,
                    "parts": [o for _, o, _ in self.inline]}

    def _close(self):
        if self.cur is None:
            return
        parts = self.cur["parts"] + [c for _, _, c in reversed(self.inline)]
        markup = "".join(parts)
        if _TAG.sub("", markup).strip() or self.cur["bullet"]:
            self.cur["markup"] = markup
            self.blocks.append(self.cur)
        self.cur = None

    def _ensure(self):
        if self.cur is None:
            self._open("quote" if self.quote else "p")

    def _push(self, tag: str, opening: str, closing: str):
        self._ensure()
        self.cur["parts"].append(opening)
        self.inline.append((tag, opening, closing))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = _style_map(attrs.get("style") or "")
        align = style.get("text-align")
        if tag in ("ul", "ol"):
            self._close()
            self.lists.append([tag, 0])
        elif tag == "li":
            kind, n = self.lists[-1] if self.lists else ("ul", 0)
            if self.lists:
                self.lists[-1][1] = n + 1
            self._open("li", align, "•" if kind == "ul" else f"{n + 1}.")
        elif tag == "blockquote":
            self._close()
            self.quote += 1
        elif tag in _BLOCKS:
            self._open(tag if tag in ("h1", "h2", "h3") else ("quote" if self.quote else "p"), align)
        elif tag == "br":
            self._ensure()
            self.cur["parts"].append("<br/>")
        elif tag == "hr":
            self._close()
            self.blocks.append({"kind": "hr"})
        elif tag in _INLINE:
            name = _INLINE[tag]
            self._push(tag, f"<{name}>", f"</{name}>")
        elif tag == "span":
            font = []
            if style.get("color") and _COLOR.match(style["color"]):
                font.append(f'color="{_xml(style["color"])}"')
            m = _SIZE.match(style.get("font-size") or "")
            if m:
                font.append(f'size="{round(float(m.group(1)) * 0.75, 1)}"')
            face = _PDF_FACES.get(FONT_FAMILIES.get((style.get("font-family") or "").lower(), ""))
            if face:
                font.append(f'face="{face}"')
            if font:
                self._push(tag, f"<font {' '.join(font)}>", "</font>")
            else:
                self._push(tag, "", "")
        elif tag == "a":
            href = attrs.get("href") or ""
            if _URL.match(href):
                self._push(tag, f'<a href="{_xml(href)}" color="#1a5fb4">', "</a>")
            else:
                self._push(tag, "", "")

    def handle_endtag(self, tag):
        if tag in _INLINE or tag in ("span", "a"):
            if any(t == tag for t, _, _ in self.inline):
                while self.inline:
                    t, _, closing = self.inline.pop()
                    if self.cur is not None:
                        self.cur["parts"].append(closing)
                    if t == tag:
                        break
        elif tag in ("ul", "ol"):
            self._close()
            if self.lists:
                self.lists.pop()
        elif tag == "blockquote":
            self._close()
            self.quote = max(0, self.quote - 1)
        elif tag in _BLOCKS:
            self._close()

    def handle_data(self, data):
        text = data.replace("\n", " ")
        if not text.strip() and self.cur is None:
            return
        self._ensure()
        self.cur["parts"].append(_xml(text))


def pdf_blocks(body: str) -> list[dict]:
    """The body as a list of blocks: ``{"kind", "markup", "align", "bullet",
    "depth", "quote"}`` or ``{"kind": "hr"}``. The input is sanitised again
    first, so a caller can never hand this unchecked markup."""
    reader = _BlockReader()
    reader.feed(sanitise(body))
    reader.close()
    reader._close()
    return reader.blocks
