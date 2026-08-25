"""
pdf_generator.py — Pure-Python PDF generation using reportlab.
No LibreOffice dependency. Each template is a function that returns a PDF bytes.

Urdu support: text containing Arabic-script characters is shaped
(arabic_reshaper + python-bidi) and rendered right-to-left in Noto Naskh
Arabic. Mixed markup (<b>…</b>) with Urdu inside is passed through unshaped —
keep Urdu values markup-free.
"""

import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
# reportlab renders QR natively — no new dependency (see Overseas Desk QR work).
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing

from app.core.config import settings


def _qr_flowable(url: str, size_cm: float = 2.6) -> Drawing:
    """A scannable QR flowable for a verify URL. Drawing subclasses Flowable, so it
    drops straight into a platypus story."""
    size = size_cm * cm
    widget = QrCodeWidget(url)
    x0, y0, x1, y1 = widget.getBounds()
    w, h = (x1 - x0) or 1, (y1 - y0) or 1
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, -x0, -y0])
    d.add(widget)
    return d


def _verify_block(f: dict, s: dict):
    """QR + caption pointing at the point-of-use verification page. Returns [] when
    no verify_url was supplied (older callers), so it never breaks a document."""
    url = f.get("verify_url")
    if not url:
        return []
    caption = ParagraphStyle("qrcap", parent=s["footer"], alignment=TA_CENTER, fontSize=7.5)
    return [
        Spacer(1, 0.4 * cm),
        _qr_flowable(url),
        Paragraph("Scan to verify this document's live status (active / revoked / expired)"
                  f"<br/>{url}", caption),
    ]

UPLOADS_DIR = Path(settings.upload_root) / "docs"

# ── Urdu / Arabic-script rendering ────────────────────────────────────────────

_FONT_PATH = Path(__file__).parents[1] / "assets" / "fonts" / "NotoNaskhArabic-Regular.ttf"
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_URDU_FONT = None  # set on first successful registration


def _ensure_urdu_font() -> str | None:
    global _URDU_FONT
    if _URDU_FONT:
        return _URDU_FONT
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont("NotoNaskh", str(_FONT_PATH)))
        _URDU_FONT = "NotoNaskh"
    except Exception:
        _URDU_FONT = None
    return _URDU_FONT


def _shape_urdu(text: str) -> str:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def P(text, style):
    """Drop-in Paragraph that renders Urdu correctly (shaped, RTL, Urdu font).

    ASCII/Latin text passes straight through to reportlab's Paragraph.
    """
    text = "" if text is None else str(text)
    if _ARABIC_RE.search(text) and "<" not in text:
        font = _ensure_urdu_font()
        if font:
            shaped = _shape_urdu(text)
            ur_style = ParagraphStyle(
                f"{style.name}_ur", parent=style, fontName=font,
                alignment=TA_RIGHT, leading=max(getattr(style, "leading", 14) or 14, style.fontSize + 8),
            )
            return Paragraph(shaped, ur_style)
    return Paragraph(text, style)

# ── Shared styles ─────────────────────────────────────────────────────────────

def _base_doc(output_path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=2.5 * cm,
        leftMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )


def _styles():
    base = getSampleStyleSheet()
    return {
        "title":    ParagraphStyle("title",    parent=base["Title"],   fontSize=14, spaceAfter=6,  alignment=TA_CENTER, fontName="Helvetica-Bold"),
        "heading":  ParagraphStyle("heading",  parent=base["Heading2"], fontSize=11, spaceAfter=4,  fontName="Helvetica-Bold"),
        "label":    ParagraphStyle("label",    parent=base["Normal"],   fontSize=9,  spaceAfter=2,  textColor=colors.grey, fontName="Helvetica"),
        "body":     ParagraphStyle("body",     parent=base["Normal"],   fontSize=10, spaceAfter=6,  leading=14, alignment=TA_JUSTIFY),
        "small":    ParagraphStyle("small",    parent=base["Normal"],   fontSize=8,  spaceAfter=2,  textColor=colors.grey),
        "footer":   ParagraphStyle("footer",   parent=base["Normal"],   fontSize=8,  alignment=TA_CENTER, textColor=colors.grey),
    }


def _field(label: str, value: str, s: dict):
    return [
        P(label.upper(), s["label"]),
        P(value or "—", s["body"]),
        Spacer(1, 0.2 * cm),
    ]


def _hr():
    return HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=10)


def _today():
    return datetime.now(timezone.utc).strftime("%d %B %Y")


# ── Template generators ───────────────────────────────────────────────────────

def legal_notice(doc_id: str, f: dict) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P("LEGAL NOTICE", s["title"]),
        P(f"Date: {f.get('date', _today())}", ParagraphStyle("right", parent=s["body"], alignment=TA_LEFT)),
        _hr(),
        Spacer(1, 0.3 * cm),
    ]

    story += _field("From", f.get("sender_name", "") + (f"\n{f.get('sender_address', '')}" if f.get("sender_address") else ""), s)
    story += _field("To", f.get("recipient_name", "") + (f"\n{f.get('recipient_address', '')}" if f.get("recipient_address") else ""), s)
    story += [_hr()]

    story += [P("SUBJECT: LEGAL NOTICE", s["heading"]), Spacer(1, 0.2 * cm)]
    story += [P(f.get("notice_body", ""), s["body"])]
    story += [Spacer(1, 0.4 * cm)]

    if f.get("demand"):
        story += [
            P("DEMAND", s["heading"]),
            P(f.get("demand", ""), s["body"]),
            Spacer(1, 0.3 * cm),
        ]

    story += [
        P(f"If no response is received within <b>{f.get('response_days', '15')} days</b> of receipt of this notice, legal proceedings shall be initiated without further notice.", s["body"]),
        Spacer(1, 0.8 * cm),
        P("Yours faithfully,", s["body"]),
        Spacer(1, 0.6 * cm),
        P(f.get("sender_name", "______________________"), s["body"]),
        P("(Sender / Authorized Representative)", s["small"]),
    ]

    doc.build(story)
    return out


def plaint_civil(doc_id: str, f: dict) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P(f"IN THE {f.get('court_name', 'CIVIL COURT').upper()}", s["title"]),
        P(f"SUIT NO. _______ / {datetime.now(timezone.utc).year}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Plaintiff", f.get("plaintiff_name", "") + (f", {f.get('plaintiff_address', '')}" if f.get("plaintiff_address") else ""), s)
    story += _field("Defendant", f.get("defendant_name", "") + (f", {f.get("defendant_address", '')}" if f.get("defendant_address") else ""), s)
    story += [_hr()]

    story += [P("PLAINT", s["title"]), Spacer(1, 0.2 * cm)]
    story += [P("FACTS OF THE CASE", s["heading"])]
    story += [P(f.get("facts", ""), s["body"])]
    story += [Spacer(1, 0.3 * cm)]

    if f.get("cause_of_action"):
        story += [P("CAUSE OF ACTION", s["heading"]), P(f.get("cause_of_action", ""), s["body"]), Spacer(1, 0.3 * cm)]

    story += [P("RELIEF SOUGHT", s["heading"]), P(f.get("relief_sought", ""), s["body"]), Spacer(1, 0.3 * cm)]

    if f.get("applicable_laws"):
        story += [P("APPLICABLE LAW", s["heading"]), P(f.get("applicable_laws", ""), s["body"]), Spacer(1, 0.3 * cm)]

    story += [
        _hr(),
        P(f"Date: {f.get('date', _today())}", s["body"]),
        Spacer(1, 0.8 * cm),
        P("______________________", s["body"]),
        P(f.get("plaintiff_name", "Plaintiff"), s["small"]),
    ]

    doc.build(story)
    return out


