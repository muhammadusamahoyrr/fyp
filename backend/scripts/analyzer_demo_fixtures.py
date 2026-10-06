"""Three SYNTHETIC demonstration PDFs for the Document Analyzer demo.

    python scripts/analyzer_demo_fixtures.py --out <folder>

Every name, identity number, company, place and amount below is INVENTED for
the demo. The identity numbers use the 999xx prefix, which no real CNIC
uses. Each page carries a "SYNTHETIC DEMONSTRATION DOCUMENT" banner. Nothing
here comes from a client document or any evaluation dataset.

The PDFs are reproducible: the same script writes byte-identical files
(reportlab `invariant=1`, which drops the creation date and random id).

What each document is built to show (the runbook walks through it):
  * local drafting checks: most general checks are located; disputes and
    governing law are deliberately absent, so they read "Not located
    automatically";
  * a blank field ("______") that the drafting notes point at;
  * a fictional name and a fictional identity number, masked before sending;
  * a detail the scanner is not built to catch (a nickname / house name),
    for the lawyer to mark by hand;
  * a nickname or initials for a party ("Fasi", "H.R.M.", "Ashi") that the
    scanner does not connect, for the lawyer to link to that party's name
    (a short surname form such as "Mr. Khan" is linked automatically);
  * an amount and a deadline that stay readable after masking.
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

BANNER = "SYNTHETIC DEMONSTRATION DOCUMENT - fictional names, numbers and places. Not a real agreement."

FIXTURES: dict[str, dict] = {
    "demo_tenancy.pdf": {
        "document_type": "tenancy",
        "title": "TENANCY AGREEMENT",
        "paragraphs": [
            "This Tenancy Agreement is made on 1st March 2026 between Nargis Akhtar, holder of CNIC "
            "99901-2345678-3 (the Landlord), and Faisal Mehmood Khan (the Tenant).",
            "1. The term of this tenancy is eleven (11) months commencing on 1st April 2026.",
            "2. The Tenant shall pay a monthly rent of Rs. 45,000 to the Landlord within 7 days of the start "
            "of each month.",
            "3. The security deposit is Rs. ______ and shall be paid before possession is handed over.",
            "4. Mr. Khan shall not sublet the premises without the written consent of the Landlord.",
            "5. The premises are the upper portion of the house known locally as Gul Kothi, and the keys "
            "shall be collected from the caretaker, Chacha Bashir.",
            "6. Either party may terminate this tenancy by giving one month's written notice.",
            "7. Notices for the Tenant may also be left at the premises, where the neighbours know him as Fasi.",
            "Signed by the Landlord: ______.",
            "Signed by the Tenant: ______.",
        ],
        "terms": {"term_months": 11, "rent_period": "monthly", "tenancy_year_to_year": False},
        "names": ["Nargis Akhtar", "Faisal Mehmood Khan"],
        "identifier": "99901-2345678-3",
        "missed": "Chacha Bashir",
        "alias": ("Fasi", "Faisal Mehmood"),
        "kept": ["Rs. 45,000", "within 7 days"],
    },
    "demo_nda.pdf": {
        "document_type": "nda",
        "title": "MUTUAL NON-DISCLOSURE AGREEMENT",
        "paragraphs": [
            "This Agreement is dated 10 February 2026 between Zarvan Textiles (Private) Limited and "
            "Hamid Raza Malik, holder of CNIC 99902-3456789-5, each a party disclosing and receiving "
            "confidential information.",
            "1. Each party shall keep the Confidential Information of the other party secret for a period "
            "of two (2) years from the date of disclosure.",
            "2. Mr. Malik shall return all documents of Zarvan Textiles within 14 days of a written request.",
            "3. The permitted purpose of the disclosure is ______.",
            "4. A party in breach shall pay Rs. 250,000 as agreed damages.",
            "5. Confidential Information includes the price list kept by the sales clerk known as Pappu "
            "at the Jhang Road warehouse.",
            "6. Either party may terminate this Agreement by written notice; clause 1 survives termination.",
            "7. Hamid Raza Malik shall initial every page of the register as H.R.M. within 3 days of receipt.",
            "Signed for Zarvan Textiles: ______.",
            "Signed by the Receiving Party: ______.",
        ],
        "terms": {"nda_mutual": True, "confidentiality_years": 2, "non_compete": False},
        "names": ["Hamid Raza Malik"],
        "identifier": "99902-3456789-5",
        "missed": "Pappu",
        "alias": ("H.R.M.", "Hamid Raza"),
        "kept": ["Rs. 250,000", "within 14 days"],
    },
    "demo_employment.pdf": {
        "document_type": "employment",
        "title": "LETTER OF APPOINTMENT",
        "paragraphs": [
            "Dated 5 January 2026. This letter of appointment is between Northgate Logistics (Private) "
            "Limited (the Employer) and Ayesha Siddiqui, holder of CNIC 99903-4567890-7 (the Employee).",
            "1. The Employee will be on probation for a period of three (3) months from the date of joining.",
            "2. The Employer shall pay the Employee a monthly salary of Rs. 120,000 within 5 days of the end "
            "of each month.",
            "3. The Employee's reporting manager will be ______.",
            "4. Ms. Siddiqui must confirm her acceptance of this offer within 10 days of the date of this letter.",
            "5. The Employee will share the night-shift desk with the supervisor everyone calls Guddu Bhai.",
            "6. Either party may terminate the employment by giving thirty (30) days' notice in writing.",
            "7. Leave requests from the Employee, whom colleagues call Ashi, go to the Employer.",
            "Signed for the Employer: ______.",
            "Signed by the Employee: ______.",
        ],
        "terms": {"probation_months": 3, "notice_days": 30, "non_compete": False},
        "names": ["Ayesha Siddiqui"],
        "identifier": "99903-4567890-7",
        "missed": "Guddu Bhai",
        "alias": ("Ashi", "Ayesha"),
        "kept": ["Rs. 120,000", "within 5 days"],
    },
}


def pdf_bytes(spec: dict) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(f"{spec['title']} (synthetic demonstration document)")
    width, height = A4
    c.setFont("Helvetica-Bold", 9)
    c.drawString(56, height - 40, BANNER)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(56, height - 80, spec["title"])
    y = height - 112
    c.setFont("Helvetica", 11)
    for paragraph in spec["paragraphs"]:
        for line in textwrap.wrap(paragraph, 88):
            c.drawString(56, y, line)
            y -= 15
        y -= 9
    c.setFont("Helvetica-Bold", 9)
    c.drawString(56, 40, BANNER)
    c.showPage()
    c.save()
    return buf.getvalue()


def build(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, spec in FIXTURES.items():
        path = out / name
        path.write_bytes(pdf_bytes(spec))
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    for path in build(args.out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
