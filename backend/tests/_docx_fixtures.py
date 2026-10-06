"""Synthetic DOCX packages written from raw WordprocessingML, for structure tests.

Every fixture is NEW text written here. No paragraph is copied from any real
or downloaded template: those stay outside the repository (copyright unclear).

`build(body, numbering=None, styles=None, extra_parts=None)` writes a minimal
but valid package that python-docx opens and Word would render: the body
XML goes inside <w:body>, numbering/styles inside their part roots.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
{extra}
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

DEFAULT_STYLES = """<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>"""


def p(text: str = "", *, style: str | None = None, num: tuple[str, int] | None = None,
      raw: str | None = None, ppr_extra: str = "") -> str:
    """One paragraph. `num=(numId, ilvl)` adds direct numbering; `raw` replaces the run."""
    ppr = ""
    if style or num or ppr_extra:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        if num:
            inner += f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>'
        ppr = f"<w:pPr>{inner}{ppr_extra}</w:pPr>"
    run = raw if raw is not None else (f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>' if text else "")
    return f"<w:p>{ppr}{run}</w:p>"


def lvl(ilvl: int, fmt: str, text: str, *, start: int = 1, extra: str = "") -> str:
    return (f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="{start}"/><w:numFmt w:val="{fmt}"/>'
            f'<w:lvlText w:val="{text}"/>{extra}</w:lvl>')


def abstract(aid: str, *levels: str, extra: str = "") -> str:
    return f'<w:abstractNum w:abstractNumId="{aid}">{extra}{"".join(levels)}</w:abstractNum>'


def num(nid: str, aid: str, overrides: str = "") -> str:
    return f'<w:num w:numId="{nid}"><w:abstractNumId w:val="{aid}"/>{overrides}</w:num>'


def tc(text: str = "", *, span: int = 1, vmerge: str | None = None, inner: str | None = None) -> str:
    props = ""
    if span > 1:
        props += f'<w:gridSpan w:val="{span}"/>'
    if vmerge is not None:
        props += '<w:vMerge w:val="restart"/>' if vmerge == "restart" else "<w:vMerge/>"
    content = inner if inner is not None else p(text)
    return f"<w:tc>{f'<w:tcPr>{props}</w:tcPr>' if props else ''}{content}</w:tc>"


def tr(*cells: str, grid_before: int = 0) -> str:
    trpr = f'<w:trPr><w:gridBefore w:val="{grid_before}"/></w:trPr>' if grid_before else ""
    return f"<w:tr>{trpr}{''.join(cells)}</w:tr>"


def tbl(*rows: str) -> str:
    return f"<w:tbl>{''.join(rows)}</w:tbl>"


def build(path: Path, body: str, *, numbering: str = "", styles: str = DEFAULT_STYLES,
          extra_parts: dict[str, str] | None = None) -> Path:
    extra_parts = extra_parts or {}
    overrides = "".join(
        f'<Override PartName="/{name}" ContentType="application/xml"/>' for name in extra_parts)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES.format(extra=overrides))
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>{body}</w:body></w:document>')
        z.writestr("word/numbering.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<w:numbering xmlns:w="{W_NS}">{numbering}</w:numbering>')
        z.writestr("word/styles.xml",
                   f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<w:styles xmlns:w="{W_NS}">{styles}</w:styles>')
        for name, xml in extra_parts.items():
            z.writestr(name, xml)
    path.write_bytes(buf.getvalue())
    return path


#: A short synthetic NDA with Word multilevel numbering: "%1." / "%1.%2" / "(%3)".
NDA_NUMBERING = (
    abstract("10", lvl(0, "decimal", "%1."), lvl(1, "decimal", "%1.%2"),
             lvl(2, "lowerLetter", "(%3)"))
    + num("1", "10"))

NDA_BODY = "".join([
    p("MUTUAL CONFIDENTIALITY AGREEMENT"),
    p("This agreement is made between Alpha Traders and Beta Studio."),
    p("Definitions", num=("1", 0)),
    p("Confidential Information means any non-public business information.", num=("1", 1)),
    p("Purpose means evaluating a possible design engagement.", num=("1", 1)),
    p("Obligations", num=("1", 0)),
    p("The Receiving Party shall keep Confidential Information secret.", num=("1", 1)),
    p("It shall not disclose it to any third party.", num=("1", 2)),
    p("It shall return all copies within seven days of a written demand.", num=("1", 2)),
    p("Term", num=("1", 0)),
    p("This agreement lasts for two years from the date of signing.", num=("1", 1)),
    p("Signed by both parties."),
])


def nda(path: Path) -> Path:
    return build(path, NDA_BODY, numbering=NDA_NUMBERING)