def written_statement(doc_id: str, f: dict) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P(f"IN THE {f.get('court_name', 'CIVIL COURT').upper()}", s["title"]),
        P(f"SUIT NO. {f.get('suit_number', '_______')}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Plaintiff", f.get("plaintiff_name", ""), s)
    story += _field("Defendant", f.get("defendant_name", ""), s)
    story += [_hr()]

    story += [P("WRITTEN STATEMENT", s["title"]), Spacer(1, 0.2 * cm)]
    story += [P("PRELIMINARY OBJECTIONS", s["heading"]), P(f.get("preliminary_objections", ""), s["body"]), Spacer(1, 0.3 * cm)]
    story += [P("REPLY ON MERITS", s["heading"]), P(f.get("reply_on_merits", ""), s["body"]), Spacer(1, 0.3 * cm)]

    if f.get("additional_facts"):
        story += [P("ADDITIONAL FACTS", s["heading"]), P(f.get("additional_facts", ""), s["body"]), Spacer(1, 0.3 * cm)]

    story += [
        _hr(),
        P(f"Date: {f.get('date', _today())}", s["body"]),
        Spacer(1, 0.8 * cm),
        P("______________________", s["body"]),
        P(f.get("defendant_name", "Defendant"), s["small"]),
    ]

    doc.build(story)
    return out


