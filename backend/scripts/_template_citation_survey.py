"""What citations does every template actually emit, and can the checker read them?

Generates each template into a TEMPORARY upload root (never the real one),
extracts the text, and compares what the verifier parses against what the text
visibly claims. A template whose citation the parser cannot see is reported as
"no citations found", which reads as approval -- so this survey is the list of
places that lie by omission.
"""
import re
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Sample fields wide enough to drive every generator (mirrors tests/test_v2_stage0).
SAMPLE = {
    "client_name": "A", "lawyer_name": "B", "case_title": "A vs B",
    "court_name": "Civil Court Lahore", "facts": "Facts.", "cause_of_action": "Breach",
    "relief_sought": "Damages", "complainant_name": "A", "incident_facts": "It happened.",
    "police_station": "PS", "district": "Lahore", "incident_date": "1 Jan 2026",
    "incident_place": "Lahore", "application_date": "2 Jan 2026", "minor_name": "C",
    "petitioner_name": "A", "appointer_name": "A", "pleader_name": "B", "party_a": "A",
    "party_b": "B", "purpose": "x", "duration": "2 years", "jurisdiction": "Lahore",
    "landlord_name": "A", "tenant_name": "B", "property_address": "X", "monthly_rent": "1000",
    "security_deposit": "1000", "tenancy_period": "11 months", "start_date": "1 Jan 2026",
    "deceased_name": "D", "testator_name": "D", "principal_name": "A", "agent_name": "B",
    "amount": "1000",
}

# Text that LOOKS like it names a provision. Used only to spot the gap between
# what a template claims and what the parser can see.
LOOKS_CITED = re.compile(
    r"(?:sections?|secs?\.|u/s|articles?|arts?\.)\s*(\d[\w\-]*)", re.I)
NAMES_AN_ACT = re.compile(
    r"\b[A-Z][A-Za-z'()\-]*(?:\s+[A-Za-z'()\-]+){0,6}\s+"
    r"(?:Act|Ordinance|Code)\s*,?\s*(?:\d{4})?")


def main() -> int:
    from app.core.config import settings

    tmp = Path(tempfile.mkdtemp(prefix="tmpl-survey-"))
    settings.upload_root = str(tmp)
    import app.services.pdf_generator as gen
    gen.UPLOADS_DIR = tmp / "docs"

    import app.db.chroma as chroma_mod
    chroma_mod._CHROMA_PATH = BACKEND / "chroma_data"
    chroma_mod.connect_chroma()
    from app.ai.citation_verification import parse_statute_citations, verify_statutes
    from app.ai.corpus_index import get_index
    index = get_index()

    print(f"{'template':26} {'parsed':>6} {'visible':>8}  verdicts / MISSED")
    print("-" * 96)
    blind, clean, actless = [], [], []
    for name, fn in sorted(gen._GENERATORS.items()):
        if name == "payment_receipt":
            continue                      # not a drafting template
        path = fn(f"survey_{name}", dict(SAMPLE))
        try:
            text, _status = gen.extract_pdf_text(path)
        finally:
            Path(path).unlink(missing_ok=True)

        parsed = parse_statute_citations(text, index)
        # DISTINCT section numbers the text names, against those actually
        # parsed. Counting raw mentions hides a PARTIAL miss -- two distinct
        # citations where only one is read -- which is the more dangerous shape,
        # because the report looks populated.
        mentioned = {m.upper().replace(" ", "")
                     for m in LOOKS_CITED.findall(text or "")}
        got = {c.section.upper().replace(" ", "") for c in parsed}
        missed = sorted(mentioned - got)
        visible = sorted(mentioned)
        verdicts = [f"{c.canonical}={c.status[:4]}" for c in verify_statutes(text, None, index)]

        note = ", ".join(verdicts) if verdicts else ""
        if missed:
            note = ("*** MISSED " + ", ".join(missed[:4])
                    + (f"  (reads {len(got)})" if got else "  (reads none)"))
            blind.append(f"{name} [{', '.join(missed[:4])}]")
        elif not visible and not parsed:
            acts = sorted(set(NAMES_AN_ACT.findall(text or "")))
            note = ("act-level only: " + "; ".join(a.strip()[:34] for a in acts[:2])
                    if acts else "no authority named")
            if acts:
                actless.append(name)
        else:
            clean.append(name)
        print(f"{name:26} {len(parsed):>6} {len(visible):>8}  {note[:64]}")

    print(f"\n  templates whose citation the parser CANNOT see : {len(blind)}")
    for name in blind:
        print(f"     {name}")
    print(f"  templates citing at Act level only             : {len(actless)}")
    for name in actless:
        print(f"     {name}")
    print(f"  templates with citations the parser reads      : {len(clean)}")
    return 0


raise SystemExit(main())
