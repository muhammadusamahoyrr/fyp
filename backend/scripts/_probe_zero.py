"""Audit every revision the checker reported ZERO citations for.

A zero from the checker means one of two very different things: the document
really cites no authority, or the parser did not recognise the citation it
carries. The second must never be reported as the first.

Prints only citation-like spans -- statutory references, not party details.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

SPAN = re.compile(
    r".{0,45}(?:sections?|secs?\.|u/s|articles?|arts?\.|order|rule|schedule)"
    r"\s*\d[\w\-()]*.{0,45}", re.I)
ACRONYMS = ("PECA", "PPC", "CrPC", "CPC", "QSO", "CNSA", "MFLO", "NAB",
            "ATA", "PLRA", "Ordinance", "Act ", "Code")
ACRO_RE = re.compile(r".{0,45}\b(?:" + "|".join(
    a.strip() for a in ACRONYMS) + r")\b.{0,45}")


async def main() -> int:
    from app.core.config import settings
    settings.mongodb_url = Path(os.environ["TEMP"], "v2s.txt").read_text(
        encoding="utf-8")
    from app.db.mongodb import connect_db, get_database
    await connect_db()
    db = get_database()

    import app.db.chroma as chroma_mod
    chroma_mod._CHROMA_PATH = Path(os.environ["SCRATCH"]) / "chroma_copy"
    chroma_mod.connect_chroma()

    from app.ai.citation_verification import parse_statute_citations
    from app.ai.corpus_index import get_index
    index = get_index()
    known = {s.upper() for s in index.statutes}

    revisions = sorted(await db["document_revisions"].find({}).to_list(length=None),
                       key=lambda r: r["document_id"])
    missed = []
    for rev in revisions:
        body = rev.get("body_text") or ""
        if not body.strip():
            continue
        parsed = parse_statute_citations(body, index)
        if parsed:
            continue                                  # checker saw something
        spans = []
        for match in list(SPAN.finditer(body)) + list(ACRO_RE.finditer(body)):
            span = " ".join(match.group(0).split())
            if span not in spans:
                spans.append(span)
        if not spans:
            continue                                  # genuinely uncited
        missed.append(rev["document_id"])
        print(f"\n{rev['document_id'][:22]}  {rev.get('template_type')}  "
              f"parser found 0, but the text says:")
        for span in spans[:6]:
            print(f"    ...{span}...")

    print("\n" + "=" * 70)
    print(f"revisions the checker called uncited but whose text names an "
          f"authority: {len(missed)}")
    for doc_id in missed:
        print(f"  {doc_id}")

    print("\n=== statutes the corpus holds (44) ===")
    for name in sorted(index.statutes):
        print(f"  {name}")
    print("\nPECA / Prevention of Electronic Crimes Act 2016 present: "
          f"{any('ELECTRONIC' in k or 'PECA' in k for k in known)}")
    return 0


raise SystemExit(asyncio.run(main()))