def nda(doc_id: str, f: dict) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P("NON-DISCLOSURE AGREEMENT", s["title"]),
        P(f"Date: {f.get('date', _today())}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Disclosing Party", f.get("party_a", ""), s)
    story += _field("Receiving Party", f.get("party_b", ""), s)
    story += [_hr()]

    clauses = [
        ("1. PURPOSE", f.get("purpose", "The parties wish to explore a potential business relationship and may disclose confidential information to each other.")),
        ("2. CONFIDENTIAL INFORMATION", "Each party agrees to keep all non-public information disclosed by the other party strictly confidential and shall not disclose it to any third party."),
        ("3. OBLIGATIONS", "The receiving party shall use the confidential information solely for the stated purpose and shall protect it with the same degree of care it uses for its own confidential information."),
        ("4. DURATION", f"This Agreement shall remain in effect for a period of <b>{f.get('duration', '2 years')}</b> from the date of signing."),
        ("5. GOVERNING LAW", f"This Agreement shall be governed by the laws of Pakistan. Any disputes shall be resolved in the courts of <b>{f.get('jurisdiction', 'Islamabad')}</b>."),
    ]

    for heading, text in clauses:
        story += [P(heading, s["heading"]), P(text, s["body"]), Spacer(1, 0.2 * cm)]

    sig_data = [
        ["DISCLOSING PARTY", "RECEIVING PARTY"],
        ["\n\n______________________\n" + f.get("party_a", "Party A"), "\n\n______________________\n" + f.get("party_b", "Party B")],
        ["Signature & Date", "Signature & Date"],
    ]
    sig_table = Table(sig_data, colWidths=[8 * cm, 8 * cm])
    sig_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",  (0, 0), (-1, -1), 9),
        ("ALIGN",     (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [Spacer(1, 0.5 * cm), sig_table]

    doc.build(story)
    return out


def rental_agreement(doc_id: str, f: dict) -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P("TENANCY / RENTAL AGREEMENT", s["title"]),
        P(f"Date: {f.get('date', _today())}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    details = [
        ("Landlord", f.get("landlord_name", "")),
        ("Tenant",   f.get("tenant_name", "")),
        ("Property", f.get("property_address", "")),
        ("Monthly Rent", f"PKR {f.get('monthly_rent', '')}"),
        ("Tenancy Period", f.get("tenancy_period", "")),
        ("Security Deposit", f"PKR {f.get("security_deposit", '')}"),
        ("Commencement Date", f.get("start_date", _today())),
    ]
    for label, val in details:
        story += _field(label, val, s)

    story += [_hr(), P("TERMS AND CONDITIONS", s["heading"])]

    terms = [
        f"1. The tenant shall pay the monthly rent of PKR {f.get('monthly_rent', '___')} on or before the {f.get('rent_due_day', '5th')} of each month.",
        "2. The tenant shall not sublet the premises without prior written consent of the landlord.",
        "3. The tenant shall maintain the property in good condition and repair any damages caused by negligence.",
        f"4. A security deposit of PKR {f.get('security_deposit', '___')} shall be held by the landlord and refunded within 30 days of vacating, subject to deductions for damages.",
        "5. Either party may terminate this agreement with 30 days written notice.",
        f"6. This agreement is governed by the Rent Restriction Ordinance and applicable provincial tenancy laws of {f.get('province', 'Pakistan')}.",
    ]
    if f.get("additional_terms"):
        terms.append(f"7. {f.get('additional_terms')}")

    for term in terms:
        story += [P(term, s["body"])]

    sig_data = [
        ["LANDLORD", "TENANT"],
        ["\n\n______________________\n" + f.get("landlord_name", "Landlord"), "\n\n______________________\n" + f.get("tenant_name", "Tenant")],
        ["Signature & Date", "Signature & Date"],
    ]
    sig_table = Table(sig_data, colWidths=[8 * cm, 8 * cm])
    sig_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",  (0, 0), (-1, -1), 9),
        ("ALIGN",     (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [Spacer(1, 0.8 * cm), sig_table]

    doc.build(story)
    return out


# ── Inheritance templates ─────────────────────────────────────────────────────

def inheritance_settlement(doc_id: str, f: dict) -> Path:
    """Faraid share statement + family settlement sheet.

    Expects the output of inheritance.calculate() under f["calculation"] plus
    deceased_name / date_of_death / estate_description.
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []
    calc = f.get("calculation") or {}

    story += [
        P("STATEMENT OF INHERITANCE SHARES", s["title"]),
        P("(Islamic Law of Inheritance — Sunni Hanafi, as applied in Pakistan)",
                  ParagraphStyle("center", parent=s["small"], alignment=TA_CENTER)),
        P(f"Date: {f.get('date', _today())}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Deceased", f.get("deceased_name", ""), s)
    if f.get("date_of_death"):
        story += _field("Date of death", f.get("date_of_death", ""), s)
    story += _field("Estate description", f.get("estate_description", ""), s)
    story += _field("Total estate value", f"PKR {int(calc.get('estate_value', 0)):,}", s)
    story += [_hr()]

    story += [P("DISTRIBUTION OF SHARES", s["heading"]), Spacer(1, 0.15 * cm)]
    rows = [["Heir", "Count", "Share", "%", "Amount (PKR)"]]
    for r in calc.get("breakdown", []):
        rows.append([
            P(r.get("heir", "") + (f"<br/><font size=7 color=grey>{r['note']}</font>" if r.get("note") else ""), s["body"]),
            str(r.get("count", 1)),
            r.get("fraction", ""),
            f"{r.get('percentage', 0)}%",
            f"{int(r.get('amount', 0)):,}",
        ])
    table = Table(rows, colWidths=[7 * cm, 1.4 * cm, 1.8 * cm, 2 * cm, 3.4 * cm])
    table.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ALIGN",      (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 0.4 * cm)]

    for note in calc.get("notes", []):
        story += [P(f"• {note}", s["small"])]
    story += [Spacer(1, 0.3 * cm)]

    story += [
        P("LEGAL BASIS", s["heading"]),
        P(
            "Shares computed under the Islamic law of inheritance as enforced by the Muslim Personal Law "
            "(Shariat) Application Act, 1962, read with section 4 of the Muslim Family Laws Ordinance, 1961 "
            "(share of children of a predeceased child).", s["body"]),
        Spacer(1, 0.3 * cm),
        P("HOW TO OBTAIN THE SUCCESSION CERTIFICATE", s["heading"]),
        P(
            "For an <b>uncontested</b> estate, legal heirs may obtain a Succession Certificate or Letters of "
            "Administration directly from <b>NADRA</b> under the Letters of Administration and Succession "
            "Certificates Act, 2021 — typically within weeks, without court proceedings. Required: deceased's "
            "death certificate (NADRA), Family Registration Certificate (FRC), CNICs of all legal heirs, and "
            "details of assets. If any heir disputes the distribution or an heir is a minor, the matter must go "
            "to the civil court under the Succession Act, 1925.", s["body"]),
        Spacer(1, 0.5 * cm),
        P("ACKNOWLEDGEMENT OF HEIRS", s["heading"]),
        P("We, the undersigned legal heirs, acknowledge the above distribution:", s["body"]),
        Spacer(1, 0.5 * cm),
    ]
    sig_rows = [["Name", "Relation", "CNIC", "Signature"]] + [["", "", "", ""] for _ in range(max(3, len(calc.get("breakdown", []))))]
    sig = Table(sig_rows, colWidths=[4.5 * cm, 3.5 * cm, 4 * cm, 3.6 * cm], rowHeights=[0.7 * cm] + [1 * cm] * (len(sig_rows) - 1))
    sig.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID",     (0, 0), (-1, -1), 0.4, colors.lightgrey),
    ]))
    story += [sig, Spacer(1, 0.4 * cm), P(calc.get("disclaimer", ""), s["footer"])]

    doc.build(story)
    return out


def inheritance_demand(doc_id: str, f: dict) -> Path:
    """Demand letter for an heir denied their inheritance share."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P("LEGAL NOTICE — DEMAND FOR INHERITANCE SHARE", s["title"]),
        P(f"Date: {f.get('date', _today())}", ParagraphStyle("left", parent=s["body"], alignment=TA_LEFT)),
        _hr(),
    ]
    story += _field("From", f.get("claimant_name", "") + (f"\n{f.get('claimant_address', '')}" if f.get("claimant_address") else ""), s)
    story += _field("To", f.get("recipient_name", "") + (f"\n{f.get('recipient_address', '')}" if f.get("recipient_address") else ""), s)
    story += [_hr()]

    share_line = ""
    if f.get("share_fraction"):
        share_line = f" My share under Islamic law is <b>{f['share_fraction']}</b>"
        if f.get("share_amount"):
            share_line += f" (approximately <b>PKR {int(f['share_amount']):,}</b>)"
        share_line += "."

    story += [
        P("SUBJECT: DEMAND FOR DISTRIBUTION OF INHERITANCE", s["heading"]),
        Spacer(1, 0.2 * cm),
        P(
            f"I am a legal heir of the late <b>{f.get('deceased_name', '')}</b>"
            + (f", who passed away on {f['date_of_death']}" if f.get("date_of_death") else "")
            + f", being their <b>{f.get('relation', 'legal heir')}</b>. "
            f"The estate of the deceased includes: {f.get('estate_description', '')}."
            + share_line, s["body"]),
        Spacer(1, 0.2 * cm),
        P(
            "Despite repeated requests, my lawful share has not been distributed to me. "
            + (f.get("additional_facts", "") or ""), s["body"]),
        Spacer(1, 0.2 * cm),
        P("LEGAL POSITION", s["heading"]),
        P(
            "Under the Muslim Personal Law (Shariat) Application Act, 1962, succession to the estate of a "
            "deceased Muslim is governed by Islamic law, and every legal heir's share vests in them "
            "<b>immediately upon death</b>. Withholding, alienating, or refusing to hand over an heir's share "
            "is actionable. Depriving women of their inheritance is additionally a criminal offence under "
            "section 498-A of the Pakistan Penal Code (punishable with imprisonment up to ten years).", s["body"]),
        Spacer(1, 0.2 * cm),
        P("DEMAND", s["heading"]),
        P(
            f"You are called upon to distribute and hand over my lawful share within "
            f"<b>{f.get('response_days', '15')} days</b> of receipt of this notice, failing which I shall be "
            "constrained to initiate civil proceedings for administration and partition of the estate, and "
            "criminal proceedings where applicable, entirely at your risk as to costs and consequences.", s["body"]),
        Spacer(1, 0.8 * cm),
        P("Yours faithfully,", s["body"]),
        Spacer(1, 0.6 * cm),
        P(f.get("claimant_name", "______________________"), s["body"]),
        P("(Claimant / Authorized Representative)", s["small"]),
    ]

    doc.build(story)
    return out


# ── FIR escalation pack ───────────────────────────────────────────────────────

def _complaint_header(story, s, title, addressee_lines):
    story += [P(title, s["title"]), P(f"Date: {_today()}", s["body"]), _hr()]
    story += [P("To,", s["body"])]
    for line in addressee_lines:
        story += [P(line, s["body"])]
    story += [Spacer(1, 0.3 * cm)]


def _complainant_block(story, s, f):
    story += [
        Spacer(1, 0.5 * cm),
        P("Complainant:", s["heading"]),
        P(f.get("complainant_name", ""), s["body"]),
        P(f"CNIC: {f.get('complainant_cnic', '_______________')}", s["body"]),
        P(f"Address: {f.get('complainant_address', '')}", s["body"]),
        P(f"Contact: {f.get('complainant_phone', '')}", s["body"]),
        Spacer(1, 0.5 * cm),
        P("______________________", s["body"]),
        P("Signature / Thumb impression", s["small"]),
    ]


def fir_application(doc_id: str, f: dict) -> Path:
    """Application for registration of FIR under section 154 CrPC (to the SHO)."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    _complaint_header(story, s, "APPLICATION FOR REGISTRATION OF FIR<br/>(Under Section 154, Code of Criminal Procedure, 1898)", [
        "The Station House Officer (SHO),",
        f"Police Station {f.get('police_station', '____________')},",
        f"District {f.get('district', '____________')}.",
    ])

    story += [
        P("SUBJECT: REGISTRATION OF FIR REGARDING A COGNIZABLE OFFENCE", s["heading"]),
        Spacer(1, 0.2 * cm),
        P("Respected Sir/Madam,", s["body"]),
        P(
            f"It is submitted that on <b>{f.get('incident_date', '__________')}</b>"
            + (f" at approximately {f['incident_time']}" if f.get("incident_time") else "")
            + f", at <b>{f.get('incident_place', '__________')}</b>, the following occurred:", s["body"]),
        P(f.get("incident_facts", ""), s["body"]),
        Spacer(1, 0.2 * cm),
    ]
    if f.get("accused_details"):
        story += [P("Particulars of the accused:", s["heading"]), P(f["accused_details"], s["body"]), Spacer(1, 0.2 * cm)]
    if f.get("witnesses"):
        story += [P("Witnesses:", s["heading"]), P(f["witnesses"], s["body"]), Spacer(1, 0.2 * cm)]
    story += [
        P(
            "The above discloses the commission of a cognizable offence"
            + (f" (including under {f['offence_sections']})" if f.get("offence_sections") else "")
            + ". Under section 154 CrPC you are bound to record the information and register an FIR. "
            "It is therefore respectfully requested that an FIR be registered forthwith and a copy "
            "provided to the complainant free of cost as required by law.", s["body"]),
    ]
    _complainant_block(story, s, f)
    doc.build(story)
    return out


def complaint_154_3(doc_id: str, f: dict) -> Path:
    """Escalation to the SP/DPO under section 154(3) CrPC when the SHO refuses."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    _complaint_header(story, s, "COMPLAINT UNDER SECTION 154(3), CrPC 1898<br/>(Non-registration of FIR by the SHO)", [
        "The Superintendent of Police / District Police Officer,",
        f"District {f.get('district', '____________')}.",
    ])

    story += [
        P("SUBJECT: FAILURE OF SHO TO REGISTER FIR — REQUEST FOR DIRECTION", s["heading"]),
        Spacer(1, 0.2 * cm),
        P("Respected Sir/Madam,", s["body"]),
        P(
            f"On <b>{f.get('application_date', '__________')}</b> the complainant submitted a written application "
            f"for registration of an FIR to the SHO, Police Station <b>{f.get('police_station', '__________')}</b>, "
            "regarding a cognizable offence. Despite the mandatory duty under section 154 CrPC, no FIR has been "
            "registered to date.", s["body"]),
        P("Brief facts of the offence:", s["heading"]),
        P(f.get("incident_facts", ""), s["body"]),
        Spacer(1, 0.2 * cm),
        P(
            "Under section 154(3) CrPC, where an SHO refuses to record information of a cognizable offence, the "
            "aggrieved person may send it in writing to the Superintendent of Police, who, if satisfied that a "
            "cognizable offence is disclosed, shall either investigate the case personally or direct an "
            "investigation. It is therefore prayed that the SHO concerned be directed to register the FIR "
            "immediately and action be taken against the delinquent official for dereliction of duty.", s["body"]),
    ]
    _complainant_block(story, s, f)
    doc.build(story)
    return out


def petition_22a(doc_id: str, f: dict) -> Path:
    """Petition to the Ex-Officio Justice of Peace under section 22-A(6) CrPC."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    story += [
        P(f"IN THE COURT OF THE LEARNED SESSIONS JUDGE / EX-OFFICIO JUSTICE OF PEACE,<br/>{f.get('district', '____________').upper()}", s["title"]),
        P("Petition under Section 22-A(6), Code of Criminal Procedure, 1898", ParagraphStyle("c", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]
    story += _field("Petitioner", f.get("complainant_name", "") + (f", {f.get('complainant_address', '')}" if f.get("complainant_address") else ""), s)
    story += _field("Respondents", f"1. SHO, Police Station {f.get('police_station', '__________')}   2. {f.get('accused_details', 'Accused (as per facts)')}" , s)
    story += [_hr(), P("RESPECTFULLY SHEWETH:", s["heading"])]

    paras = [
        f"1. That on {f.get('incident_date', '__________')} a cognizable offence was committed against the petitioner at {f.get('incident_place', '__________')}, as follows: {f.get('incident_facts', '')}",
        f"2. That the petitioner applied to the SHO, Police Station {f.get('police_station', '__________')}, on {f.get('application_date', '__________')} for registration of an FIR, but the FIR has not been registered.",
        f"3. That the petitioner thereafter approached the Superintendent of Police under section 154(3) CrPC on {f.get('sp_complaint_date', '__________')}, again without result." if f.get("sp_complaint_date") else "3. That the police have failed in their statutory duty despite the disclosure of a cognizable offence.",
        "4. That under section 22-A(6) CrPC this Honourable Court, as Ex-Officio Justice of Peace, is empowered to issue appropriate directions to the police authorities on a complaint of non-registration of a criminal case.",
    ]
    for p in paras:
        story += [P(p, s["body"]), Spacer(1, 0.15 * cm)]

    story += [
        P("PRAYER", s["heading"]),
        P(
            "It is therefore respectfully prayed that the respondent SHO be directed to record the statement of "
            "the petitioner and register an FIR in accordance with law, and any other relief this Honourable "
            "Court deems fit may also be granted.", s["body"]),
    ]
    _complainant_block(story, s, f)
    doc.build(story)
    return out


def fia_cybercrime(doc_id: str, f: dict) -> Path:
    """Complaint to the FIA Cybercrime Wing (NR3C) under PECA 2016."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    _complaint_header(story, s, "COMPLAINT TO THE FIA CYBERCRIME WING (NR3C)<br/>(Under the Prevention of Electronic Crimes Act, 2016)", [
        "The Director / Deputy Director,",
        "Cybercrime Wing (NR3C), Federal Investigation Agency,",
        f"Cybercrime Reporting Centre, {f.get('fia_office_city', '____________')}.",
    ])

    story += [
        P("SUBJECT: COMPLAINT OF AN OFFENCE UNDER PECA 2016", s["heading"]),
        Spacer(1, 0.2 * cm),
        P("Respected Sir/Madam,", s["body"]),
        P(
            f"It is submitted that since <b>{f.get('incident_date', '__________')}</b> the complainant has been "
            f"subjected to the following conduct through electronic means"
            + (f" (platform: <b>{f['platform']}</b>)" if f.get("platform") else "")
            + ":", s["body"]),
        P(f.get("incident_facts", ""), s["body"]),
        Spacer(1, 0.2 * cm),
    ]
    if f.get("accused_details"):
        story += [P("Particulars of the accused (if known):", s["heading"]), P(f["accused_details"], s["body"]), Spacer(1, 0.2 * cm)]
    if f.get("evidence_list"):
        story += [P("Evidence available (screenshots, URLs, numbers, transaction records):", s["heading"]), P(f["evidence_list"], s["body"]), Spacer(1, 0.2 * cm)]
    story += [
        P(
            "The above conduct constitutes one or more offences under the Prevention of Electronic Crimes Act, 2016"
            + (f", including {f['offence_sections']}" if f.get("offence_sections") else
               " (such as sections 20 — offences against dignity, 21 — offences against modesty, and 24 — cyberstalking)")
            + ". It is respectfully requested that this complaint be registered, the material preserved and secured, "
            "and an enquiry/investigation initiated in accordance with law. The complainant requests that their "
            "identity be treated confidentially to the extent the law allows.", s["body"]),
    ]
    _complainant_block(story, s, f)
    doc.build(story)
    return out


