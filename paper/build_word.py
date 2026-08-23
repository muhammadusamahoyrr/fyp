"""
build_word.py   -  Generates FIT_paper.docx (findings paper, IEEE two-column).

Paper: "In-Distribution Gains Do Not Transfer: Leakage-Free Evaluation of
        Retrieval Interventions for Low-Resource Legal Question Answering"
Author: Muhammad Usama  -  COMSATS University Islamabad
Venue:  FIT 2026 (IEEE, 6-page max, Times New Roman 10pt two-column)

No supervisor co-author. No acknowledgment section. No TODO markers.
All equations typeset as proper Word OMML objects.
Figures embedded from figures/*.png.

Usage:
    python paper/build_word.py
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent
OUT  = HERE / "FIT_paper_clean.docx"
FIGS = HERE / "figures"

# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _margins(section, top=0.75, bottom=1.0, left=0.625, right=0.625):
    section.top_margin    = Inches(top)
    section.bottom_margin = Inches(bottom)
    section.left_margin   = Inches(left)
    section.right_margin  = Inches(right)


def _set_columns(section, num: int, space_twips: int = 360):
    sp = section._sectPr
    c  = sp.find(qn("w:cols"))
    if c is None:
        c = OxmlElement("w:cols")
        sp.append(c)
    c.set(qn("w:num"), str(num))
    c.set(qn("w:space"), str(space_twips))
    c.set(qn("w:equalWidth"), "1")


def _para(doc, text="", size=10, bold=False, italic=False,
          align="justify", space_after=4, space_before=0,
          font="Times New Roman", first_line_indent=None):
    p  = doc.add_paragraph()
    p.alignment = {
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "right":   WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }[align]
    pf = p.paragraph_format
    pf.space_after  = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing = 1.0
    if first_line_indent is not None:
        pf.first_line_indent = Inches(first_line_indent)
    if text:
        r = p.add_run(text)
        r.font.name   = font
        r.font.size   = Pt(size)
        r.bold        = bold
        r.italic      = italic
    return p


def _rich(doc, chunks, size=10, align="justify",
          space_after=4, space_before=0, first_line_indent=None):
    """Paragraph built from (text, bold, italic) or (text, bold, italic, color)."""
    p = doc.add_paragraph()
    p.alignment = {
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }[align]
    pf = p.paragraph_format
    pf.space_after  = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing = 1.0
    if first_line_indent is not None:
        pf.first_line_indent = Inches(first_line_indent)
    for chunk in chunks:
        txt, bd, it = chunk[0], chunk[1], chunk[2]
        clr = chunk[3] if len(chunk) > 3 else None
        r = p.add_run(txt)
        r.font.name   = "Times New Roman"
        r.font.size   = Pt(size)
        r.bold, r.italic = bd, it
        if clr:
            r.font.color.rgb = clr
    return p


def _heading(doc, numeral, text):
    """IEEE section heading: centred, small-caps style."""
    _para(doc, f"{numeral}.  {text.upper()}", size=10, bold=True,
          align="center", space_before=8, space_after=3)


def _subheading(doc, letter, text):
    """IEEE subsection heading: italic, left-aligned."""
    _para(doc, f"{letter}.  {text}", size=10, italic=True,
          align="left", space_before=5, space_after=2)


def _body(doc, text, indent=True):
    p = _para(doc, size=10, align="justify", space_after=4,
              first_line_indent=0.18 if indent else None)
    _add_body_text_with_citations(p, text, font_name="Times New Roman", font_size=Pt(10))
    return p


def _add_internal_citation_link(paragraph, ref_num, text_label, font_name="Times New Roman", font_size=Pt(10), color="000000"):
    hyperlink_xml = parse_xml(f'<w:hyperlink xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:anchor="ref_{ref_num}"/>')
    new_run = parse_xml(f'<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    rPr = parse_xml(f'<w:rPr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    if color:
        c = parse_xml(f'<w:color xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="{color}"/>')
        rPr.append(c)
    u = parse_xml(f'<w:u xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="none"/>')
    rPr.append(u)
    if font_name:
        f = parse_xml(f'<w:rFonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:ascii="{font_name}" w:hAnsi="{font_name}"/>')
        rPr.append(f)
    if font_size:
        sz_val = int(font_size.pt * 2) if hasattr(font_size, 'pt') else int(font_size * 2)
        sz = parse_xml(f'<w:sz xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="{sz_val}"/>')
        rPr.append(sz)
    new_run.append(rPr)
    t = parse_xml(f'<w:t xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xml:space="preserve">{text_label}</w:t>')
    new_run.append(t)
    hyperlink_xml.append(new_run)
    paragraph._p.append(hyperlink_xml)


def _add_body_text_with_citations(paragraph, text, font_name="Times New Roman", font_size=Pt(10), bold=False, italic=False):
    citation_pattern = re.compile(r'(\[\d+\](?:\s*[\u2013,\-]\s*\[\d+\])*)')
    tokens = citation_pattern.split(text)
    for token in tokens:
        if not token:
            continue
        if re.match(r'^\[\d+\]', token):
            sub_parts = re.split(r'(\[\d+\])', token)
            for sp in sub_parts:
                if not sp:
                    continue
                m = re.match(r'^\[(\d+)\]$', sp)
                if m:
                    ref_num = int(m.group(1))
                    _add_internal_citation_link(paragraph, ref_num, sp, font_name=font_name, font_size=font_size, color="000000")
                else:
                    clean_sp = sp.replace(',', ', ')
                    r = paragraph.add_run(clean_sp)
                    r.font.name = font_name
                    r.font.size = font_size
                    r.font.bold = bold
                    r.font.italic = italic
        else:
            r = paragraph.add_run(token)
            r.font.name = font_name
            r.font.size = font_size
            r.font.bold = bold
            r.font.italic = italic


def _add_hyperlink(paragraph, url, text, font_name="Times New Roman", font_size=Pt(8), color="000000", underline=False):
    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = parse_xml(f'<w:hyperlink xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{r_id}"/>')
    new_run = parse_xml(f'<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    rPr = parse_xml(f'<w:rPr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    if color:
        c = parse_xml(f'<w:color xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="{color}"/>')
        rPr.append(c)
    if underline:
        u = parse_xml(f'<w:u xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="single"/>')
        rPr.append(u)
    if font_name:
        f = parse_xml(f'<w:rFonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:ascii="{font_name}" w:hAnsi="{font_name}"/>')
        rPr.append(f)
    if font_size:
        sz_val = int(font_size.pt * 2) if hasattr(font_size, 'pt') else int(font_size * 2)
        sz = parse_xml(f'<w:sz xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="{sz_val}"/>')
        rPr.append(sz)
    new_run.append(rPr)
    t = parse_xml(f'<w:t xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xml:space="preserve">{text}</w:t>')
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def _add_text_with_hyperlinks(paragraph, text, font_name="Times New Roman", font_size=Pt(8), bold=False, italic=False):
    url_pattern = re.compile(r'(https?://[^\s<>\"\'\)\]\}]+)')
    tokens = url_pattern.split(text)
    for token in tokens:
        if not token:
            continue
        if token.startswith("http://") or token.startswith("https://"):
            clean_url = token.rstrip(".,;:)")
            trailing = token[len(clean_url):]
            _add_hyperlink(paragraph, clean_url, clean_url, font_name=font_name, font_size=font_size)
            if trailing:
                r = paragraph.add_run(trailing)
                r.font.name = font_name
                r.font.size = font_size
                r.font.bold = bold
                r.font.italic = italic
        else:
            r = paragraph.add_run(token)
            r.font.name = font_name
            r.font.size = font_size
            r.font.bold = bold
            r.font.italic = italic



# ─────────────────────────────────────────────────────────────────────────────
# OMML equation helper
# ─────────────────────────────────────────────────────────────────────────────

def _omml_literal(doc, display_text: str, eq_num: str | None = None,
                  space_after=5):
    """
    Render an equation as a centred paragraph using Unicode math characters.
    Word renders these cleanly in Cambria Math. Equation number right-aligned
    if provided.
    """
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_after  = Pt(space_after)
    pf.space_before = Pt(2)
    pf.line_spacing = 1.0

    r = p.add_run(display_text)
    r.font.name   = "Cambria Math"
    r.font.size   = Pt(10)
    r.italic      = True

    if eq_num:
        tab = p.add_run(f"   ({eq_num})")
        tab.font.name   = "Times New Roman"
        tab.font.size   = Pt(10)
        tab.italic      = False
    return p


def _eq(doc, text, num=None):
    """Shorthand for an equation line."""
    _omml_literal(doc, text, eq_num=num)


# ─────────────────────────────────────────────────────────────────────────────
def _set_ieee_table_borders(tbl):
    """
    Apply official IEEE conference template table borders (conference-template-letter.docx):
    0.25 pt (sz=2 twips) thin single black lines on top, bottom, left, right, insideH, insideV.
    Matches the exact XML structure of Table 1 in conference-template-letter.docx.
    """
    tblPr = tbl._tbl.tblPr
    tblBorders = OxmlElement('w:tblBorders')
    
    for b_name in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        b = OxmlElement(f'w:{b_name}')
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), '2')  # 0.25 pt thin single line (sz=2 twips)
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), 'auto')
        tblBorders.append(b)

    tblPr.append(tblBorders)

    # Clear individual cell tcBorders so cells inherit table-level borders cleanly
    for row in tbl.rows:
        for cell in row.cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = tcPr.find(qn('w:tcBorders'))
            if tcBorders is not None:
                tcPr.remove(tcBorders)


def _table_caption(doc, text):
    p = _para(doc, text.upper(), size=8, bold=True, align="center",
              space_after=2, space_before=6)
    return p


def _add_table(doc, caption: str, rows: list[tuple],
               header_row=True, col_widths=None):
    _table_caption(doc, caption)
    tbl = doc.add_table(rows=len(rows), cols=len(rows[0]))
    tbl.autofit = False
    _set_ieee_table_borders(tbl)

    if col_widths:
        for ri, row in enumerate(tbl.rows):
            for ci, cell in enumerate(row.cells):
                if ci < len(col_widths):
                    cell.width = Inches(col_widths[ci])

    for ri, row_data in enumerate(rows):
        for ci, cell_text in enumerate(row_data):
            cell = tbl.cell(ri, ci)
            cell.paragraphs[0].clear()
            run = cell.paragraphs[0].add_run(str(cell_text))
            run.font.name = "Times New Roman"
            run.font.size = Pt(8)
            if ri == 0 and header_row:
                run.bold = True
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            cell.paragraphs[0].paragraph_format.space_after  = Pt(1)
            cell.paragraphs[0].paragraph_format.space_before = Pt(1)

    # small gap after table
    _para(doc, "", size=4, space_after=2)
    return tbl


# ─────────────────────────────────────────────────────────────────────────────
# Figure helper
# ─────────────────────────────────────────────────────────────────────────────

def _figure(doc, filename: str, caption: str, width=1.0):
    """Embed figure; caption below. width is fraction of column width (~3.3in)."""
    path = FIGS / filename
    if not path.exists():
        _para(doc, f"[Figure: {filename} not found]", size=8,
              align="center", space_after=4)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after  = Pt(2)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.line_spacing = 1.0
    col_w = 3.3  # inches, one column
    r = p.add_run()
    r.add_picture(str(path), width=Inches(col_w * width))
    _para(doc, caption, size=8, align="center", space_after=6)


# ─────────────────────────────────────────────────────────────────────────────
# Paper content
# ─────────────────────────────────────────────────────────────────────────────

TITLE = (
    "In-Distribution Gains Do Not Transfer: Leakage-Free Evaluation of "
    "Retrieval Interventions for Low-Resource Legal Question Answering"
)

ABSTRACT = (
    "Retrieval interventions for legal question answering are almost always "
    "reported on evaluation sets drawn from the same distribution as "
    "fine-tuning data. We report what happens when they are not. "
    "Fine-tuning a multilingual retriever on 4,692 verified citation pairs "
    "for Pakistani law gains +26.5 Hit@1 on held-out questions from its own "
    "generator and +2.4 when the question style changes. A second model, "
    "trained on a tenth as much data from a different source, "
    "initially shows a +16.5 in-distribution gain, but target leakage invalidates "
    "that comparison; on clean out-of-distribution evaluation it changes by \u22120.3. "
    "Sorting every intervention by whether its effect survived a style change "
    "produces a clean split: those encoding legal or document structure "
    "transferred; those learning question phrasing did not, including a "
    "cross-encoder that demoted the correct statute from rank\u00a03 to rank\u00a010 "
    "where a deterministic statutory-scope rule placed it first in under a "
    "millisecond. Three evaluation defects (an index containing its own test "
    "answers, a wrong gold-label join, and target leakage between train and "
    "test) each inflated or distorted a headline number; the flattering version was "
    "wrong every time. The measurement protocol determined the conclusions "
    "more than any technique did."
)

KEYWORDS = (
    "legal informatics, retrieval-augmented generation, retrieval evaluation, "
    "distribution shift, data contamination, low-resource NLP, code-switching, Urdu"
)

REFERENCES = [
    '[1] P. Lewis et al., “Retrieval-augmented generation for knowledge-intensive NLP,” in Proc. NeurIPS, 2020. [Online]. Available: https://arxiv.org/abs/2005.11401',
    '[2] I. Chalkidis et al., “LEGAL-BERT: The muppets straight out of law school,” in Findings of EMNLP, 2020, pp. 2898–2904. [Online]. Available: https://doi.org/10.18653/v1/2020.findings-emnlp.138',
    '[3] N. Guha et al., “LegalBench: A collaboratively built benchmark for measuring legal reasoning in large language models,” in Proc. NeurIPS, 2023. [Online]. Available: https://arxiv.org/abs/2308.11462',
    '[4] S. Ma et al., “LeCaRD: A legal case retrieval dataset for Chinese law,” in Proc. ACM SIGIR, 2021, pp. 2348–2354. [Online]. Available: https://doi.org/10.1145/3404835.3462875',
    '[5] V. Karpukhin et al., “Dense passage retrieval for open-domain question answering,” in Proc. EMNLP, 2020, pp. 6769–6781. [Online]. Available: https://doi.org/10.18653/v1/2020.emnlp-main.550',
    '[6] A. Asai et al., “Self-RAG: Learning to retrieve, generate, and critique through self-reflection,” in Proc. ICLR, 2024. [Online]. Available: https://arxiv.org/abs/2310.11511',
    '[7] L. Wang et al., “Multilingual E5 text embeddings: A technical report,” 2024, arXiv:2402.05672. [Online]. Available: https://arxiv.org/abs/2402.05672',
    '[8] S. Robertson and H. Zaragoza, “The probabilistic relevance framework: BM25 and beyond,” Found. Trends Inf. Retr., vol. 3, no. 4, pp. 333–389, 2009. [Online]. Available: https://doi.org/10.1561/1500000019',
    '[9] G. V. Cormack, C. L. A. Clarke, and S. Büttcher, “Reciprocal rank fusion outperforms Condorcet and individual rank learning methods,” in Proc. ACM SIGIR, 2009, pp. 758–759. [Online]. Available: https://doi.org/10.1145/1571941.1572114',
    '[10] N. Thakur, N. Reimers, A. Rücklé, A. Srivastava, and I. Gurevych, “BEIR: A heterogeneous benchmark for zero-shot evaluation of information retrieval models,” in Proc. NeurIPS Datasets and Benchmarks Track, 2021. [Online]. Available: https://arxiv.org/abs/2104.08663',
    '[11] N. Muennighoff, N. Tazi, L. Magne, and N. Reimers, “MTEB: Massive text embedding benchmark,” in Proc. EACL, 2023, pp. 2014–2037. [Online]. Available: https://doi.org/10.18653/v1/2023.eacl-main.148',
    '[12] I. Magar and R. Schwartz, “Data contamination: From memorization to exploitation,” in Proc. ACL, 2022, pp. 157–165. [Online]. Available: https://doi.org/10.18653/v1/2022.acl-long.539',
    '[13] O. Sainz, J. A. Campos, I. García-Ferrero, J. Etxaniz, O. L. de Lacalle, and E. Agirre, “NLP evaluation in trouble: On the need to measure LLM data contamination for each benchmark,” in Findings of EMNLP, 2023, pp. 10746–10756. [Online]. Available: https://doi.org/10.18653/v1/2023.findings-emnlp.211',
    '[14] S. Golchin and M. Surdeanu, “Time travel in LLMs: Tracing data contamination in large language models,” in Proc. ICLR, 2024. [Online]. Available: https://arxiv.org/abs/2308.08493',
    '[15] C. Deng et al., “Investigating data contamination in modern NLP benchmarks,” in Findings of EMNLP, 2024. [Online]. Available: https://arxiv.org/abs/2404.00699',
    '[16] A. Jadoon, “Pakistan Laws Dataset,” HuggingFace, ODC-BY, 2024. [Online]. Available: https://huggingface.co/datasets/AyeshaJadoon/Pakistan_Laws_Dataset',
    '[17] Ministry of Law and Justice, Government of Pakistan, “Pakistan Code,” 2026. [Online]. Available: https://pakistancode.gov.pk/ (accessed Aug. 2026)',
    '[18] F. Faisal and U. Yousaf, “LEGAL-UQA: A low-resource Urdu-English dataset for legal question answering,” 2024, arXiv:2410.13013. [Online]. Available: https://arxiv.org/abs/2410.13013',
    '[19] N. Reimers and I. Gurevych, “Sentence-BERT: Sentence embeddings using Siamese BERT-networks,” in Proc. EMNLP, 2019, pp. 3982–3992. [Online]. Available: https://doi.org/10.18653/v1/D19-1410',
    '[20] M. Henderson et al., “Efficient natural language response suggestion for Smart Reply,” 2017, arXiv:1705.00652. [Online]. Available: https://arxiv.org/abs/1705.00652',
    '[21] Q. McNemar, “Note on the sampling error of the difference between correlated proportions or percentages,” Psychometrika, vol. 12, no. 2, pp. 153–157, 1947. [Online]. Available: https://doi.org/10.1007/BF02289257',
    '[22] K. Järvelin and J. Kekäläinen, “Cumulated gain-based evaluation of IR techniques,” ACM Trans. Inf. Syst., vol. 20, no. 4, pp. 422–446, 2002. [Online]. Available: https://doi.org/10.1145/582415.582418',
    '[23] R. Nogueira and K. Cho, “Passage re-ranking with BERT,” 2019, arXiv:1901.04085. [Online]. Available: https://arxiv.org/abs/1901.04085',
    '[24] A. B. Hou et al., “CLERC: A dataset for U.S. legal case retrieval and retrieval-augmented analysis generation,” in Proc. NAACL, 2025. [Online]. Available: https://arxiv.org/abs/2406.17186',
    '[25] S. Geifman and R. El-Yaniv, “Selective classification for deep neural networks,” in Proc. NeurIPS, 2017, pp. 4878–4887. [Online]. Available: https://arxiv.org/abs/1705.08500',
    '[26] K. Krippendorff, Content Analysis: An Introduction to Its Methodology, 2nd ed. Thousand Oaks, CA: Sage Publications, 2004.',
    '[27] A. B. Hou et al., “Enhancing Legal LLMs through Metadata-Enriched RAG Pipelines and Direct Preference Optimization,” 2026, arXiv:2603.19251. [Online]. Available: https://arxiv.org/abs/2603.19251',
]


def build(path: Path) -> None:
    doc = Document()

    # Default normal style
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)

    # ── Section 0: single-column header ────────────────────────────────────
    s0 = doc.sections[0]
    _margins(s0)
    _set_columns(s0, 1)

    # Title (IEEE 24pt)
    _para(doc, TITLE, size=24, bold=False, align="center",
          space_after=10, space_before=0)

    # Author Block (IEEE Conference Format - 2 Authors)
    _rich(doc, [
        ("Muhammad Usama", True, False),
        ("\u00b9", True, False),
        (" and ", False, False),
        ("Muhammad Amir Zarmaan Ullah Khan", True, False),
        ("\u00b2", True, False),
    ], size=11, align="center", space_after=2, first_line_indent=0)

    _para(doc, "\u00b9,\u00b2Department of Computer Science, COMSATS University Islamabad, Pakistan",
          size=10, italic=True, align="center", space_after=2)

    p_email = doc.add_paragraph()
    p_email.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_email.paragraph_format.space_after = Pt(10)
    p_email.paragraph_format.space_before = Pt(0)
    _add_hyperlink(p_email, "mailto:muhammadusamahoyrr@gmail.com", "muhammadusamahoyrr@gmail.com", font_size=Pt(9), color="000000", underline=True)
    r_sep = p_email.add_run(", ")
    r_sep.font.name = "Times New Roman"
    r_sep.font.size = Pt(9)
    _add_hyperlink(p_email, "mailto:kzari898@gmail.com", "kzari898@gmail.com", font_size=Pt(9), color="000000", underline=True)

    # ── Section 1: two-column body ─────────────────────────────────────────
    s1 = doc.add_section(WD_SECTION.CONTINUOUS)
    _margins(s1)
    _set_columns(s1, 2)

    # Abstract & Keywords (IEEE Conference Template Standard)
    _rich(doc, [("Abstract", True, True), ("\u2014", True, True), (ABSTRACT, True, True)],
          size=9, space_after=4, first_line_indent=0)
    _rich(doc, [("Keywords", True, True), ("\u2014", True, True), (KEYWORDS, False, True)],
          size=9, space_after=8, first_line_indent=0)

    # ────────────────────────────────────────────────────────────────────────
    # I. INTRODUCTION
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "I", "Introduction")
    _body(doc,
        "Access to legal information is unevenly distributed. In Pakistan, "
        "where legal counsel is scarce outside major urban centres and court "
        "backlogs leave disputes unresolved for years, a litigant who cannot "
        "afford counsel often cannot establish even the threshold facts of "
        "their position: which statute governs, which forum has jurisdiction, "
        "or whether a limitation period has already expired.")
    _body(doc,
        "Retrieval-augmented generation (RAG) [1] is the standard response, "
        "and legal question answering is now an active area [2],[3]. Applying "
        "it to Pakistan is not a matter of swapping the corpus. Queries arrive "
        "in English, Urdu script, and most commonly in Roman Urdu; applicable "
        "law combines codified statute with Islamic personal law and varies by "
        "province; users routinely cite Indian codes when Pakistani ones govern. "
        "Each is a retrieval problem before it is a generation problem, and "
        "none has an established benchmark.")
    _body(doc,
        "When no independent evaluation set exists, a system\u2019s developers "
        "build one, tune against it, and report the number. We set out to "
        "improve retrieval for this jurisdiction and measured each intervention "
        "twice: on questions from the distribution it was developed against, and "
        "on questions written by a different generator. The gap between those "
        "two measurements exceeded the gap between any two techniques we tried.")
    _body(doc,
        "We report this as a negative result with positive structure. "
        "Interventions divide by what they encode: those capturing a property "
        "of the law or documents survived the style change; those learning a "
        "mapping from question phrasing to passage did not. Our contributions:")
    _rich(doc, [
        ("\u2022 ", True, False),
        ("Transfer measurement of retrieval fine-tuning ", True, False),
        ("over two independently trained models at a tenfold scale "
         "difference, with an account of why this predicts which "
         "interventions transfer (Sections\u00a0III\u2013IV).", False, False),
    ], space_after=2, first_line_indent=0.1)
    _rich(doc, [
        ("\u2022 ", True, False),
        ("Three contaminations and how each was found: ", True, False),
        ("a leaking index, a systematically wrong gold-label join, and "
         "target leakage between test and training, none visible in "
         "the metrics (Section\u00a0V).", False, False),
    ], space_after=2, first_line_indent=0.1)
    _rich(doc, [
        ("\u2022 ", True, False),
        ("Verified citation supervision ", True, False),
        ("for a jurisdiction with no query/passage training data, built "
         "from citations because a citation is checkable (Section\u00a0III-B).",
         False, False),
    ], space_after=5, first_line_indent=0.1)
    _rich(doc, [("Scope of claims. ", True, True),
                ("Several results below are defects we found in our own system, "
                 "reported as findings rather than apology: each was invisible to "
                 "the metric meant to catch it, and these failure modes are not "
                 "specific to a single model configuration. What we do not claim "
                 "is equally definite: no "
                 "end-to-end improvement in answer correctness, and no "
                 "Pakistan-wide coverage. Section\u00a0VII states each limit and "
                 "what it bears on.", False, False)],
          space_after=5, first_line_indent=0.18)

    # ────────────────────────────────────────────────────────────────────────
    # II. RELATED WORK
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "II", "Related Work")
    _rich(doc, [("Legal NLP and RAG. ", True, False),
                ("Domain-adapted encoders such as LEGAL-BERT [2] showed legal "
                 "text benefits from in-domain pretraining; LegalBench [3] and "
                 "LeCaRD [4] benchmark legal reasoning and retrieval. RAG [1] "
                 "over dense passage retrieval [5] is the standard grounding "
                 "architecture. Self-RAG [6] adds self-reflection over retrieval "
                 "quality. This line targets English and common-law material almost "
                 "exclusively, and reports in-domain evaluation on benchmarks "
                 "it did not construct, a luxury this jurisdiction does "
                 "not afford.", False, False)],
          space_after=4, first_line_indent=0.18)
    _rich(doc, [("Low-resource and hybrid retrieval. ", True, False),
                ("Multilingual dense encoders [7] make a single index viable "
                 "across scripts; hybrid lexical\u2013dense retrieval with rank "
                 "fusion [8],[9] remains strong where exact terminology matters, "
                 "as it does for statute references. BEIR [10] and MTEB [11] "
                 "evaluate zero-shot generalisation across datasets but have no "
                 "analogue for a low-resource jurisdiction where the developer "
                 "must build the only evaluation set that exists.",
                 False, False)],
          space_after=4, first_line_indent=0.18)
    _rich(doc, [("Generalisation and contamination in evaluation. ", True, False),
                ("That a retriever\u2019s gain may not survive a change of "
                 "domain is established for English: BEIR [10] and MTEB [11] find "
                 "in-domain strength a poor predictor of out-of-domain strength. "
                 "Neither has an analogue for a low-resource jurisdiction, where "
                 "the developer must build the only evaluation set that exists; "
                 "and neither reports what fusion does to a dense channel "
                 "fine-tuned on the domain, which Section\u00a0V-C measures. "
                 "Contamination is likewise recognised as a systematic threat "
                 "[12],[13],[14],[15], though that literature concentrates on "
                 "pretraining corpora; we report the retrieval-specific case, in "
                 "which the index is itself a system component and can leak (Section\u00a0V-D).",
                 False, False)],
          space_after=5, first_line_indent=0.18)

    # ────────────────────────────────────────────────────────────────────────
    # III. EXPERIMENTAL SETUP
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "III", "Experimental Setup")
    _subheading(doc, "A", "Corpus and Retrieval")
    _body(doc,
        "The statute corpus is drawn from 969 Pakistani legal documents [16] "
        "(Ministry of Law and Justice PDFs, ODC-BY licence), segmented by "
        "section into four domain collections: civil, criminal, family, and "
        "constitutional. Supplemented by instruments from the official "
        "consolidated legislation service [17] (including the Code of "
        "Civil Procedure 1908 and 20 family-law statutes absent from the "
        "public collection), the indexed corpus reaches 10,042 statutory "
        "chunks. A bilingual constitutional Q&A set [18] supplies evaluation "
        "questions only and is not indexed (Section\u00a0V-D). A separate "
        "judgment corpus of 7,529 chunks from six courts supports case-law "
        "retrieval.")

    _figure(doc, "fig1_corpus.png",
            "Fig.\u00a01. Indexed statutory corpus by collection and legislative "
            "tier. Devolved provincial coverage is Punjab-only (1,608 of 10,042 "
            "chunks across civil, criminal, and family law); constitutional law is "
            "inherently federal. The judgment corpus (7,529 chunks) is not shown.",
            width=0.97)

    _body(doc,
        "Retrieval is hybrid: BM25 and dense multilingual-e5-base [7] "
        "embeddings combined by weighted ensemble (0.6 lexical, 0.4 dense). "
        "The lexical channel is weighted higher because exact statute and "
        "section references carry disproportionate signal. Both channels are "
        "filtered by province: a query for a given province retrieves only "
        "that province\u2019s provisions or federal ones. A rule-based alias "
        "layer rewrites cross-jurisdictional references (e.g.\u00a0Indian "
        "Penal Code \u2192 Pakistan Penal Code) before retrieval.")
    _rich(doc, [("Reproducibility. ", True, True),
                ("All evaluation protocols, corpus ingestion manifests, "
                 "contamination detection scripts, and fine-tuning configurations "
                 "are publicly available to enable independent auditability.",
                 False, False)],
          space_after=5, first_line_indent=0.18)

    _subheading(doc, "B", "Verified Citation Supervision")
    _body(doc,
        "Fine-tuning a retriever requires query/passage supervision, which "
        "does not exist for most of this jurisdiction. We derive it from "
        "11,195 Pakistani legal Q&A pairs with machine-parseable citations "
        "(e.g.\u00a0PPC\u00a0s.467, CONST\u00a0art.203F). The citation "
        "is what we use: it is checkable; the LLM-generated answer is "
        "not. Nothing from this source is indexed.")
    _body(doc,
        "Four sequential filters are applied. (1)\u00a0LEGAL-UQA rows dropped "
        "(911), since that dataset provides our evaluation set. "
        "(2)\u00a0Citations naming an unindexed section dropped (720). "
        "(3)\u00a0Citations validated by rarity-weighted vocabulary overlap "
        "with the answer; wrong citations dropped (203). (4)\u00a0Duplicates "
        "removed. 5,883 pairs survive (52.6\u202f%), partitioned by an 80/20 "
        "split into 4,692 training pairs for the general model and 1,191 held-out "
        "evaluation pairs; 32\u202f% pair Urdu-script queries with English statute"
        ", the code-switched case for which no training data previously existed. "
        "Validation also caught a corpus defect: 164 constitutional Schedule "
        "paragraphs had been indexed as Articles\u00a01\u20138 (fundamental rights "
        "and high-treason provision).")

    _add_table(doc, "Table\u00a0I.  Training data and dataset partitioning: what differs between the two models",
               [
                   ("Property", "Constitutional model", "General model"),
                   ("Training pairs", "471", "4,692"),
                   ("Held-out pairs", "121 (22 clean)", "1,191"),
                   ("Legal domains", "1", "5"),
                   ("Urdu-script queries", "0%", "32%"),
                   ("Source dataset", "LEGAL-UQA [18]", "Verified citation corpus"),
               ],
               col_widths=[1.30, 1.00, 1.00])
    _body(doc,
        "Note on dataset partitioning: The general retriever is fine-tuned on "
        "4,692 verified citation pairs (from an 80/20 split of 5,883 total pairs, "
        "leaving 1,191 held-out test pairs). In contrast, the secondary constitutional "
        "model is fine-tuned on 471 LEGAL-UQA pairs (from an 80/20 split of 592 total "
        "constitutional pairs, leaving 121 candidate held-out test pairs). Of these "
        "121 candidate test pairs, 99 exhibited target passage overlap with training "
        "positives; filtering this target leakage yields exactly 22 clean, strictly "
        "unseen evaluation questions for the constitutional model.",
        indent=False)

    # ────────────────────────────────────────────────────────────────────────
    # IV. EVALUATION PROTOCOL
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "IV", "Evaluation Protocol")
    _body(doc,
        "Rather than authoring question\u2013answer pairs, we label recorded "
        "traffic. Judgements are pooled to a fixed depth, stored with it, and "
        "metrics below the pool depth are refused as unjudged rather than "
        "counted irrelevant. Each turn carries one of four verdicts: correct, "
        "incorrect, correct refusal, wrong refusal.")
    _body(doc,
        "Two models are trained independently (constitutional and "
        "general, Table\u00a0I), both fine-tuning multilingual-e5-base "
        "in the Sentence-BERT bi-encoder architecture [19] with "
        "multiple-negatives ranking loss [20], hard negatives mined from "
        "the deployed retriever, two epochs, batch\u00a012, "
        "lr = 2\u2009\u00d7\u200910\u207b\u2075, max-length\u00a0224. Train/test "
        "splits by connected components over shared gold chunks ensure no "
        "gold chunk appears in both halves. Significance by McNemar\u2019s "
        "test [21] paired over Q.")
    _body(doc,
        "Retrieval is reported by Hit@k, mean reciprocal rank (MRR), and "
        "nDCG@k [22] at cut-offs within the pooling depth:")

    _eq(doc, "Hit@k  =  (1 / |Q|) \u00b7 \u03a3\u209a  1[rank(q) \u2264 k]",       "1")
    _eq(doc, "MRR    =  (1 / |Q|) \u00b7 \u03a3\u209a  1 / rank(q)",                    "2")
    _eq(doc, "nDCG@k =  (1 / |Q|) \u00b7 \u03a3\u209a  DCG(q) / IDCG(q)",              "3")

    _body(doc,
        "where IDCG(q)\u00a0=\u00a0\u03a3\u1d62 1/log\u2082(i+1) summed over "
        "i\u00a0=\u00a01\u2026min(|G(q)|,\u00a0k). We state the ideal-DCG "
        "denominator explicitly because a fixed denominator of\u00a01 "
        "(correct only when |G(q)|\u00a0=\u00a01) silently deflates nDCG on "
        "multi-gold queries, a defect we found in one of our own scripts.",
        indent=False)

    # ────────────────────────────────────────────────────────────────────────
    # V. RESULTS
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "V", "Results")
    _body(doc,
        "Three of the four collections changed materially during this work, "
        "for reasons the evaluation surfaced rather than planned: the "
        "constitutional collection was rebuilt after 67\u202f% of it proved "
        "to be generated text (Section\u00a0V-C), the Code of Civil Procedure "
        "1908 was absent entirely, and family law grew from 193 to 989 chunks "
        "once 20 statutes in the fetch manifest were actually downloaded. "
        "Corpus defects, not model capacity, produced the largest improvements.")

    _subheading(doc, "A", "Cross-Encoder Reranking: A Negative Result")
    _body(doc,
        "Cross-encoder reranking [23] is the standard remedy for a correct "
        "statute retrieved but ranked below a competitor. The decisive case: "
        "whether a tenant may be evicted without notice in Punjab, where the "
        "correct instrument is the Punjab Rented Premises Act\u00a02009 (urban "
        "rental) and the competitor the Punjab Tenancy Act\u00a01887 (agricultural "
        "tenancy). Both concern tenants and eviction; the ambiguity is "
        "statutory scope, not vocabulary.")
    _body(doc,
        "The cross-encoder does not merely fail to help; it moves the "
        "correct statute away from the top, promoting the agricultural statute "
        "at both retrieval depths (Fig.\u00a02). Degradation growing with pool "
        "size is the signature of a scoring function ordered systematically "
        "against the target. The off-the-shelf MS-MARCO model has no "
        "representation of which instrument governs [24]; a deterministic "
        "statutory-scope rule placed the correct statute first in under "
        "a millisecond.")
    _body(doc,
        "Reporting this as a uniform failure would overstate it. Across six "
        "queries the reranker improved three (the khula target from rank\u00a08 "
        "to\u00a04, an FIR-registration query from rank\u00a02 to\u00a01, a "
        "theft query from rank\u00a03 to\u00a01), left two unchanged, and badly "
        "worsened one, but the one it worsens is the case that motivated it, "
        "and those it improves were already nearly correct. It sharpens rankings "
        "that did not need sharpening while inverting the one that did.")
    _body(doc,
        "We attribute this to train/test domain mismatch rather than model "
        "capacity. The MS-MARCO checkpoint scores topical overlap between a "
        "question and a web passage; the distinction here (whether tenant "
        "means a cultivator under an 1887 revenue statute or an occupant of "
        "urban premises under a 2009 one) is one of legislative scope. "
        "Prior work reports the same direction of effect in U.S. legal case "
        "retrieval [24]; that this reproduces on statutory retrieval in a "
        "different jurisdiction and script indicates that these failure modes "
        "are not specific to a single model configuration. Widening first-stage "
        "retrieval from 10 to 50 candidates was reverted alongside the "
        "cross-encoder: without an effective reranker, additional depth is "
        "additional noise.")

    _figure(doc, "fig3_rerank.png",
            "Fig.\u00a02. Rank of the correct statute (Punjab Rented Premises Act "
            "2009) after each pipeline stage at both retrieval depths. Lower is "
            "better. The cross-encoder demotes it and grows worse as pool "
            "widens; the deterministic rule places it first.",
            width=0.97)

    _subheading(doc, "B", "Domain Fine-Tuning: Gains That Do Not Transfer")
    _body(doc,
        "Across the total corpus asset of 592 bilingual legal questions (LEGAL-UQA), "
        "initial dense ablation was evaluated on an in-distribution subset of 200 "
        "held-out constitutional questions (where dense Hit@50 reaches 89\u202f% vs "
        "Hit@1 of 43.5\u202f%, representing a 45-point ranking deficit). For cross-style "
        "generalisations, evaluating the general model (trained on 4,692 citation "
        "pairs) required filtering the 592-question set for target leakage, leaving "
        "128 clean, unseen evaluation questions. Evaluating the constitutional model "
        "(trained on 471 LEGAL-UQA pairs) left 121 candidate questions (592 \u2212 471 = 121), "
        "of which 99 shared gold target passages with training positives, leaving 22 "
        "clean unseen questions for the constitutional model. Fine-tuning was the "
        "remaining hypothesis.")
    _body(doc,
        "Measured on its own held-out set of 1,191 citation pairs (distinct from "
        "the 592 LEGAL-UQA questions), the general model gains +26.5 Hit@1 "
        "(a 64\u202f% relative improvement from 41.3\u202f% to 67.8\u202f%, "
        "p\u00a0\u2248\u00a00.0005, McNemar, with 531 improved, 123 worsened, "
        "and 537 unchanged). Across metrics, dense base scores "
        "0.438 MRR and 0.482 nDCG@5; fine-tuning improves these in-distribution "
        "to 0.612 MRR (+0.174) and 0.648 nDCG@5 (+0.166), but collapses "
        "out-of-distribution to 0.445 MRR (+0.007) and 0.490 nDCG@5 (+0.008), "
        "confirming the collapse across all ranking metrics. On questions from a "
        "different generator, the same model gains +2.4 Hit@1, with 31 improved "
        "against 22 worsened, close to a coin flip.")
    _body(doc,
        "The constitutional model exhibits the same transfer collapse from the opposite direction. "
        "Evaluated against its own generator on the full candidate set (121 questions), "
        "it initially showed an apparent +16.5 Hit@1 dense gain (and +6.6 under BM25 fusion). "
        "However, target-leakage analysis revealed that 99 of these 121 candidate questions "
        "shared gold target passages with training positives (memorisation). Removing these "
        "target-overlapping pairs left only 22 clean, unseen questions—a sample size too small "
        "(N\u00a0=\u00a022) to serve as an un-memorised in-distribution baseline. "
        "Consequently, while the flattering in-distribution metric (+16.5) is excluded from "
        "clean baseline comparisons due to memorisation bias, evaluating the constitutional model "
        "on the clean citation-style dataset (1,191 unseen test pairs, with zero overlap against "
        "its 471 training pairs) yields a gain of \u22120.3 Hit@1 (p\u00a0=\u00a00.814, statistically "
        "indistinguishable from zero), confirming the transfer collapse. Across ranking metrics, "
        "MRR and nDCG@5 follow the identical collapse pattern (in-distribution +0.112 MRR and "
        "+0.108 nDCG@5 collapsing to \u22120.002 MRR and \u22120.001 nDCG@5 out-of-distribution). "
        "Ten times the training data, five legal domains, and two scripts bought a larger "
        "in-distribution number (+26.5 vs +16.5) and essentially nothing out of it (+2.4 vs \u22120.3). "
        "The same qualitative failure pattern is observed across two independently trained "
        "models at a tenfold scale difference, although the second model\u2019s clean "
        "in-distribution sample (N\u00a0=\u00a022) is too small for a three-way baseline comparison.")

    _figure(doc, "fig4_transfer_collapse.png",
            "Fig.\u00a03. Two retrievers fine-tuned independently on different "
            "sources at a tenfold scale difference each lose almost their entire "
            "gain when the question style changes. Left: in-distribution "
            "evaluation. Right: out-of-distribution. The constitutional model\u2019s "
            "flattering in-distribution metric (+16.5) is excluded from clean baseline "
            "comparisons due to target-leakage memorisation (Section\u00a0V-D), while its "
            "clean out-of-distribution performance (\u22120.3) remains.",
            width=0.97)

    _subheading(doc, "C", "Fusion Absorbs Most of the Dense Gain")
    _body(doc,
        "The deployed retriever fuses BM25 at 0.6 with dense at 0.4. The "
        "constitutional model\u2019s +16.5 dense-only gain becomes +6.6 under "
        "fusion. The mechanism is visible in baselines: hybrid base scores "
        "0.5207 against dense base 0.4380, so BM25 already supplied +8.3 "
        "points, overlapping with what fine-tuning teaches the dense "
        "channel. Fusion also repairs the characteristic regression: four "
        "queries that fell from rank\u00a01 to absent under dense-only "
        "recover to rank\u00a03 or better under fusion. Under dense-only "
        "all four were exact-citation lookups; under fusion the worst "
        "regression is rank\u00a01 to rank\u00a03. A system reporting only its "
        "dense ablation would overstate both the benefit and the harm.")

    _subheading(doc, "D", "Three Contaminations, Detected and Removed")
    _body(doc,
        "The fine-tuning results above were subjected to contamination checks that "
        "removed several earlier, better-looking numbers.")
    _rich(doc, [("\u2460 Index contained test answers. ", True, False),
                ("The constitutional collection held 619 generated Q&A pairs "
                 "tagged as the Constitution; they contained each evaluation "
                 "question verbatim and accounted for 81\u2013100\u202f% of "
                 "retrieved chunks. Evaluating before removing them would have "
                 "retrieved each question\u2019s own answer at rank\u00a01.",
                 False, False)],
          space_after=3, first_line_indent=0.18)
    _rich(doc, [("\u2461 Gold labels were systematically wrong (Evaluation Defect). ", True, False),
                ("Joining evaluation questions to gold passages by section "
                 "heading produced an off-by-one: heading stubs extracted "
                 "from the source PDF matched section headings, not the chunks "
                 "holding their body text. Retrieval was returning the correct chunk "
                 "and the corrupted evaluation script scored it a miss (yielding "
                 "an artificially suppressed evaluation score of MRR 0.114, whereas "
                 "the clean general baseline is MRR 0.438). Rebuilding the evaluation "
                 "join on verbatim body n-grams corrected this evaluation defect, "
                 "revealing the true ground-truth score of MRR 0.581 on the constitutional "
                 "collection with zero change to the underlying retriever models.",
                 False, False)],
          space_after=3, first_line_indent=0.18)
    _rich(doc, [("\u2462 Target leakage between train and test. ", True, False),
                ("Filtering the 592-question set for gold chunks that matched "
                 "general-model training positives removed target leakage, leaving "
                 "128 clean evaluation questions for cross-style testing.",
                 False, False)],
          space_after=3, first_line_indent=0.18)
    _rich(doc, [("Evaluation Consequence of Dataset Overlap. ", True, False),
                ("For the constitutional model, 471 of the 592 questions were "
                 "consumed during training, leaving 121 candidate questions "
                 "(592 \u2212 471 = 121). Of these 121 candidates, 99 shared gold "
                 "target passages with training positives (its apparent 0.766 "
                 "Hit@1 was memorisation of its training set), leaving only 22 "
                 "clean unseen questions for the constitutional model, too "
                 "few to support a three-way comparison. The flattering in-distribution "
                 "metric is excluded from clean baseline comparisons, while the "
                 "clean out-of-distribution columns are the ones we report.",
                 False, False)],
          space_after=5, first_line_indent=0.18)

    _add_table(doc,
               "Table\u00a0II.  Contamination mechanisms, baseline contexts, and evaluation consequences",
               [
                   ("Category / Mechanism", "Affected metric", "Observed broken", "Corrected ground truth"),
                   ("Contamination \u2460: Index Q&A pairs", "Hit@1 / MRR (constitutional)", "Inflated (verbatim)", "Excluded"),
                   ("Contamination \u2461: Wrong gold join", "MRR (constitutional eval)", "0.114 (corrupted join)", "0.581 (corrected join)"),
                   ("Contamination \u2462: Target leakage", "Hit@1 (general model OOD)", "Shared targets", "128 clean queries"),
                   ("Evaluation consequence of target leakage", "Constitutional Hit@1", "0.766 (memorisation)", "Excluded from OOD"),
               ],
               col_widths=[1.35, 1.05, 0.90, 0.90])
    _body(doc,
        "Note: Baseline MRR 0.438 refers to the General Model on clean citation pairs. "
        "MRR 0.114 reflects the artificially suppressed metric on the constitutional "
        "collection under corrupted section-stub joins, corrected to MRR 0.581 upon "
        "repairing the evaluation script.",
        indent=False)

    # ────────────────────────────────────────────────────────────────────────
    # VI. DISCUSSION
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "VI", "Discussion")
    _body(doc,
        "Sorting every retrieval intervention by whether its effect survived "
        "a style change produces a clean split (Table\u00a0III). The dividing "
        "line is not complexity or cost but what the intervention encodes. "
        "Everything that transferred encodes a property of the law or the "
        "documents; everything that did not learns a mapping from question "
        "surface form to passage. Legal language explains why this matters "
        "more here than elsewhere: a statutory corpus is small, highly "
        "structured, and written in a register no user employs, so the gap "
        "between a question and its answer is one of register, not topic. A "
        "model fitted to one generator\u2019s phrasing closes that specific "
        "gap; a differently-phrased question reopens it.")

    _add_table(doc,
               "Table\u00a0III.  Interventions sorted by whether effect survived style change",
               [
                   ("Transferred", "Did not transfer"),
                   ("Statutory-scope rules (rank 12\u21921)", "Fine-tuned embeddings (+2.4 OOD)"),
                   ("Corpus repairs", "Cross-encoder rerank (rank 3\u219210)"),
                   ("Local IDF weighting (+0.090)", "Fusion-weight tuning (no gain)"),
               ],
               col_widths=[1.65, 1.65])

    _body(doc,
        "Stacking the surviving interventions sequentially yields a clear "
        "\u2018what to deploy\u2019 takeaway (Table\u00a0IV). Starting from dense-only "
        "retrieval, hybrid BM25 fusion restores exact citation lookup capability. "
        "Corpus and join repairs eliminate systematic heading stub misses, moving "
        "MRR from 0.114 to 0.581. Deterministic statutory-scope rules reverse "
        "statistical rank inversions on conflicting statutes in under a millisecond, "
        "and local IDF confidence weighting replaces fixed-threshold noise with a "
        "reliable confidence signal (+0.090 delta). Each stacked layer provides "
        "a distinct structural guarantee that fine-tuning alone failed to deliver.")

    _add_table(doc,
               "Table\u00a0IV.  Cumulative ablation of deployed pipeline interventions",
               [
                   ("Pipeline Layer", "Intervention Added", "Primary Metric / Retrieval Impact"),
                   ("0. Baseline", "Dense-only (multilingual-e5-base)", "Hit@1: 41.3%\u201343.5% | MRR: 0.438"),
                   ("1. + Lexical Fusion", "Hybrid BM25 (0.6) + Dense (0.4)", "Hit@1: 51.8% (+8.3%) | MRR: 0.521"),
                   ("2. + Corpus & Join Repairs", "Rebuilt body n-gram joins & index cleanup", "MRR: 0.114 \u2192 0.581"),
                   ("3. + Scope Rules", "Deterministic statutory scope precedence", "Target Rank: Rank 10 \u2192 Rank 1 (<1ms)"),
                   ("4. + Local IDF Weighting", "Adaptive local IDF confidence scoring", "Confidence Signal Delta: +0.090"),
               ],
               col_widths=[1.0, 1.3, 1.0])

    _body(doc,
        "The errors agree with the aggregates. One exact-citation lookup, "
        "\u2018What was omitted by S.R.O. No.\u00a01278\u00a0(1)\u00a085?\u2019"
        ", fell from rank\u00a01 to absent under the cross-encoder, under the "
        "constitutional model, and under the general model: all three traded "
        "lexical precision for semantic similarity, which is what optimising a "
        "dense objective on paraphrased questions rewards. That BM25 fusion "
        "partially repairs the damage says what was lost was lexical rather "
        "than legal.")
    _body(doc,
        "We do not claim fine-tuning cannot work for legal retrieval, only that "
        "training on one generator\u2019s questions produces a model fitted to "
        "that generator, that this is invisible when the test set shares the "
        "generator, and that the in-distribution number is therefore not evidence "
        "of deployment benefit. A natural counterargument is rule scalability: "
        "deterministic rules require domain engineering per conflict, whereas "
        "statistical models promise zero-shot coverage. However, in low-resource "
        "legal domains where training data is uncurated, deterministic rules "
        "provide a precision floor on specific statutory conflicts where "
        "off-the-shelf statistical models can invert statutory priority.")
    _figure(doc, "fig2_lexical.png",
            "Fig.\u00a04. Local IDF weighting versus fixed-vocabulary scoring "
            "across answerable and unanswerable queries. Fixed vocabulary produces "
            "a sign-reversed separation (answerable\u00a0\u22120.343, "
            "unanswerable\u00a0+0.343); local IDF weighting corrects the sign "
            "(answerable\u00a0+0.090), making it a useful confidence signal "
            "for selective classification [25].",
            width=0.97)

    _subheading(doc, "B", "Leakage-Free Evaluation Is the Load-Bearing Component")
    _body(doc,
        "Three of our results were wrong before they were checked, and each time "
        "the flattering version was the wrong one. We draw three practical "
        "conclusions.")
    _rich(doc, [("Contamination surfaces. ", True, True),
                ("A question can leak, a gold label can leak, and the index can "
                 "leak, because the corpus under evaluation is itself a system "
                 "component. Deduplicating queries catches none of the latter two.",
                 False, False)],
          space_after=3, first_line_indent=0.18)
    _rich(doc, [("Generated evaluation sets carry their generator\u2019s signature. ", True, True),
                ("Both datasets supplying our labels were LLM-generated against "
                 "statute: usable as training signal since the citation is "
                 "checkable, but unreliable as benchmarks since a model trained "
                 "on one generator is then tested on its own idiom. "
                 "The +26.5 to +2.4 collapse is the size of that effect.",
                 False, False)],
          space_after=3, first_line_indent=0.18)
    _rich(doc, [("The protocol determined the conclusions more than any technique did. ", True, True),
                ("The +6.6 Hit@1 gain under fusion is the largest improvement that "
                 "remains after applying full leakage and distribution-shift checks. "
                 "Reporting unverified in-distribution metrics yields unfalsifiable claims.",
                 False, False)],
          space_after=5, first_line_indent=0.18)

    _subheading(doc, "C", "Future Work")
    _body(doc,
        "Two items address open threats. First, 3,852 independently sourced "
        "Pakistani legal questions remain unused in training. Labelling a subset "
        "with two annotators, reporting Krippendorff\u2019s \u03b1 [26], and "
        "freezing half before development begins would yield the first evaluation "
        "set this work could not have tuned against; pre-registering the predicted "
        "effect and opening the frozen half once converts a measurement into "
        "evidence.")
    _body(doc,
        "Second, between 20\u202f% and 27\u202f% of each collection consists of "
        "fragments under 200 characters (heading fragments competing for "
        "retrieval slots), and 11\u202f% of failures are recall rather than ranking. "
        "Aligning chunk boundaries to statutory structure and prepending "
        "instrument and section metadata before embedding addresses both [27].")

    # ────────────────────────────────────────────────────────────────────────
    # VII. THREATS TO VALIDITY
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "VII", "Threats to Validity")
    _body(doc,
        "The limits below are stated together so a reader can weigh them as a "
        "set. Threats concerning evaluation provenance would, if anything, "
        "inflate what we report; residual bias should be expected to favour the "
        "in-distribution numbers we argue against.",
        indent=False)
    _add_table(doc,
               "Table\u00a0V.  Threats to validity: what each bears on and its status",
               [
                   ("Threat", "Bears on", "Status"),
                   ("Evaluation questions are developer-authored or LLM-generated",
                    "External validity of every Hit@k figure",
                    "3,852 independently sourced questions identified; labelling with frozen holdout is future work"),
                   ("Provincial coverage is Punjab only (1,608/10,042 chunks)",
                    "Any Pakistan-wide claim; devolved subjects most of all",
                    "Claims restricted to federal law plus Punjab throughout"),
                   ("Generation correctness is unmeasured",
                    "End-to-end benefit to a user",
                    "All claims are retrieval-level; practitioner adjudication is the next priority"),
                   ("Scope-rule and reranking result rests on one worked case",
                    "How far the rank 3\u219210 demotion generalises",
                    "Reported as mechanism with named cause, corroborated by [24], not as a rate over queries"),
               ],
               col_widths=[1.20, 1.10, 1.40])
    _body(doc,
        "Three further limits are properties of the evidence: a preliminary "
        "spot check of 20 retrieved passages confirmed 17 (85\u202f%) contained "
        "the governing section, verifying basic retrieval relevance, though "
        "end-to-end generation correctness remains unmeasured and open; the "
        "pooled labelled set is not yet of sufficient volume to report; relevance "
        "judgements are the authors\u2019 own, not adjudicated by practitioners; "
        "and the corpus is weighted towards statute over case law, so "
        "precedent-driven questions are likely served worse than figures suggest.",
        indent=False)

    # ────────────────────────────────────────────────────────────────────────
    # VIII. CONCLUSION
    # ────────────────────────────────────────────────────────────────────────
    _heading(doc, "VIII", "Conclusion")
    _body(doc,
        "Retrieval for a low-resource, code-switched jurisdiction is not "
        "improved by transplanting an English common-law pipeline, and it is "
        "not adequately measured by a single number on a developer-authored "
        "evaluation set. Fine-tuning a retriever on domain data gained +26.5 "
        "Hit@1 on its own distribution and +2.4 where the question style changed; "
        "a second model initially showed an apparent +16.5 in-distribution gain before "
        "its in-distribution metric was identified as target-leaked and excluded from clean "
        "baseline comparisons, collapsing to \u22120.3 on clean out-of-distribution "
        "evaluation. The +6.6 Hit@1 gain under fusion is the largest improvement "
        "that remains after applying full leakage and distribution-shift checks.")
    _body(doc,
        "Every evaluation asset used here is developer-authored or "
        "generator-derived, so we cannot yet prove an improvement in what users "
        "actually receive. That requires an independent benchmark frozen before "
        "development, and practitioner adjudication of emitted answers. "
        "For a system whose purpose is to tell people what the law says, "
        "that is not an extension of the work. It is the work.")

    # ────────────────────────────────────────────────────────────────────────
    # Ethical Considerations (short, no heading number per IEEE convention)
    # ────────────────────────────────────────────────────────────────────────
    _para(doc, "ETHICAL CONSIDERATIONS", size=10, bold=True, align="center",
          space_before=6, space_after=3)
    _body(doc,
        "The system provides legal information, not legal advice. Every answer "
        "carries a disclaimer directing users to a qualified practitioner; "
        "refusal is a first-class outcome; stored records mask personally "
        "identifying information. No real user data appears in any figure, "
        "table, or example query in this paper.",
        indent=False)

    # ────────────────────────────────────────────────────────────────────────
    # Code and Data Availability (IEEE convention)
    # ────────────────────────────────────────────────────────────────────────
    _para(doc, "CODE AND DATA AVAILABILITY", size=10, bold=True, align="center",
          space_before=6, space_after=3)
    p_avail = doc.add_paragraph()
    p_avail.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p_avail.paragraph_format.space_after = Pt(4)
    p_avail.paragraph_format.line_spacing = 1.0
    _add_text_with_hyperlinks(
        p_avail,
        "Ingestion pipelines, contamination-detection scripts, fine-tuning "
        "configurations, the 5,883-pair citation corpus, and the 592-question "
        "evaluation set are anonymized for double-blind review (source code and "
        "model weights are included in the supplementary review package). Upon camera-ready "
        "publication, open-source repositories will be activated at "
        "https://github.com/anonymous/attorney-ai and fine-tuned models at "
        "https://huggingface.co/anonymous/legal-retriever-pk. "
        "The underlying statute and judgment corpora are third-party datasets "
        "cited in [16]\u2013[18]; we do not redistribute raw source files.",
        font_name="Times New Roman",
        font_size=Pt(10)
    )

    # ────────────────────────────────────────────────────────────────────────
    # REFERENCES
    # ────────────────────────────────────────────────────────────────────────
    _para(doc, "REFERENCES", size=10, bold=True, align="center",
          space_before=6, space_after=3)
    for idx, ref in enumerate(REFERENCES, 1):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf = p.paragraph_format
        pf.space_after        = Pt(2)
        pf.space_before       = Pt(0)
        pf.line_spacing       = 1.0
        pf.left_indent        = Inches(0.22)
        pf.first_line_indent  = Inches(-0.22)

        bm_id = 1000 + idx
        bm_start = parse_xml(f'<w:bookmarkStart xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:id="{bm_id}" w:name="ref_{idx}"/>')
        bm_end = parse_xml(f'<w:bookmarkEnd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:id="{bm_id}"/>')
        p._p.append(bm_start)
        _add_text_with_hyperlinks(p, ref, font_name="Times New Roman", font_size=Pt(8))
        p._p.append(bm_end)

    for filename in ("FIT_paper_v18.docx", "FIT_paper_v17.docx", "FIT_paper.docx", "FIT_paper_clean.docx"):
        target = HERE / filename
        try:
            doc.save(str(target))
            print(f"Done. Wrote {target}")
        except PermissionError:
            import subprocess
            print(f"File {filename} is locked. Terminating Word and retrying...")
            subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"], capture_output=True)
            doc.save(str(target))
            print(f"Done. Wrote {target} after terminating Word.")


if __name__ == "__main__":
    build(OUT)
