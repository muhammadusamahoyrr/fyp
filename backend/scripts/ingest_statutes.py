"""
ingest_statutes.py — Ingest statute PDFs from a local directory, reproducibly.

Why this exists
---------------
The statute corpus currently in ChromaDB was written by a one-off script that is
not in this repository, so the corpus could not be rebuilt from source — a
reproducibility problem for any published result. It also mis-filed the
Qanun-e-Shahadat (evidence law) into family_collection, where 211 chunks of
evidence law drowned out 15 chunks of actual family law.

Both problems have the same root cause: classification by keyword-guessing on a
filename. This script replaces that with an EXPLICIT registry. A statute that is
not in the registry is reported and skipped rather than silently guessed into the
wrong collection.

Cross-cutting statutes
----------------------
Some statutes belong in more than one collection. The Qanun-e-Shahadat governs
evidence in both criminal and civil proceedings, so it is registered for both —
and deliberately NOT for family, since family courts are not bound by the strict
rules of evidence (verify the exact section of the Family Courts Act 1964 before
citing that in writing).

Idempotency
-----------
Rather than relying on a chunk-id hash matching whatever the original script used,
this checks whether a statute already has chunks in a target collection and skips
it. Use --force to delete that statute's existing chunks and re-ingest.

Usage
-----
  python scripts/ingest_statutes.py --dir "C:/path/to/pdfs"     # dry run
  python scripts/ingest_statutes.py --dir "..." --apply
  python scripts/ingest_statutes.py --dir "..." --apply --force  # re-ingest
  python scripts/ingest_statutes.py --list-registry
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pypdf import PdfReader  # noqa: E402

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

# ── chunking (matches ingest_pakistan_laws.py) ───────────────────────────────
CHUNK_SIZE = 800
CHUNK_OVER = 100

# Default jurisdiction. NOT a constant any more: the retriever filters
# province IN (query_province, "federal"), and while every chunk was "federal"
# that filter excluded nothing and no provincial law could be represented.
# Provincial statutes (family courts, rent, police order, land revenue) must
# carry their own province or the filter stays a no-op.
DEFAULT_PROVINCE = "federal"
VALID_PROVINCES = {"federal", "punjab", "sindh", "kpk", "balochistan"}
SECTION_RE = re.compile(r"^\s*(\d+[A-Z]?)\s*[.\-]\s+(?=\S)", re.M)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

CRIMINAL = "criminal_collection"
CIVIL = "civil_collection"
FAMILY = "family_collection"
CONSTITUTIONAL = "constitutional_collection"

# ── explicit registry: filename stem (lowercased) -> statute record ──────────
# Matching is substring-based on the lowercased filename so minor naming
# differences do not break it. Order matters: first match wins.
REGISTRY: list[tuple[str, str, str, tuple[str, ...]]] = [
    # ── Punjab provincial law — MUST precede the federal entries ─────────────
    # First match wins, and these filenames contain federal fragments:
    # "police-order-2002" contains "police", "punjab-family-courts" contains
    # "family court". Listed first so the specific rule beats the general one.
    ("punjab-rented-premises",     "Punjab Rented Premises Act 2009",              "civil",  (CIVIL,)),
    ("punjab-tenancy-act",         "Punjab Tenancy Act 1887",                      "civil",  (CIVIL,)),
    ("punjab-protection-restoration-tenancy",
                                   "Punjab Protection and Restoration of Tenancy Rights Act 1950",
                                                                                   "civil",  (CIVIL,)),
    ("punjab-tenancy-validation",  "Punjab Tenancy (Validation) Ordinance 1969",   "civil",  (CIVIL,)),
    ("punjab-land-revenue-abolition",
                                   "Punjab Land Revenue (Abolition) Act 1998",     "civil",  (CIVIL,)),
    ("punjab-land-revenue-act",    "Punjab Land Revenue Act 1967",                 "civil",  (CIVIL,)),
    ("punjab-pre-emption-removal", "Punjab Pre-emption (Removal of Doubts) Ordinance 1972",
                                                                                   "civil",  (CIVIL,)),
    ("punjab-pre-emption-act",     "Punjab Pre-emption Act 1991",                  "civil",  (CIVIL,)),
    ("punjab-partition-of-immovable",
                                   "Punjab Partition of Immovable Property Act 2012",
                                                                                   "civil",  (CIVIL,)),
    ("punjab-consumer-protection", "Punjab Consumer Protection Act 2005",          "civil",  (CIVIL,)),
    ("punjab-letters-of-administration",
                                   "Punjab Letters of Administration and Succession Certificates Act 2021",
                                                                                   "civil",  (CIVIL,)),
    # Creates criminal offences AND protection orders sought in family
    # proceedings, so it belongs in both collections.
    ("punjab-protection-of-women", "Punjab Protection of Women against Violence Act 2016",
                                                                        "criminal", (CRIMINAL, FAMILY)),
    ("punjab-family-courts",       "Family Courts Act 1964",                       "family", (FAMILY,)),
    # SUPERSEDES the Police Act 1861 in Punjab.
    ("police-order-2002",          "Police Order 2002",                            "criminal", (CRIMINAL,)),

    # ── Federal law ─────────────────────────────────────────────────────────
    # (filename fragment, canonical statute, law_type, target collections)
    ("penal code",            "PPC 1860",                             "criminal",      (CRIMINAL,)),
    ("criminal_procedure",    "CrPC 1898",                            "criminal",      (CRIMINAL,)),
    ("criminal procedure",    "CrPC 1898",                            "criminal",      (CRIMINAL,)),
    ("police",                "Police Act 1861",                      "criminal",      (CRIMINAL,)),
    # Evidence law is cross-cutting: criminal AND civil, never family.
    ("shahadat",              "Qanun-e-Shahadat Order 1984",          "evidence",      (CRIMINAL, CIVIL)),
    ("limitation",            "Limitation Act 1908",                  "civil",         (CIVIL,)),
    ("transfer",              "Transfer of Property Act 1882",        "civil",         (CIVIL,)),
    ("contract",              "Contract Act 1872",                    "civil",         (CIVIL,)),
    ("civil procedure",       "CPC 1908",                             "civil",         (CIVIL,)),
    # Family
    ("muslim-family-laws",    "Muslim Family Laws Ordinance 1961",    "family",        (FAMILY,)),
    ("muslim family laws",    "Muslim Family Laws Ordinance 1961",    "family",        (FAMILY,)),
    ("dissolution",           "Dissolution of Muslim Marriages Act 1939", "family",    (FAMILY,)),
    ("family court",          "Family Courts Act 1964",               "family",        (FAMILY,)),
    ("guardians",             "Guardians and Wards Act 1890",         "family",        (FAMILY,)),
    ("child marriage",        "Child Marriage Restraint Act 1929",    "family",        (FAMILY,)),
    ("shariat",               "Muslim Personal Law (Shariat) Application Act 1962", "family", (FAMILY,)),
    # Constitutional
    ("constitution",          "Constitution of Pakistan 1973",        "constitutional", (CONSTITUTIONAL,)),

]


# Statutes that are PROVINCIAL rather than federal. Anything not listed here is
# treated as federal, which is the safe default: the retriever admits
# province IN (query_province, "federal"), so a federal label makes a statute
# visible everywhere, whereas a wrong provincial label hides it from four
# provinces.
PROVINCIAL_STATUTES: dict[str, str] = {
    "Punjab Rented Premises Act 2009": "punjab",
    "Punjab Tenancy Act 1887": "punjab",
    "Punjab Protection and Restoration of Tenancy Rights Act 1950": "punjab",
    "Punjab Tenancy (Validation) Ordinance 1969": "punjab",
    "Punjab Land Revenue Act 1967": "punjab",
    "Punjab Land Revenue (Abolition) Act 1998": "punjab",
    "Punjab Pre-emption Act 1991": "punjab",
    "Punjab Pre-emption (Removal of Doubts) Ordinance 1972": "punjab",
    "Punjab Partition of Immovable Property Act 2012": "punjab",
    "Punjab Consumer Protection Act 2005": "punjab",
    "Punjab Letters of Administration and Succession Certificates Act 2021": "punjab",
    "Punjab Protection of Women against Violence Act 2016": "punjab",
    "Police Order 2002": "punjab",
    # Family Courts Act 1964 is left FEDERAL on purpose: it originates as a West
    # Pakistan act adapted by every province, so a federal label keeps it
    # retrievable nationwide under the province OR federal rule. Replace with a
    # province-specific label only once each province's own version is indexed.
}


def classify(path: Path):
    name = path.stem.lower()
    for fragment, statute, law_type, collections in REGISTRY:
        if fragment in name:
            province = PROVINCIAL_STATUTES.get(statute, DEFAULT_PROVINCE)
            return statute, law_type, collections, province
    return None


def _slug(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower()).strip("_")[:60]


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    splits, last_end, last_sec = [], 0, None
    for m in SECTION_RE.finditer(text):
        if m.start() > last_end:
            splits.append((last_sec, text[last_end:m.start()].strip()))
        last_sec = m.group(1)
        last_end = m.start()
    splits.append((last_sec, text[last_end:].strip()))
    return [(s, t) for s, t in splits if t]


def _slide(text: str) -> list[str]:
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + CHUNK_SIZE])
        start += CHUNK_SIZE - CHUNK_OVER
    return out


def extract_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def make_chunks(text: str, statute: str, law_type: str, source_file: str,
                province: str = DEFAULT_PROVINCE) -> list[dict]:
    """Deterministic ids: statutes_{slug}_{index:04d}.

    The `statutes_` prefix keeps these distinct from ids written by other ingest
    scripts, so the two can coexist without silent collisions.
    """
    if province not in VALID_PROVINCES:
        raise ValueError(f"unknown province {province!r}; valid: {sorted(VALID_PROVINCES)}")
    slug = _slug(statute)
    chunks, i = [], 0
    for sec, block in _split_sections(text):
        for part in ([block] if len(block) <= CHUNK_SIZE else _slide(block)):
            part = part.strip()
            if not part:
                continue
            chunks.append({
                "id": f"statutes_{slug}_{i:04d}",
                "content": part,
                "meta": {
                    "statute": statute,
                    "section_number": sec or "",
                    "source_file": source_file,
                    "province": province,
                    "law_type": law_type,
                    "chunk_id": f"statutes_{slug}_{i:04d}",
                    # Lets a later run tell whether the source file changed.
                    "content_sha": hashlib.sha256(part.encode()).hexdigest()[:12],
                },
            })
            i += 1
    return chunks


def existing_count(col, statute: str) -> int:
    got = col.get(where={"statute": {"$eq": statute}}, include=[], limit=20000)
    return len(got.get("ids") or [])


def main(args) -> None:
    if args.list_registry:
        print("\n  registered statutes:\n")
        for frag, statute, law_type, cols in REGISTRY:
            print(f"    {statute:<52} {law_type:<14} -> {', '.join(cols)}")
        print()
        return

    src = Path(args.dir)
    if not src.is_dir():
        raise SystemExit(f"not a directory: {src}")

    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no PDFs found in {src}")

    connect_chroma()
    client = get_chroma()

    print(f"\n  source: {src}")
    print(f"  {len(pdfs)} PDF(s) found\n")
    print(f"  {'file':<42} {'statute':<40} {'status'}")
    print("  " + "-" * 104)

    planned = []
    unknown = []
    for pdf in pdfs:
        if args.only and args.only.lower() not in pdf.name.lower():
            continue
        hit = classify(pdf)
        if hit is None:
            unknown.append(pdf)
            print(f"  {pdf.name[:41]:<42} {'-':<40} NOT IN REGISTRY - skipped")
            continue
        statute, law_type, collections, province = hit
        # An explicit --province overrides the registry, for ingesting a batch
        # of statutes from one provincial code in a single pass.
        if args.province:
            province = args.province

        present = {}
        for cname in collections:
            col = client.get_or_create_collection(cname, metadata={"hnsw:space": "cosine"})
            present[cname] = existing_count(col, statute)

        already = all(n > 0 for n in present.values())
        status = ("present " + str(present)) if already else "WILL INGEST"
        if already and args.force:
            status = "RE-INGEST (--force) " + str(present)
        print(f"  {pdf.name[:41]:<42} {statute[:39]:<40} {status}")

        if not already or args.force:
            planned.append((pdf, statute, law_type, collections, province))

    if unknown:
        print(f"\n  {len(unknown)} file(s) not in the registry. Add them to "
              f"REGISTRY rather than letting a keyword guess place them:")
        for p in unknown:
            print(f"    - {p.name}")

    if not planned:
        print("\n  Nothing to do. Everything registered is already ingested.\n")
        return

    if not args.apply:
        print(f"\n  Dry run — {len(planned)} statute(s) would be ingested. "
              f"Re-run with --apply.\n")
        return

    from app.ai.pipelines.retriever import _embeddings  # noqa: E402
    embedder = _embeddings()

    for pdf, statute, law_type, collections, province in planned:
        text = extract_text(pdf)
        if len(text.strip()) < 500:
            print(f"  ! {pdf.name}: little or no extractable text "
                  f"({len(text)} chars) — likely a scan. SKIPPED.")
            continue

        chunks = make_chunks(text, statute, law_type, pdf.name, province)
        print(f"\n  {statute} [{province}]: {len(text):,} chars -> {len(chunks)} chunks")

        vectors = embedder.embed_documents([c["content"] for c in chunks])

        for cname in collections:
            col = client.get_or_create_collection(cname, metadata={"hnsw:space": "cosine"})
            if args.force:
                old = col.get(where={"statute": {"$eq": statute}}, include=[], limit=20000)
                if old.get("ids"):
                    col.delete(ids=old["ids"])
                    print(f"    removed {len(old['ids'])} existing chunks from {cname}")
            col.upsert(
                ids=[c["id"] for c in chunks],
                documents=[c["content"] for c in chunks],
                metadatas=[c["meta"] for c in chunks],
                embeddings=vectors,
            )
            print(f"    -> {cname}: now {col.count()} chunks")

    print("\n  Done. Re-run scripts/build_law_graph.py to refresh the "
          "statute cross-reference graph.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", default=r"C:\Users\The Laptop Hut\Desktop\specific_case_data",
                   help="directory of statute PDFs")
    p.add_argument("--apply", action="store_true", help="perform the ingest")
    p.add_argument("--force", action="store_true",
                   help="delete and re-ingest statutes already present")
    p.add_argument("--only", default="",
                   help="only process files whose name contains this substring")
    p.add_argument("--province", default="", choices=sorted(VALID_PROVINCES) + [""],
                   help="override the province for this batch, e.g. --province punjab "
                        "when ingesting a provincial code")
    p.add_argument("--list-registry", action="store_true",
                   help="print the statute registry and exit")
    main(p.parse_args())