# ── Dispatcher ────────────────────────────────────────────────────────────────

_DRAFT_BANNER = (
    "DRAFT FOR LEGAL REVIEW — This is an unexecuted draft generated by Attorney.AI. It is NOT "
    "valid until signed, notarised, attested by the Pakistan Mission and the Ministry of Foreign "
    "Affairs, and (for property) registered before the Sub-Registrar. Have it reviewed by a "
    "qualified Pakistani lawyer before use."
)


def _draft_banner(s):
    return P(f"<b>{_DRAFT_BANNER}</b>", ParagraphStyle(
        "draftbanner", parent=s["small"], textColor=colors.HexColor("#B00020"),
        borderColor=colors.HexColor("#B00020"), borderWidth=0.8, borderPadding=6, spaceAfter=10))


def bail_application(doc_id: str, f: dict) -> Path:
    """Bail application under s.497 (post-arrest) or s.498 (pre-arrest) CrPC."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    pre = bool(f.get("pre_arrest"))
    section = "498" if pre else "497"
    kind = "PRE-ARREST" if pre else "POST-ARREST"

    story += [
        P(f"IN THE COURT OF {f.get('court_name', 'THE SESSIONS JUDGE').upper()}", s["title"]),
        P(f"Bail Application No. _______ of {datetime.now(timezone.utc).year}",
          ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]
    story += _field("Applicant / Accused", f.get("accused_name", "") + (f", {f.get('accused_address', '')}" if f.get("accused_address") else ""), s)
    story += _field("Versus", "The State", s)
    story += _field("FIR", " · ".join(x for x in [
        f"No. {f.get('fir_no')}" if f.get("fir_no") else "",
        f"P.S. {f.get('police_station')}" if f.get("police_station") else "",
        f"dated {f.get('fir_date')}" if f.get("fir_date") else "",
    ] if x), s)
    story += _field("Offence under", f.get("offence_sections", ""), s)
    story += [_hr()]

    story += [
        P(f"APPLICATION FOR {kind} BAIL UNDER SECTION {section} Cr.P.C.", s["heading"]),
        Spacer(1, 0.2 * cm),
        P("Respectfully Sheweth:", s["body"]),
    ]
    grounds = f.get("grounds") or [
        "That the applicant is innocent and has been falsely implicated in the case.",
        "That there is no reasonable ground to believe the applicant has committed a non-bailable offence; the case calls for further inquiry into the guilt of the applicant (s.497(2) Cr.P.C.).",
        "That the applicant is a respectable citizen with no prior criminal record and will not abscond or tamper with the evidence.",
        "That the applicant undertakes to join the investigation / trial and abide by any conditions imposed by this Honourable Court.",
    ]
    for i, g in enumerate(grounds, 1):
        story += [P(f"{i}. {g}", s["body"])]

    story += [
        Spacer(1, 0.3 * cm),
        P("PRAYER", s["heading"]),
        P(f"It is therefore respectfully prayed that the applicant may kindly be granted {kind.lower()} bail in "
          f"the interest of justice.", s["body"]),
        Spacer(1, 0.8 * cm),
        P(f"Date: {f.get('date', _today())}", s["body"]),
        Spacer(1, 0.4 * cm),
        P("______________________", s["body"]),
        P("Applicant / through counsel", s["small"]),
        Spacer(1, 0.4 * cm),
        P("This is a draft for review by a qualified lawyer. Bail is granted at the discretion of the court; "
          "this document does not guarantee any outcome.", s["footer"]),
    ]
    doc.build(story)
    return out


def labour_demand(doc_id: str, f: dict) -> Path:
    """Demand notice to an employer for unpaid labour dues (gratuity/wages/etc.)."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []
    calc = f.get("calculation") or {}

    story += [
        P("LEGAL NOTICE — DEMAND FOR UNPAID LABOUR DUES", s["title"]),
        P(f"Date: {f.get('date', _today())}", ParagraphStyle("left", parent=s["body"], alignment=TA_LEFT)),
        _hr(),
    ]
    story += _field("From (Worker)", f.get("worker_name", "") + (f"\n{f.get('worker_address', '')}" if f.get("worker_address") else ""), s)
    story += _field("To (Employer)", f.get("employer_name", "") + (f"\n{f.get('employer_address', '')}" if f.get("employer_address") else ""), s)
    if f.get("designation") or f.get("employment_period"):
        story += _field("Employment", " · ".join(x for x in [f.get("designation", ""), f.get("employment_period", "")] if x), s)
    story += [_hr(), P("AMOUNTS DEMANDED", s["heading"]), Spacer(1, 0.15 * cm)]

    rows = [["Item", "Amount (PKR)"]]
    for r in calc.get("breakdown", []):
        rows.append([P(r.get("item", "") + (f"<br/><font size=7 color=grey>{r['note']}</font>" if r.get("note") else ""), s["body"]),
                     f"{int(r.get('amount', 0)):,}"])
    rows.append([P("<b>TOTAL</b>", s["body"]), f"{int(calc.get('total', 0)):,}"])
    tb = Table(rows, colWidths=[11.5 * cm, 4 * cm])
    tb.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story += [tb, Spacer(1, 0.4 * cm)]

    story += [
        P("DEMAND", s["heading"]),
        P(f"You are hereby called upon to pay the above sum of <b>PKR {int(calc.get('total', 0)):,}</b> "
          f"within <b>{f.get('response_days', '15')} days</b> of receipt of this notice, failing which the "
          f"undersigned shall be constrained to initiate proceedings before the Labour Court / the authority "
          f"under the Payment of Wages Act, 1936, entirely at your risk as to cost and consequences.", s["body"]),
        Spacer(1, 0.3 * cm),
        P("LEGAL BASIS", s["heading"]),
        P(calc.get("legal_basis", ""), s["body"]),
        Spacer(1, 0.8 * cm),
        P("Yours faithfully,", s["body"]),
        Spacer(1, 0.5 * cm),
        P(f.get("worker_name", "______________________"), s["body"]),
        P("(Worker / through counsel)", s["small"]),
        Spacer(1, 0.4 * cm),
        P(calc.get("disclaimer", ""), s["footer"]),
    ]
    doc.build(story)
    return out


