"""
ingest_judgments.py — Ingest the multi-court Pakistani judgment corpus.

Why
---
judgments_collection holds 200 judgments, all from the Lahore High Court, all
marked binding_provincial/punjab. That has two consequences:

  * The precedent-aware ranking in citator_service has no data behind its most
    important branch. binding_national (Supreme Court, x1.15) never fires
    because there are no Supreme Court judgments.
  * A litigant outside Punjab gets ONLY persuasive authority, because every
    judgment in the corpus belongs to another province's High Court.

This ingests a corpus spanning the Supreme Court and five High Courts, taking
the collection from one court to six.

Both stores, or the judgment is invisible
-----------------------------------------
citator_service.search() looks each Chroma hit up in MongoDB by _id and DROPS it
if absent. Chunks written to Chroma alone would silently never surface, so this
writes the Mongo document first and the vectors second.

Findings this handles, measured on the corpus
---------------------------------------------
  * Two files are byte-identical duplicates (browser "(1).pdf" re-downloads), so
    dedup is on content hash, not filename. 325 files, 323 judgments.
  * Roughly 6% are image-only scans. They are skipped and reported, not ingested
    as empty documents.
  * Filename metadata quality varies enormously. Lahore filenames are neutral
    citations (2025LHC7284) and parse directly; Supreme Court filenames carry a
    case number and year; but 50 of Balochistan's are bare numbers or raw UUIDs
    carrying nothing at all, so every field must come from the document text.
  * Citation extraction over OCR'd text produces impossible years ("2077 SCMR
    561", 2084, 2090). Citations are year-bounded before being stored, or the
    citator's reverse index fills with garbage.

Usage
-----
  python scripts/ingest_judgments.py --dir DIR              # dry run
  python scripts/ingest_judgments.py --dir DIR --apply
  python scripts/ingest_judgments.py --dir DIR --apply --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pypdf import PdfReader  # noqa: E402

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.services import citator_service as cs  # noqa: E402

DEFAULT_DIR = Path.home() / "Downloads" / "Pakistan-Legal-Data-main"

# Folder name -> (court code, province, authority)
# Supreme Court is "federal" deliberately: the retriever admits federal for every
# province, which is the correct behaviour for a court that binds nationally.
COURTS: dict[str, tuple[str, str, str]] = {
    "supreme court decisions":   ("SC",  "federal",     "binding_national"),
    "lahore high court":         ("LHC", "punjab",      "binding_provincial"),
    "sindh high court":          ("SHC", "sindh",       "binding_provincial"),
    "peshawar high court":       ("PHC", "kpk",         "binding_provincial"),
    "balochistan high court":    ("BHC", "balochistan", "binding_provincial"),
    "islamabad high court":      ("IHC", "federal",     "binding_provincial"),
}

MIN_TEXT_CHARS = 800          # below this it is a scan, not a judgment
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_NEUTRAL_LHC = re.compile(r"^(\d{4})LHC(\d{1,6})$", re.IGNORECASE)

# Pakistan's first reported judgments post-date 1947; anything outside the range
# is OCR noise, not a citation.
_YEAR_MIN = 1947
_YEAR_MAX = date.today().year + 1

_CASE_NO_RE = re.compile(
    r"((?:Crl|Cr|Civil|Const|Criminal|Writ|Jail|Murder|Regular|Election)"
    r"[A-Za-z\.\s]{0,28}?(?:Appeal|Petition|Revision|Reference|Misc|Suit|No)"
    r"[^\n]{0,40}?\d[\d\-/\s]{0,18}(?:of\s*\d{4})?)",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"([A-Z][A-Za-z\.\,\'\- ]{2,60}?)\s+(?:VS?\.?|VERSUS|V/S)\s+([A-Z][A-Za-z\.\,\'\- ]{2,60})",
    re.IGNORECASE,
)
# The honorific is optional: several courts print "JUSTICE ABC" or
# "Before: Mr. Justice ABC", and requiring "Mr./Mrs./Ms." matched 0 of 12
# Balochistan judgments.
_JUDGE_RE = re.compile(
    r"(?:before\s*:?\s*)?((?:Mr\.?|Mrs\.?|Ms\.?|Miss)?\s*Justice\s+"
    r"[A-Z][A-Za-z\.\' \-]{3,50})", re.IGNORECASE)
_YEAR_IN_TEXT = re.compile(r"\b(19[5-9]\d|20[0-2]\d)\b")


def slug(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")[:70]


def court_of(path: Path, root: Path) -> tuple[str, str, str] | None:
    for part in path.relative_to(root).parts:
        hit = COURTS.get(part.strip().lower())
        if hit:
            return hit
    return None


def extract_text(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def judgment_id(path: Path, court_code: str) -> str:
    """Stable id. Lahore filenames ARE neutral citations, so keep them — that
    matches the existing corpus convention and keeps ids meaningful."""
    stem = path.stem
    if court_code == "LHC" and _NEUTRAL_LHC.match(stem):
        return stem.upper()
    return f"{court_code}:{slug(stem)}"


def derive_metadata(text: str, path: Path) -> dict:
    """Best-effort fields from the document body.

    Necessary because filename quality collapses for some courts — 50 of
    Balochistan's are bare numbers or UUIDs carrying no information whatsoever.
    """
    head = text[:4000]
    meta: dict = {}

    m = _TITLE_RE.search(head)
    if m:
        meta["title"] = " ".join(f"{m.group(1).strip()} vs {m.group(2).strip()}".split())[:160]

    m = _CASE_NO_RE.search(head)
    if m:
        meta["case_no"] = " ".join(m.group(1).split())[:90]

    m = _JUDGE_RE.search(head)
    if m:
        meta["judge"] = " ".join(m.group(1).split())[:90]

    years = [int(y) for y in _YEAR_IN_TEXT.findall(head)
             if _YEAR_MIN <= int(y) <= _YEAR_MAX]
    if years:
        meta["year"] = max(years)
    else:
        fm = re.search(r"(19|20)\d{2}", path.stem)
        if fm:
            meta["year"] = int(fm.group(0))
    return meta


def clean_citations(text: str) -> list[str]:
    """Reporter citations, with impossible years discarded.

    OCR noise yields things like '2077 SCMR 561'. Left unfiltered they pollute
    the citator's reverse index with references to judgments that cannot exist.
    """
    out, dropped = [], 0
    for c in cs.extract_citations(text):
        ym = re.search(r"\b(\d{4})\b", c)
        if ym and not (_YEAR_MIN <= int(ym.group(1)) <= _YEAR_MAX):
            dropped += 1
            continue
        out.append(c)
    return out, dropped


async def main(args) -> None:
    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")

    pdfs = sorted(root.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no PDFs under {root}")

    await connect_db()
    connect_chroma()
    try:
        col = cs._judgments_col()
        vectors_col = get_chroma().get_or_create_collection(
            "judgments_collection", metadata={"hnsw:space": "cosine"})

        def has_vectors(jid: str) -> bool:
            got = vectors_col.get(where={"judgment_id": {"$eq": jid}},
                                  include=[], limit=1)
            return bool(got.get("ids"))

        # ── plan ─────────────────────────────────────────────────────────────
        seen_hashes: dict[str, Path] = {}
        plan, dupes, scans, unknown = [], [], [], []
        by_court: collections.Counter = collections.Counter()

        for pdf in pdfs:
            court = court_of(pdf, root)
            if court is None:
                unknown.append(pdf)
                continue
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            if digest in seen_hashes:
                dupes.append((pdf, seen_hashes[digest]))
                continue
            seen_hashes[digest] = pdf
            plan.append((pdf, court, digest))
            by_court[court[0]] += 1

        print(f"\n  {len(pdfs)} PDFs under {root}")
        print(f"  {len(dupes)} exact duplicate(s) skipped (content hash, not filename)")
        if unknown:
            print(f"  {len(unknown)} file(s) in an unrecognised court folder — skipped")
        print(f"  {len(plan)} unique judgments across {len(by_court)} courts: "
              f"{dict(by_court)}")

        if args.limit:
            plan = plan[:args.limit]
            print(f"  --limit {args.limit} applied")

        already = 0
        todo = []
        for pdf, court, digest in plan:
            jid = judgment_id(pdf, court[0])
            # "Done" means BOTH stores. Checking Mongo alone would permanently
            # skip a judgment whose embedding failed part-way, leaving it stored
            # but unsearchable — search() drops Chroma hits with no Mongo doc,
            # and a Mongo doc with no vectors is never a hit in the first place.
            if await col.find_one({"_id": jid}, {"_id": 1}) and has_vectors(jid):
                already += 1
                continue
            todo.append((pdf, court, digest, jid))
        print(f"  {already} already ingested, {len(todo)} to process")

        if not todo:
            print("\n  Nothing to do.\n")
            return
        if not args.apply:
            print("\n  Dry run — nothing written. Re-run with --apply.\n")
            return

        # ── ingest ───────────────────────────────────────────────────────────
        stats = collections.Counter()
        total_dropped_cites = 0

        for i, (pdf, (code, province, authority), digest, jid) in enumerate(todo, 1):
            text = extract_text(pdf)
            if len(text.strip()) < MIN_TEXT_CHARS:
                scans.append(pdf.name)
                stats["scan_skipped"] += 1
                continue

            meta = derive_metadata(text, pdf)
            citations, dropped = clean_citations(text)
            total_dropped_cites += dropped

            doc = {
                "_id": jid,
                "court": code,
                "province": province,
                "authority": authority,
                "year": meta.get("year"),
                "case_no": meta.get("case_no", ""),
                "title": meta.get("title", "") or pdf.stem[:120],
                "judge": meta.get("judge", ""),
                "citations_out": citations,
                "text": text,
                "text_chars": len(text),
                "source_file": pdf.name,
                "sha256": digest,
                "source": "pakistan-legal-dataset",
                "ingested_at": datetime.now(timezone.utc),
            }
            await col.replace_one({"_id": jid}, doc, upsert=True)
            stats["mongo"] += 1

            chunks = cs._chunk(text)
            if chunks:
                await asyncio.to_thread(
                    _embed, jid, chunks, code, province, authority, doc)
                stats["embedded"] += 1
                stats["chunks"] += len(chunks)

            if i % 25 == 0 or i == len(todo):
                print(f"    {i}/{len(todo)}  mongo={stats['mongo']} "
                      f"embedded={stats['embedded']} chunks={stats['chunks']} "
                      f"scans={stats['scan_skipped']}")

        print(f"\n  judgments stored : {stats['mongo']}")
        print(f"  embedded         : {stats['embedded']}  ({stats['chunks']} chunks)")
        print(f"  scans skipped    : {stats['scan_skipped']}")
        if scans[:5]:
            for s in scans[:5]:
                print(f"      {s}")
        print(f"  citations dropped as impossible years: {total_dropped_cites}")
        print("\n  Next: python scripts/build_law_graph.py is NOT needed (statutes only),\n"
              "  but re-check citator corpus stats.\n")
    finally:
        await close_db()


def _embed(jid, chunks, court, province, authority, doc) -> None:
    """Mirror citator_service._embed_and_upsert, plus jurisdiction metadata.

    province/authority are what the precedent-aware ranker reads; without them a
    judgment is treated as persuasive everywhere.
    """
    from app.ai.pipelines.retriever import _embeddings
    from app.db.chroma import get_collection

    emb = _embeddings()
    vectors = emb.embed_documents(chunks)
    get_collection("judgments_collection").upsert(
        ids=[f"{jid}:{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=chunks,
        metadatas=[{
            "judgment_id": jid,
            "court": court,
            "province": province,
            "authority": authority,
            "year": doc.get("year") or 0,
            "judge": doc.get("judge") or "",
            "title": doc.get("title") or "",
        } for _ in chunks],
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", default=str(DEFAULT_DIR),
                   help=f"root of the judgment corpus (default {DEFAULT_DIR})")
    p.add_argument("--apply", action="store_true", help="perform the ingest")
    p.add_argument("--limit", type=int, default=0, help="process only the first N")
    asyncio.run(main(p.parse_args()))
