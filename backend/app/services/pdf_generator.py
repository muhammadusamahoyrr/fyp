"""
pdf_generator.py — Pure-Python PDF generation using reportlab.
No LibreOffice dependency. Each template is a function that returns a PDF bytes.
"""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
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

UPLOADS_DIR = Path(__file__).parents[2] / "uploads" / "docs"

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
        Paragraph(label.upper(), s["label"]),
        Paragraph(value or "—", s["body"]),
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
        Paragraph("LEGAL NOTICE", s["title"]),
        Paragraph(f"Date: {f.get('date', _today())}", ParagraphStyle("right", parent=s["body"], alignment=TA_LEFT)),
        _hr(),
        Spacer(1, 0.3 * cm),
    ]

    story += _field("From", f.get("sender_name", "") + (f"\n{f.get('sender_address', '')}" if f.get("sender_address") else ""), s)
    story += _field("To", f.get("recipient_name", "") + (f"\n{f.get('recipient_address', '')}" if f.get("recipient_address") else ""), s)
    story += [_hr()]

    story += [Paragraph("SUBJECT: LEGAL NOTICE", s["heading"]), Spacer(1, 0.2 * cm)]
    story += [Paragraph(f.get("notice_body", ""), s["body"])]
    story += [Spacer(1, 0.4 * cm)]

    if f.get("demand"):
        story += [
            Paragraph("DEMAND", s["heading"]),
            Paragraph(f.get("demand", ""), s["body"]),
            Spacer(1, 0.3 * cm),
        ]

    story += [
        Paragraph(f"If no response is received within <b>{f.get('response_days', '15')} days</b> of receipt of this notice, legal proceedings shall be initiated without further notice.", s["body"]),
        Spacer(1, 0.8 * cm),
        Paragraph("Yours faithfully,", s["body"]),
        Spacer(1, 0.6 * cm),
        Paragraph(f.get("sender_name", "______________________"), s["body"]),
        Paragraph("(Sender / Authorized Representative)", s["small"]),
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
        Paragraph(f"IN THE {f.get('court_name', 'CIVIL COURT').upper()}", s["title"]),
        Paragraph(f"SUIT NO. _______ / {datetime.now(timezone.utc).year}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Plaintiff", f.get("plaintiff_name", "") + (f", {f.get('plaintiff_address', '')}" if f.get("plaintiff_address") else ""), s)
    story += _field("Defendant", f.get("defendant_name", "") + (f", {f.get("defendant_address", '')}" if f.get("defendant_address") else ""), s)
    story += [_hr()]

    story += [Paragraph("PLAINT", s["title"]), Spacer(1, 0.2 * cm)]
    story += [Paragraph("FACTS OF THE CASE", s["heading"])]
    story += [Paragraph(f.get("facts", ""), s["body"])]
    story += [Spacer(1, 0.3 * cm)]

    if f.get("cause_of_action"):
        story += [Paragraph("CAUSE OF ACTION", s["heading"]), Paragraph(f.get("cause_of_action", ""), s["body"]), Spacer(1, 0.3 * cm)]

    story += [Paragraph("RELIEF SOUGHT", s["heading"]), Paragraph(f.get("relief_sought", ""), s["body"]), Spacer(1, 0.3 * cm)]

    if f.get("applicable_laws"):
        story += [Paragraph("APPLICABLE LAW", s["heading"]), Paragraph(f.get("applicable_laws", ""), s["body"]), Spacer(1, 0.3 * cm)]

    story += [
        _hr(),
        Paragraph(f"Date: {f.get('date', _today())}", s["body"]),
        Spacer(1, 0.8 * cm),
        Paragraph("______________________", s["body"]),
        Paragraph(f.get("plaintiff_name", "Plaintiff"), s["small"]),
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
        Paragraph(f"IN THE {f.get('court_name', 'CIVIL COURT').upper()}", s["title"]),
        Paragraph(f"SUIT NO. {f.get('suit_number', '_______')}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
        _hr(),
    ]

    story += _field("Plaintiff", f.get("plaintiff_name", ""), s)
    story += _field("Defendant", f.get("defendant_name", ""), s)
    story += [_hr()]

    story += [Paragraph("WRITTEN STATEMENT", s["title"]), Spacer(1, 0.2 * cm)]
    story += [Paragraph("PRELIMINARY OBJECTIONS", s["heading"]), Paragraph(f.get("preliminary_objections", ""), s["body"]), Spacer(1, 0.3 * cm)]
    story += [Paragraph("REPLY ON MERITS", s["heading"]), Paragraph(f.get("reply_on_merits", ""), s["body"]), Spacer(1, 0.3 * cm)]

    if f.get("additional_facts"):
        story += [Paragraph("ADDITIONAL FACTS", s["heading"]), Paragraph(f.get("additional_facts", ""), s["body"]), Spacer(1, 0.3 * cm)]

    story += [
        _hr(),
        Paragraph(f"Date: {f.get('date', _today())}", s["body"]),
        Spacer(1, 0.8 * cm),
        Paragraph("______________________", s["body"]),
        Paragraph(f.get("defendant_name", "Defendant"), s["small"]),
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
        Paragraph("NON-DISCLOSURE AGREEMENT", s["title"]),
        Paragraph(f"Date: {f.get('date', _today())}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
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
        story += [Paragraph(heading, s["heading"]), Paragraph(text, s["body"]), Spacer(1, 0.2 * cm)]

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
        Paragraph("TENANCY / RENTAL AGREEMENT", s["title"]),
        Paragraph(f"Date: {f.get('date', _today())}", ParagraphStyle("center", parent=s["body"], alignment=TA_CENTER)),
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

    story += [_hr(), Paragraph("TERMS AND CONDITIONS", s["heading"])]

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
        story += [Paragraph(term, s["body"])]

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


# ── Dispatcher ────────────────────────────────────────────────────────────────

_GENERATORS = {
    "legal_notice":       legal_notice,
    "plaint_civil":       plaint_civil,
    "written_statement":  written_statement,
    "nda":                nda,
    "rental_agreement":   rental_agreement,
}


def generate_pdf(doc_id: str, template_type: str, fields: dict) -> Path:
    fn = _GENERATORS.get(template_type)
    if not fn:
        raise ValueError(f"Unknown template type: {template_type}")
    return fn(doc_id, fields)