def power_of_attorney(doc_id: str, f: dict) -> Path:
    """Special or General Power of Attorney for an overseas principal."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []
    is_special = (f.get("poa_type") or "special") == "special"
    title = ("SPECIAL POWER OF ATTORNEY" if is_special else "GENERAL POWER OF ATTORNEY")

    story += [
        _draft_banner(s),
        P(title, s["title"]),
        P(f"Date: {f.get('issue_date') or _today()}"
          + (f" &nbsp;&nbsp; Executed at: {f.get('country_of_execution')}" if f.get("country_of_execution") else ""),
          ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += [P("PRINCIPAL (Executant)", s["heading"])]
    story += _field("Name", f.get("principal_name", ""), s)
    if f.get("principal_cnic"):
        story += _field("CNIC / NICOP", f.get("principal_cnic", ""), s)
    story += _field("Residing at", f.get("principal_address", "") + (f", {f.get('country_of_execution')}" if f.get("country_of_execution") else ""), s)
    story += [_hr(), P("ATTORNEY (Agent)", s["heading"])]
    story += _field("Name", f.get("attorney_name", ""), s)
    if f.get("attorney_cnic"):
        story += _field("CNIC", f.get("attorney_cnic", ""), s)
    if f.get("attorney_relation"):
        story += _field("Relationship", f.get("attorney_relation", ""), s)
    story += _field("Address in Pakistan", f.get("attorney_address", ""), s)
    story += [_hr()]

    if f.get("subject"):
        story += [P("SUBJECT / PROPERTY", s["heading"]), P(f.get("subject", ""), s["body"]), Spacer(1, 0.2 * cm)]

    story += [P("POWERS GRANTED", s["heading"]),
              P("I hereby appoint the above-named Attorney to do the following acts on my behalf:", s["body"])]
    powers = f.get("powers") or []
    for i, p in enumerate(powers, 1):
        story += [P(f"{i}. {p}", s["body"])]
    if not powers:
        story += [P("1. [Specify the powers granted]", s["body"])]
    story += [Spacer(1, 0.2 * cm)]

    if f.get("restrictions"):
        story += [P("RESTRICTIONS / CONDITIONS", s["heading"]), P(f.get("restrictions", ""), s["body"]), Spacer(1, 0.2 * cm)]

    story += [
        P("GENERAL TERMS", s["heading"]),
        P("1. This Power of Attorney takes effect on execution and remains in force until it is revoked in "
          "writing" + (f" or until {f.get('expiry_date')}" if f.get("expiry_date") else "") + ".", s["body"]),
        P("2. All lawful acts done by the Attorney within the powers above shall be binding on me as if done by me.", s["body"]),
        P("3. The Attorney shall act in my best interest, keep proper accounts, and shall not exceed the powers granted.", s["body"]),
    ]
    if is_special:
        story += [P("4. For any dealing in immovable property, this instrument must be registered before the "
                    "Sub-Registrar under the Registration Act, 1908, with biometric verification, before it is acted upon.", s["body"])]
    story += [Spacer(1, 0.3 * cm)]

    # attestation block
    story += [P("EXECUTION & ATTESTATION", s["heading"]),
              P("Signed by the Principal and to be attested in sequence:", s["body"]), Spacer(1, 0.2 * cm)]
    att = Table([
        ["Principal's signature", "______________________"],
        ["Notary Public (country of residence)", "______________________"],
        ["Pakistan Embassy / Consulate", "______________________"],
        ["Ministry of Foreign Affairs (Pakistan)", "______________________"],
        ["Witness 1", "______________________"],
        ["Witness 2", "______________________"],
    ], colWidths=[8 * cm, 7 * cm], rowHeights=[1.0 * cm] * 6)
    att.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [att, Spacer(1, 0.4 * cm)]
    story += _verify_block(f, s)
    story += [P(_DRAFT_BANNER, s["footer"])]

    doc.build(story)
    return out


def poa_revocation(doc_id: str, f: dict) -> Path:
    """Deed of Revocation of a previously granted Power of Attorney."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = [
        _draft_banner(s),
        P("DEED OF REVOCATION OF POWER OF ATTORNEY", s["title"]),
        P(f"Date: {f.get('date') or _today()}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]
    story += _field("Principal", f.get("principal_name", ""), s)
    story += _field("Attorney whose authority is revoked", f.get("attorney_name", ""), s)
    if f.get("subject"):
        story += _field("Subject / property", f.get("subject", ""), s)
    if f.get("original_date"):
        story += _field("Original POA dated", f.get("original_date", ""), s)
    story += [
        _hr(),
        P("I, the above-named Principal, hereby REVOKE, cancel and withdraw the Power of Attorney described "
          "above, together with all powers and authorities granted thereunder, with immediate effect. The "
          "Attorney shall forthwith cease to act on my behalf and return all documents in his/her possession.", s["body"]),
        Spacer(1, 0.3 * cm),
        P("Notice of this revocation shall be given to the Attorney and to any authority, registrar or bank "
          "before whom the original Power of Attorney may have been submitted.", s["body"]),
        Spacer(1, 0.6 * cm),
        P("Principal's signature: ______________________", s["body"]),
    ]
    # Same verify link as the original POA — scanning this deed lands on the record,
    # which now reads REVOKED. Closes the "forge/misrepresent the revocation" vector.
    story += _verify_block(f, s)
    story += [Spacer(1, 0.2 * cm), P(_DRAFT_BANNER, s["footer"])]
    doc.build(story)
    return out


def dispute_petition(doc_id: str, f: dict) -> Path:
    """DRAFT petition to the Special Court under the Protection of Overseas Pakistanis'
    Property Act 2024. English-only this pass. The facts/cause are drafted upstream
    (grounded, structured); this only lays them out with a non-removable DRAFT banner."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = [
        _draft_banner(s),
        P(f.get("court_heading", "IN THE SPECIAL COURT (OVERSEAS PAKISTANIS' PROPERTY)"), s["title"]),
        P(f"Petition No. ______ of {f.get('year') or _today()[-4:]}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += [P("PARTIES", s["heading"])]
    story += _field("Petitioner", f.get("petitioner", ""), s)
    story += _field("Respondent", f.get("respondent", ""), s)
    story += [_hr(), P("JURISDICTION", s["heading"]), P(f.get("jurisdiction_clause", ""), s["body"]), Spacer(1, 0.2 * cm)]

    story += [P("STATEMENT OF FACTS", s["heading"])]
    for i, fact in enumerate(f.get("facts") or [], 1):
        story += [P(f"{i}. {fact}", s["body"])]
    if not f.get("facts"):
        story += [P("[Facts to be provided]", s["body"])]
    story += [Spacer(1, 0.2 * cm)]

    story += [P("CAUSE OF ACTION", s["heading"]), P(f.get("cause_of_action", ""), s["body"]), Spacer(1, 0.2 * cm)]

    story += [P("PRAYER (RELIEF SOUGHT)", s["heading"]),
              P("The Petitioner respectfully prays that this Honourable Court be pleased to:", s["body"]),
              P(f"(a) {f.get('relief', '')};", s["body"]),
              P("(b) grant such other or further relief as this Honourable Court deems just and proper.", s["body"]),
              Spacer(1, 0.3 * cm)]

    story += [P("VERIFICATION", s["heading"]),
              P("Verified at __________ on this ______ day of __________, 20____, that the contents of "
                "this petition are true and correct to the best of the Petitioner's knowledge and belief, "
                "and nothing material has been concealed.", s["body"]),
              Spacer(1, 0.5 * cm),
              P("Petitioner: ______________________", s["body"]),
              P("Through counsel: ______________________", s["body"]),
              Spacer(1, 0.3 * cm)]

    # Procedural note — carried straight from the resolver so it cannot drop.
    note = f.get("timing_note")
    if note:
        story += [_hr(), P("PROCEDURAL NOTE", s["heading"]), P(note, s["footer"]), Spacer(1, 0.2 * cm)]

    story += [P(_DRAFT_BANNER, s["footer"])]
    doc.build(story)
    return out


def wasiyyat_nama(doc_id: str, f: dict) -> Path:
    """Wasiyyat Nama — an Islamic will. Bequests are capped at one-third of the
    net estate; the residue devolves on the legal heirs per Faraid."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []
    comp = f.get("computation") or {}

    story += [
        P("WASIYYAT NAMA", s["title"]),
        P("(Islamic Will — Sunni law, as applied in Pakistan)",
          ParagraphStyle("center", parent=s["small"], alignment=TA_CENTER)),
        P(f"Date: {f.get('date', _today())}" + (f" &nbsp;&nbsp; Place: {f.get('place')}" if f.get("place") else ""),
          ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    testator = f.get("testator_name", "") or "____________________"
    ident = ", ".join(x for x in [
        f"son/daughter of {f.get('testator_father_name')}" if f.get("testator_father_name") else "",
        f"CNIC {f.get('testator_cnic')}" if f.get("testator_cnic") else "",
        f.get("testator_address", ""),
    ] if x)
    story += [
        P(f"I, <b>{testator}</b>{(', ' + ident) if ident else ''}, being of sound mind and free will, "
          f"make this Wasiyyat (will) in accordance with the Islamic law as applied in Pakistan.", s["body"]),
        Spacer(1, 0.2 * cm),
        P("1. REVOCATION", s["heading"]),
        P("I revoke all wills and codicils previously made by me.", s["body"]),
        Spacer(1, 0.15 * cm),
    ]

    # Executor / guardian / funeral
    story += [P("2. EXECUTOR (WASI)", s["heading"])]
    if f.get("executor_name"):
        story += [P(f"I appoint <b>{f['executor_name']}</b>"
                    + (f" ({f.get('executor_relation')})" if f.get("executor_relation") else "")
                    + " as the executor (wasi) of this will, to pay my funeral expenses and debts and to "
                      "distribute my estate as set out below.", s["body"])]
    else:
        story += [P("I appoint ____________________ as the executor (wasi) of this will.", s["body"])]
    story += [Spacer(1, 0.15 * cm)]

    if f.get("guardian_name"):
        story += [P("3. GUARDIAN OF MINOR CHILDREN", s["heading"]),
                  P(f"I appoint <b>{f['guardian_name']}</b> as guardian of my minor children.", s["body"]),
                  Spacer(1, 0.15 * cm)]
    if f.get("funeral_instructions"):
        story += [P("FUNERAL INSTRUCTIONS", s["heading"]),
                  P(f.get("funeral_instructions", ""), s["body"]), Spacer(1, 0.15 * cm)]

    # Estate summary
    story += [_hr(), P("ESTATE SUMMARY", s["heading"])]
    story += _field("Gross estate", f"PKR {int(comp.get('gross_estate', 0)):,}", s)
    if comp.get("funeral_expenses"):
        story += _field("Less: funeral expenses", f"PKR {int(comp['funeral_expenses']):,}", s)
    if comp.get("debts"):
        story += _field("Less: debts", f"PKR {int(comp['debts']):,}", s)
    story += _field("Net estate", f"PKR {int(comp.get('net_estate', 0)):,}", s)
    story += _field("One-third bequeathable limit", f"PKR {int(comp.get('one_third_limit', 0)):,}", s)

    # Bequests table
    beq = comp.get("bequests", [])
    if beq:
        story += [Spacer(1, 0.15 * cm), P("4. BEQUESTS (WASIYYAT)", s["heading"])]
        rows = [["Beneficiary", "Amount (PKR)", "Status"]]
        _status_label = {
            "valid": "Valid (within 1/3)",
            "exceeds_one_third_needs_consent": "Excess — needs heirs' consent",
            "to_heir_needs_consent": "To an heir — needs heirs' consent",
        }
        for b in beq:
            who = b.get("beneficiary", "") + (f" ({b['relation']})" if b.get("relation") else "")
            amt = b.get("honoured") if b.get("status") == "valid" else b.get("amount", 0)
            rows.append([P(who, s["body"]), f"{int(amt):,}", _status_label.get(b.get("status", ""), "")])
        tb = Table(rows, colWidths=[7.5 * cm, 3 * cm, 5 * cm])
        tb.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        story += [tb, Spacer(1, 0.2 * cm),
                  P("Note: total bequests may not exceed one-third of the net estate without the consent of "
                    "all legal heirs. A bequest to a legal heir is valid only with such consent.", s["small"])]

    # Residue clause
    story += [Spacer(1, 0.15 * cm), P("5. RESIDUE", s["heading"]),
              P("The remaining estate, after payment of funeral expenses, debts and the valid bequests above, "
                "shall devolve upon my legal heirs in accordance with the Islamic law of inheritance (Faraid) "
                "as applied in Pakistan (Muslim Personal Law (Shariat) Application Act, 1962, read with the "
                "Muslim Family Laws Ordinance, 1961).", s["body"])]

    faraid = comp.get("faraid")
    if faraid and faraid.get("breakdown"):
        rows = [["Heir", "Share", "%", "Amount (PKR)"]]
        for r in faraid["breakdown"]:
            rows.append([P(r.get("heir", ""), s["body"]), r.get("fraction", ""),
                         f"{r.get('percentage', 0)}%", f"{int(r.get('amount', 0)):,}"])
        tb = Table(rows, colWidths=[7.5 * cm, 2.4 * cm, 2.1 * cm, 3.4 * cm])
        tb.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ]))
        story += [Spacer(1, 0.15 * cm), P(f"Residue distributed (PKR {int(comp.get('residue', 0)):,}):", s["small"]), tb]

    # Signatures
    story += [Spacer(1, 0.5 * cm), P("EXECUTION", s["heading"]),
              P("Signed by the testator in the presence of the two witnesses below, who signed in the "
                "testator's presence. Executed electronically under the Electronic Transactions Ordinance, 2002.", s["body"]),
              Spacer(1, 0.4 * cm)]
    sig_rows = [
        ["Testator", f.get("testator_name", ""), "Signature: ______________"],
        ["Witness 1", f.get("witness1_name", ""), "Signature: ______________"],
        ["Witness 2", f.get("witness2_name", ""), "Signature: ______________"],
    ]
    sg = Table(sig_rows, colWidths=[3 * cm, 6 * cm, 6 * cm], rowHeights=[1.1 * cm] * 3)
    sg.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [sg, Spacer(1, 0.4 * cm), P(comp.get("disclaimer", ""), s["footer"])]

    doc.build(story)
    return out


