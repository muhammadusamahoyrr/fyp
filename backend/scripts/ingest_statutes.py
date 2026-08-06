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


# ── contents-region removal ──────────────────────────────────────────────────
# 16 of 21 statutes open with an explicit CONTENTS marker. Removing that region
# before chunking is strictly better than pruning stubs afterwards, and it
# reaches a case dedup cannot: a contents entry whose body text was never
# extracted has no sibling to be matched against, so it survives the prune and
# masquerades as the section itself.
#
# Measured alternatives that did NOT work, so they are not reinstated:
#   * dotted-leader density per page — fires on only 2 of 21 statutes, because
#     Punjab contents lines carry no leader and no page number
#   * right-aligned page numbers — body text shares the same right edge, the
#     text block being narrow
_CONTENTS_MARKER = re.compile(
    r"^\s*(?:TABLE\s+OF\s+)?(?:CONTENTS|ARRANGEMENT\s+OF\s+SECTIONS|INDEX)\s*$",
    re.IGNORECASE)
# "12. Power to arrest without warrant." / "5. Definitions ... 3"
_CONTENTS_ENTRY = re.compile(r"^\s*\d+[A-Z]?\s*[\.\-]\s*\S.{0,110}$")
# Where the law actually begins. "Preamble" is deliberately NOT here: contents
# pages frequently list "Preamble" as their first entry, and treating it as the
# body terminated the scan immediately — that alone made the Qanun-e-Shahadat,
# one of the two worst offenders, come back unchanged.
_BODY_MARKER = re.compile(
    r"\b(whereas|it\s+is\s+hereby\s+enacted|be\s+it\s+enacted|"
    r"in\s+exercise\s+of\s+the\s+powers)\b", re.IGNORECASE)
_BODY_LINE_CHARS = 150      # a line this long is prose, not a contents entry
_MAX_CONTENTS_FRACTION = 0.30


def _strip_contents(text: str) -> tuple[str, int]:
    """Remove the contents region. Returns (text, lines_removed).

    Conservative by design: without an explicit marker nothing is removed, and
    the cut is capped at a fraction of the document so a misfire can never
    swallow the statute.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines[:400])
                  if _CONTENTS_MARKER.match(ln.strip())), None)
    if start is None:
        return text, 0

    last_entry = start
    for j in range(start + 1, len(lines)):
        s = lines[j].strip()
        if not s:
            continue
        if len(s) > _BODY_LINE_CHARS or _BODY_MARKER.search(s):
            break                      # the law starts here
        if _CONTENTS_ENTRY.match(s):
            last_entry = j

    cut = last_entry + 1
    if cut - start < 3:                # too small to be a contents block
        return text, 0
    if cut > len(lines) * _MAX_CONTENTS_FRACTION:
        # REFUSE rather than clamp. Clamping to the cap cuts at an arbitrary
        # line in the middle of the region, which is worse than leaving it:
        # part of the contents survives AND the boundary is meaningless.
        return text, 0

    return "\n".join(lines[:start] + lines[cut:]), cut - start


def extract_text(path: Path) -> str:
    reader = PdfReader(str(path))
    raw = "\n".join((p.extract_text() or "") for p in reader.pages)
    cleaned, removed = _strip_contents(raw)
    if removed:
        print(f"    (removed {removed} contents lines before chunking)")
    return cleaned


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
    return _drop_toc_stubs(chunks)


# A statute PDF opens with a CONTENTS page whose lines read
# "12. Power to arrest .... 7". Section-aware splitting treats each as a section
# start and emits a ~50-char chunk, duplicating a section whose real text is
# indexed separately. Those stubs are almost entirely heading words, so they
# match a query about that heading as densely as the provision does while
# containing none of the rule — they compete with, and can outrank, the law.
# Kept in sync with scripts/prune_toc_stubs.py.
_STUB_MAX_CHARS = 120
# Compare on the opening only. A contents line often carries trailing junk — a
# page number, or the next chapter heading run together with it — so matching
# the whole string fails even when the head is plainly the same.
_STUB_HEAD_CHARS = 25
_ALNUM = re.compile(r"[^a-z0-9]+")
# The trailing page reference MUST go before alphanumeric folding, or it lands
# inside the head and blocks the match. "16. Accomplice 7" -> "16accomplice7"
# never prefixes "16accompliceanaccomplice...". Long headings hid this, because
# the page number falls beyond _STUB_HEAD_CHARS.
_TRAILING_PAGENO = re.compile(r"[\.\s]*\d{1,3}\s*$")


def _normalise(text: str) -> str:
    """Alphanumeric-only, lowercased, trailing page reference removed.

    Statute PDFs are OCR'd, and the same heading appears differently in the
    contents and the body: "communicat ions" vs "communications",
    "facts-in-issue" vs "f acts in issue". Stripping everything but letters and
    digits makes those identical, where exact text matching does not.
    """
    return _ALNUM.sub("", _TRAILING_PAGENO.sub("", (text or "")).lower())


def _drop_toc_stubs(chunks: list[dict]) -> list[dict]:
    """Drop contents-page stubs, identified by PREFIX rather than by length.

    A contents line repeats the opening of the section it points at:

        "16. Accomplice 7"                                   <- stub
        "16. Accomplice; An accomplice shall be a competent"  <- the provision

    Strip the trailing page number and the stub is a prefix of the real text.
    That test is precise, where a length threshold is not: an earlier attempt
    using "sibling must exceed 400 chars" misjudged this very section, because
    the real provision is only 254 characters.

    A short chunk with no longer sibling it prefixes is always kept — plenty of
    provisions genuinely are one line, and dropping them would lose law.
    """
    by_section: dict[str, list[dict]] = {}
    for c in chunks:
        by_section.setdefault(c["meta"]["section_number"], []).append(c)

    drop_ids = set()
    for siblings in by_section.values():
        if len(siblings) < 2:
            continue
        for c in siblings:
            if len(c["content"]) >= _STUB_MAX_CHARS:
                continue
            head = _normalise(c["content"])[:_STUB_HEAD_CHARS]
            # Too short a head would match almost anything.
            if len(head) < 12:
                continue
            for other in siblings:
                if other is c or len(other["content"]) <= len(c["content"]):
                    continue
                if _normalise(other["content"]).startswith(head):
                    drop_ids.add(c["id"])
                    break

    return [c for c in chunks if c["id"] not in drop_ids]


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