def payment_receipt(doc_id: str, f: dict) -> Path:
    """Payment receipt — rendered entirely from the payment doc's frozen
    snapshots so it is reproducible and never shifts with later data changes."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    cur = f.get("currency", "PKR")
    amount = float(f.get("amount", 0))
    fee = float(f.get("platform_fee", 0))
    net = float(f.get("net_to_payee", amount - fee))
    is_sub = f.get("kind") == "subscription"

    story += [
        P("PAYMENT RECEIPT", s["title"]),
        P("Attorney.AI", ParagraphStyle("center", parent=s["small"], alignment=TA_CENTER)),
        _hr(),
        Spacer(1, 0.2 * cm),
    ]
    story += _field("Receipt No.", f.get("id", doc_id), s)
    story += _field("Date", f.get("paid_date", _today()), s)
    story += _field("Status", (f.get("status", "paid")).upper(), s)
    story += [_hr()]

    story += _field("Paid By", f.get("payer_name", "—"), s)
    story += _field("Paid To", f.get("payee_name", "Attorney.AI"), s)
    if f.get("case_title"):
        story += _field("Matter", f"{f.get('case_title','')} {('(' + f.get('case_number','') + ')') if f.get('case_number') else ''}".strip(), s)
    story += _field("Purpose", (f.get("purpose", "") or "").replace("_", " ").title(), s)
    story += [_hr()]

    story += [P("AMOUNT", s["heading"])]
    story += _field("Amount Paid", f"{cur} {amount:,.0f}", s)
    if not is_sub:
        story += _field("Platform Fee", f"{cur} {fee:,.0f} ({float(f.get('take_rate',0))*100:.1f}%)", s)
        story += _field("Net to Advocate", f"{cur} {net:,.0f}", s)
    story += [
        Spacer(1, 0.6 * cm),
        _hr(),
        P("This is a computer-generated receipt and is valid without signature. "
          "Payment processed electronically under the Electronic Transactions Ordinance 2002.",
          s["footer"]),
    ]

    doc.build(story)
    return out


def urdu_pleading(doc_id: str, f: dict) -> Path:
    """Render a court-register Urdu pleading (RTL, Noto Naskh).

    Fields:
      urdu_text     — the translated Urdu body (paragraphs separated by newlines)
      title_ur      — optional Urdu heading (centred)
      court_ur      — optional Urdu court line (centred)
      english_label — optional English caption for the document type
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    ur_center = ParagraphStyle("ur_center", parent=s["title"], fontSize=15)
    ur_court = ParagraphStyle("ur_court", parent=s["heading"], alignment=TA_CENTER)

    if f.get("court_ur"):
        story += [P(f.get("court_ur"), ur_court), Spacer(1, 0.15 * cm)]
    if f.get("title_ur"):
        story += [P(f.get("title_ur"), ur_center)]
    if f.get("english_label"):
        story += [P(f.get("english_label"), s["small"])]
    story += [_hr(), Spacer(1, 0.2 * cm)]

    body = (f.get("urdu_text") or "").replace("\r\n", "\n")
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            story += [Spacer(1, 0.2 * cm)]
            continue
        story += [P(line, s["body"])]

    story += [
        Spacer(1, 0.6 * cm),
        _hr(),
        P("Machine-assisted translation into court Urdu — review and verify before filing. "
          "یہ عدالتی اردو میں مشین کی مدد سے کیا گیا ترجمہ ہے؛ داخل کرنے سے پہلے نظرثانی کریں۔",
          s["footer"]),
    ]

    doc.build(story)
    return out


def guardianship_petition(doc_id: str, f: dict) -> Path:
    """Petition under s.10, Guardians and Wards Act 1890.

    PROVENANCE. Laid out from the Act itself — s.10(1) enumerates, in clauses
    (a) to (l), the particulars the petition must state, and s.10(3) requires an
    accompanying declaration of willingness. The order of the sections below
    follows the order of those clauses, so the document can be read against the
    statute line by line.

    It is NOT copied from any court's published guardianship proforma. LHC
    asserts copyright over its site material and asks that it not be downloaded
    without prior agreement; IHC's site disclaims its content as "just for
    Information", not for official use. Statutory requirements are law and carry
    no such restriction, so the Act is the only source used here.

    A particular the petitioner has not supplied is printed as an explicit
    "[not stated]" rather than silently dropped. s.10(1) requires the petition to
    state these things "so far as can be ascertained" — a blank line hides the
    gap from the judge and from the petitioner, while a marked gap is something
    the compliance report can also point at.
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    out = UPLOADS_DIR / f"{doc_id}.pdf"
    s = _styles()
    doc = _base_doc(out)
    story = []

    # Numbered dynamically. A conditional clause that does not apply must not
    # leave a hole in the sequence — a petition that jumps from 1 to 3 reads to
    # a judge like a page went missing.
    n = [0]

    def head(label: str) -> str:
        n[0] += 1
        return f"{n[0]}. {label}"

    def stated(key: str) -> str:
        v = (f.get(key) or "").strip() if isinstance(f.get(key), str) else f.get(key)
        return v if v else "[not stated]"

    story += [
        P(f"IN THE {(f.get('court_name') or 'DISTRICT COURT').upper()}", s["title"]),
        P(f"GUARDIAN CASE NO. _______ / {datetime.now(timezone.utc).year}",
          ParagraphStyle("gc", parent=s["body"], alignment=TA_CENTER)),
        P("PETITION UNDER SECTION 10 OF THE GUARDIANS AND WARDS ACT, 1890",
          ParagraphStyle("gs", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Petitioner", (f.get("petitioner_name") or "")
                    + (f", {f.get('petitioner_address')}" if f.get("petitioner_address") else ""), s)
    if f.get("petitioner_relation"):
        story += _field("Relationship to the minor", f["petitioner_relation"], s)
    story += [_hr()]

    # s.10(1)(a)
    story += [P(head("PARTICULARS OF THE MINOR"), s["heading"]),
              P(f"Name: {stated('minor_name')} &nbsp;&nbsp; Sex: {stated('minor_sex')}", s["body"]),
              P(f"Religion: {stated('minor_religion')} &nbsp;&nbsp; "
                f"Date of birth: {stated('minor_dob')}", s["body"]),
              P(f"Ordinarily resides at: {stated('minor_residence')}", s["body"])]

    # s.10(1)(b) — only where the minor is female
    if (f.get("minor_sex") or "").strip().lower().startswith("f") or f.get("minor_marital_status"):
        story += [P(head("MARITAL STATUS OF THE MINOR (s.10(1)(b))"), s["heading"]),
                  P(stated("minor_marital_status"), s["body"])]

    # s.10(1)(c)
    story += [P(head("PROPERTY OF THE MINOR (s.10(1)(c))"), s["heading"]),
              P(f.get("minor_property") or "The minor is not stated to own property.", s["body"])]

    # s.10(1)(d), (e)
    story += [P(head("CUSTODY AND RELATIONS"), s["heading"]),
              P(f"Person having custody or possession: {stated('custodian_name_address')}", s["body"]),
              P(f"Near relations of the minor and where they reside: {stated('near_relations')}", s["body"])]

    # s.10(1)(f), (g)
    story += [P(head("EXISTING AND PREVIOUS GUARDIANSHIP"), s["heading"]),
              P(f"Guardian already appointed or declared: {stated('existing_guardian')}", s["body"]),
              P(f"Previous applications to this or any other Court: "
                f"{stated('previous_applications')}", s["body"])]

    # s.10(1)(h), (i), (j)
    story += [P(head("NATURE OF THIS APPLICATION"), s["heading"]),
              P(f"Guardianship sought of: {stated('application_scope')}", s["body"])]
    if f.get("proposed_guardian_qualifications"):
        story += [P(f"Qualifications of the proposed guardian: "
                    f"{f['proposed_guardian_qualifications']}", s["body"])]
    if f.get("declaration_grounds"):
        story += [P(f"Grounds on which guardianship is claimed: "
                    f"{f['declaration_grounds']}", s["body"])]

    # s.10(1)(k)
    story += [P(head("CAUSES LEADING TO THIS APPLICATION (s.10(1)(k))"), s["heading"]),
              P(stated("causes"), s["body"])]

    # s.17 is the Court's test; naming it keeps the prayer honest about what is
    # actually being asked and on what basis.
    story += [P(head("PRAYER"), s["heading"]),
              P("It is respectfully prayed that this Honourable Court may be pleased to "
                "appoint or declare the petitioner as guardian as sought above, the same "
                "being for the welfare of the minor within the meaning of section 17 of "
                "the Guardians and Wards Act, 1890.", s["body"])]

    story += [_hr(),
              P(f"Date: {f.get('date', _today())}", s["body"]),
              Spacer(1, 0.8 * cm),
              P("______________________", s["body"]),
              P(f.get("petitioner_name", "Petitioner"), s["small"])]

    # s.10(1) requires verification as for a plaint under the CPC.
    story += [Spacer(1, 0.4 * cm),
              P("VERIFICATION", s["heading"]),
              P("Verified on oath at ____________ on ____________ that the contents of "
                "this petition are true and correct to the best of my knowledge and "
                "belief, and that nothing material has been concealed.", s["body"]),
              Spacer(1, 0.6 * cm),
              P("______________________", s["body"]),
              P("Petitioner", s["small"])]

    # s.10(3) — a separate instrument, so it is flagged rather than fabricated.
    story += [Spacer(1, 0.4 * cm),
              P("ACCOMPANYING DECLARATION (s.10(3))", s["heading"]),
              P(f.get("willingness_declaration")
                or "NOT ATTACHED. Section 10(3) requires this petition to be accompanied "
                   "by a declaration of the proposed guardian's willingness to act, signed "
                   "by them and attested by at least two witnesses.", s["small"])]

    doc.build(story)
    return out

_GENERATORS = {
    "payment_receipt":    payment_receipt,
    "urdu_pleading":      urdu_pleading,
    "bail_application":   bail_application,
    "wasiyyat_nama":      wasiyyat_nama,
    "power_of_attorney":  power_of_attorney,
    "poa_revocation":     poa_revocation,
    "dispute_petition":   dispute_petition,
    "labour_demand":      labour_demand,
    "legal_notice":       legal_notice,
    "plaint_civil":       plaint_civil,
    "written_statement":  written_statement,
    "nda":                nda,
    "rental_agreement":   rental_agreement,
    "inheritance_settlement": inheritance_settlement,
    "inheritance_demand":     inheritance_demand,
    "fir_application":        fir_application,
    "complaint_154_3":        complaint_154_3,
    "petition_22a":           petition_22a,
    "fia_cybercrime":         fia_cybercrime,
    "guardianship_petition":  guardianship_petition,
}


def generate_pdf(doc_id: str, template_type: str, fields: dict) -> Path:
    fn = _GENERATORS.get(template_type)
    if not fn:
        raise ValueError(f"Unknown template type: {template_type}")
    return fn(doc_id, fields)
