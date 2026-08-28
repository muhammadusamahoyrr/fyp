"""Pakistani case-law corpus + citator.

Source v1: Lahore High Court reported judgments. LHC publishes each
approved-for-reporting judgment as a born-digital PDF under a sequential
neutral citation — http://sys.lhc.gov.pk/appjudgments/2026LHC4480.pdf —
so the corpus is enumerable by (year, seq) without scraping listing pages;
the listing page additionally provides judge/title/headnote tag-lines for
recent items. (Verified 2026-07-05. Note: the PDF host speaks plain HTTP.)

The citator's first useful query is the reverse index: "which judgments in
the corpus cite PLD 2019 SC 675" — precedent-usage lookup across reporters
(PLD, SCMR, CLC, YLR, MLD, PCr.LJ, PLJ, CLD, PTD, PLC, NLR).
"""
import asyncio
import io
import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.db.chroma import get_collection
from app.db.mongodb import get_database

logger = logging.getLogger(__name__)

PDF_URL = "http://sys.lhc.gov.pk/appjudgments/{neutral_id}.pdf"
LISTING_URL = "https://data.lhc.gov.pk/reported_judgments/judgments_approved_for_reporting"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

NEUTRAL_ID_RE = re.compile(r"^(\d{4})LHC(\d{1,6})$")

# This path scrapes one court, so the jurisdiction is fixed rather than derived.
# Values match ingest_judgments.COURTS["lahore high court"]; the ranker compares
# them literally, so a spelling that drifts from that table reads as no match.
COURT = "LHC"
PROVINCE = "punjab"
AUTHORITY = "binding_provincial"

# ── Citation extraction ───────────────────────────────────────────────────────
# Two families of Pakistani reporter citations (whitespace-tolerant — PDFs
# break citations across lines):
#   volume-first:  PLD 2019 SC 675 · PLJ 2020 Lahore 14
#   year-first:    2021 SCMR 1023 · 2019 CLC 123 · 2020 PCr.LJ 55
_COURT_TOKEN = r"[A-Za-z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*)?"
_VOLUME_FIRST = re.compile(
    rf"\b(PLD|PLJ)\s+(\d{{4}})\s+({_COURT_TOKEN})\s+(\d{{1,5}})\b"
)
_YEAR_FIRST = re.compile(
    r"\b(\d{4})\s+(SCMR|CLC|YLR|MLD|PCr\.?\s?LJ|PLC|CLD|PTD|NLR|GBLR|SCP)\s+(\d{1,5})\b"
)

# court aliases seen after PLD/PLJ
_COURT_CANON = {
    "sc": "SC", "s.c.": "SC", "supreme court": "SC",
    "lah": "Lah", "lahore": "Lah",
    "kar": "Kar", "karachi": "Kar", "sindh": "Kar",
    "pesh": "Pesh", "peshawar": "Pesh",
    "quetta": "Quetta", "bal": "Quetta",
    "isl": "Isl", "islamabad": "Isl",
    "fsc": "FSC", "ajk": "AJK", "fc": "FC",
}


def _canon_reporter(rep: str) -> str:
    rep = re.sub(r"\s+", "", rep.upper())
    return "PCr.LJ" if rep in ("PCRLJ", "PCR.LJ") else rep


def extract_citations(text: str) -> list[str]:
    """All reporter citations in a judgment, normalized and de-duplicated."""
    found: list[str] = []
    for m in _VOLUME_FIRST.finditer(text):
        series, year, court, page = m.groups()
        court_key = re.sub(r"\s+", " ", court).strip().lower().rstrip(".")
        court_norm = _COURT_CANON.get(court_key)
        if not court_norm:
            continue  # "PLD 2019 the 5"-style false positives die here
        found.append(f"{series.upper()} {year} {court_norm} {int(page)}")
    for m in _YEAR_FIRST.finditer(text):
        year, rep, page = m.groups()
        found.append(f"{year} {_canon_reporter(rep)} {int(page)}")
    seen: set[str] = set()
    out = []
    for c in found:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def normalize_citation(raw: str) -> str:
    """Normalize a user-typed citation to the stored form."""
    cites = extract_citations(" " + re.sub(r"\s+", " ", raw or "").strip() + " ")
    return cites[0] if cites else re.sub(r"\s+", " ", (raw or "").strip())


# ── Fetch + parse ─────────────────────────────────────────────────────────────

def _judgments_col():
    return get_database()["judgments"]


async def fetch_pdf_text(neutral_id: str) -> str | None:
    """Judgment PDF → text. None for a 404 (gap in the sequence)."""
    url = PDF_URL.format(neutral_id=neutral_id)
    try:
        async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        if "pdf" not in resp.headers.get("content-type", ""):
            return None
        reader = PdfReader(io.BytesIO(resp.content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except httpx.HTTPError as e:
        logger.warning("Judgment fetch failed for %s: %r", neutral_id, e)
        raise ServiceUnavailableError("Court server unreachable")
    except Exception:
        logger.exception("PDF extraction failed for %s", neutral_id)
        return None


_CASE_NO_RE = re.compile(r"^(.{3,80}?No\.?\s*[\w./-]+\s+of\s+\d{4})", re.M)
_JUDGE_RE = re.compile(r"^\s*([A-Z][A-Z .]{4,60}),\s*(?:C\.?)?J\b", re.M)
_DATE_RE = re.compile(r"DATE OF HEARING[:\s]*(\d{2}[.\-/]\d{2}[.\-/]\d{4})", re.I)


def parse_metadata(text: str) -> dict:
    head = text[:2500]
    meta: dict = {}
    if m := _CASE_NO_RE.search(head):
        meta["case_no"] = re.sub(r"\s+", " ", m.group(1)).strip()
    if m := re.search(r"\n(.{3,90}?)\n\s*V(?:ERSU|S)?S?U?S?\.?\s*\n(.{3,90}?)\n", head, re.I):
        meta["title"] = re.sub(r"\s+", " ", f"{m.group(1).strip()} vs {m.group(2).strip()}")
    if m := _JUDGE_RE.search(head):
        meta["judge"] = m.group(1).title().strip()
    if m := _DATE_RE.search(head):
        meta["hearing_date"] = m.group(1)
    return meta


async def fetch_listing(year: int | None = None) -> list[dict]:
    """The reported-judgments listing page (latest ~50) — richer metadata
    (judge, title, headnote tag-line) than the PDFs' first pages."""
    params = {"year": year} if year else None
    try:
        async with httpx.AsyncClient(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(LISTING_URL, params=params)
            resp.raise_for_status()
    except httpx.HTTPError:
        raise ServiceUnavailableError("Court server unreachable")

    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[dict] = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"appjudgments/(\d{4}LHC\d+)\.pdf", a["href"])
        if not m:
            continue
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        item = {"neutral_id": m.group(1), "pdf_url": a["href"]}
        if lm := re.match(r"(.+?)\s*\((.+?)\)\s*by\s+(.+)$", label):
            item["case_no"] = lm.group(1).strip()
            item["title"] = lm.group(2).strip()
            item["judge"] = lm.group(3).strip()
        else:
            item["title"] = label
        # Tag line lives in the text between this link and the next entry
        tail = ""
        for sib in a.next_siblings:
            tail += sib.get_text(" ", strip=True) if getattr(sib, "get_text", None) else str(sib)
            if "uploaded on" in tail:
                break
        if tm := re.search(r"Tag Line:\s*(.+?)(?:uploaded on|$)", tail, re.S):
            item["tag_line"] = re.sub(r"\s+", " ", tm.group(1)).strip()
        if um := re.search(r"uploaded on:\s*([\d-]+)", tail):
            item["uploaded_date"] = um.group(1)
        items.append(item)
    return items


# ── Ingestion ─────────────────────────────────────────────────────────────────

_CHUNK_CHARS = 1200
_MAX_CHUNKS = 24


def _chunk(text: str) -> list[str]:
    """Sentence-boundary chunks, capped so one judgment can't hog embedding time."""
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text))
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) > _CHUNK_CHARS and cur:
            chunks.append(cur.strip())
            cur = ""
        cur += s + " "
        if len(chunks) >= _MAX_CHUNKS:
            return chunks
    if cur.strip():
        chunks.append(cur.strip())
    return chunks[:_MAX_CHUNKS]


# The three stages below are shared by the inline `ingest_judgment` path and by
# the decoupled Redis-Streams pipeline (services/citator_stream.py). Keeping one
# implementation each means both paths parse/store/embed identically.

def build_doc(neutral_id: str, text: str, listing_meta: dict | None = None) -> dict:
    """PARSE stage (pure, no I/O): neutral id + PDF text (+ optional listing
    metadata) → the judgment document. Runs metadata parse + citation extract."""
    m = NEUTRAL_ID_RE.match(neutral_id)
    if not m:
        raise ValueError(f"Bad neutral id: {neutral_id}")

    meta = parse_metadata(text)
    if listing_meta:
        meta.update({k: v for k, v in listing_meta.items() if v})

    return {
        "_id": neutral_id,
        "court": COURT,
        # Persisted, not merely passed to the embedder. rebuild_judgments_
        # vectors.py regenerates Chroma metadata FROM these Mongo fields, so a
        # judgment whose document omits them comes back out of any future
        # rebuild as persuasive-everywhere — which is exactly how 200 judgments
        # lost their jurisdiction the first time.
        "province": PROVINCE,
        "authority": AUTHORITY,
        "year": int(m.group(1)),
        "seq": int(m.group(2)),
        "pdf_url": PDF_URL.format(neutral_id=neutral_id),
        "case_no": meta.get("case_no"),
        "title": meta.get("title"),
        "judge": meta.get("judge"),
        "hearing_date": meta.get("hearing_date"),
        "tag_line": meta.get("tag_line"),
        "uploaded_date": meta.get("uploaded_date"),
        "citations_out": extract_citations(text),
        "text": text,
        "text_chars": len(text),
        "ingested_at": datetime.now(timezone.utc),
    }


async def store_judgment(doc: dict) -> None:
    """STORE stage: persist the judgment doc to Mongo (raises DuplicateKeyError
    if the neutral id already exists — callers treat that as already-ingested)."""
    await _judgments_col().insert_one(doc)


def _embed_and_upsert(neutral_id: str, chunks: list[str], year: int, meta_doc: dict) -> None:
    """Blocking body of the embed stage: E5 inference + Chroma upsert. Runs in a
    worker thread (see embed_judgment). onnxruntime releases the GIL during
    inference, so this genuinely overlaps with the event loop.

    province/authority are written here even though this path only ever ingests
    LHC. They are what the precedent-aware ranker reads, and omitting them does
    not leave a judgment unranked — it ranks it as persuasive everywhere, so a
    Lahore judgment that binds in Punjab silently loses its binding weight.
    Every judgment ingested through this path before the fields were added
    landed that way: 200 judgments, 3,230 chunks, corrected by
    scripts/backfill_jurisdiction.py.
    """
    from app.ai.pipelines.retriever import _embeddings
    emb = _embeddings()
    vectors = emb.embed_documents(chunks)
    chroma = get_collection("judgments_collection")
    chroma.upsert(
        ids=[f"{neutral_id}:{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=chunks,
        metadatas=[{
            "judgment_id": neutral_id,
            "court": COURT,
            "province": PROVINCE,
            "authority": AUTHORITY,
            "year": year,
            "judge": meta_doc.get("judge") or "",
            "title": meta_doc.get("title") or "",
        } for _ in chunks],
    )


async def embed_judgment(neutral_id: str, text: str) -> None:
    """EMBED stage: chunk the text and upsert vectors into judgments_collection.
    Idempotent (Chroma upsert keyed on `{neutral_id}:{i}`). Never raises — a
    failed embed leaves the stored text for a later re-embed.

    The CPU/IO-bound embed+upsert is offloaded via asyncio.to_thread so it does
    NOT block the event loop — letting the parse and embed stages run
    concurrently within a single `--role both` worker process."""
    try:
        chunks = _chunk(text)
        if not chunks:
            return
        year = int(NEUTRAL_ID_RE.match(neutral_id).group(1))
        meta_doc = await _judgments_col().find_one(
            {"_id": neutral_id}, {"judge": 1, "title": 1}
        ) or {}
        await asyncio.to_thread(_embed_and_upsert, neutral_id, chunks, year, meta_doc)
    except Exception:
        logger.exception("Embedding failed for %s (text is stored; re-embed later)", neutral_id)


async def ingest_judgment(neutral_id: str, listing_meta: dict | None = None) -> dict | None:
    """Inline fetch → parse → store → embed. Idempotent by neutral id.
    Returns the stored doc, or None if the PDF doesn't exist / has no text.

    The streaming pipeline (services/citator_stream.py) splits these same stages
    across Redis-Streams consumer groups; this inline form stays for CLI/one-off
    use and as the reference implementation."""
    m = NEUTRAL_ID_RE.match(neutral_id)
    if not m:
        raise ValueError(f"Bad neutral id: {neutral_id}")

    col = _judgments_col()
    if existing := await col.find_one({"_id": neutral_id}):
        return existing

    text = await fetch_pdf_text(neutral_id)
    if not text or len(text.strip()) < 200:
        return None

    doc = build_doc(neutral_id, text, listing_meta)
    await store_judgment(doc)
    await embed_judgment(neutral_id, text)
    return doc


# ── Citator queries ───────────────────────────────────────────────────────────

def _public(doc: dict, with_text: bool = False) -> dict:
    out = {k: v for k, v in doc.items() if k != "text"}
    out["id"] = out.pop("_id")
    if with_text:
        out["text_preview"] = doc.get("text", "")[:3000]
    return out


async def get_judgment(neutral_id: str) -> dict:
    doc = await _judgments_col().find_one({"_id": neutral_id})
    if not doc:
        raise NotFoundError("Judgment")
    return _public(doc, with_text=True)


async def cited_by(citation: str, limit: int = 50) -> dict:
    """Corpus judgments that cite the given reporter citation."""
    norm = normalize_citation(citation)
    cursor = _judgments_col().find(
        {"citations_out": norm},
        {"text": 0},
    ).sort("year", -1).limit(limit)
    docs = [_public(d) async for d in cursor]
    return {"citation": norm, "cited_by": docs, "count": len(docs)}


# ── precedent weighting ───────────────────────────────────────────────────────
# Pakistani precedent is hierarchical: the Supreme Court binds every court in the
# country, a High Court binds courts within its own province, and another
# province's High Court is PERSUASIVE only.
#
# This is applied as a rank BOOST rather than a filter, deliberately. Excluding
# other provinces would discard persuasive authority that is genuinely useful —
# and with a corpus drawn largely from one High Court it would return nothing at
# all for users elsewhere. Ordering reflects authority; availability does not.
_AUTHORITY_BOOST_NATIONAL = 1.15   # Supreme Court — binds everywhere
_AUTHORITY_BOOST_OWN      = 1.10   # High Court of the querying province
_AUTHORITY_BOOST_OTHER    = 1.00   # another High Court — persuasive only


def _precedent_weight(meta: dict, province: str | None) -> float:
    authority = str((meta or {}).get("authority", ""))
    if authority == "binding_national":
        return _AUTHORITY_BOOST_NATIONAL
    if authority == "binding_provincial" and province:
        same = str((meta or {}).get("province", "")).lower() == province.lower()
        return _AUTHORITY_BOOST_OWN if same else _AUTHORITY_BOOST_OTHER
    return _AUTHORITY_BOOST_OTHER


async def search(query: str, n: int = 8, province: str | None = None) -> list[dict]:
    """Semantic search over judgment text; one result per judgment.

    `province` enables precedent-aware ranking: binding authority outranks
    persuasive authority at comparable semantic similarity. Omit it for a purely
    semantic search.
    """
    from app.ai.pipelines.retriever import _embeddings
    emb = _embeddings()
    qvec = emb.embed_query(query)
    chroma = get_collection("judgments_collection")
    res = chroma.query(query_embeddings=[qvec], n_results=min(n * 4, 60),
                       include=["metadatas", "documents", "distances"])

    best: dict[str, dict] = {}
    for i, meta in enumerate(res["metadatas"][0]):
        jid = meta["judgment_id"]
        dist = res["distances"][0][i]
        if jid in best and best[jid]["distance"] <= dist:
            continue
        raw = round(max(0.0, 1 - dist), 4)
        weight = _precedent_weight(meta, province)
        best[jid] = {
            "judgment_id": jid,
            "distance": dist,
            # Capped at 1.0 so a boosted score stays comparable with the
            # thresholds callers apply to semantic similarity.
            "score": round(min(raw * weight, 1.0), 4),
            "semantic_score": raw,
            "authority": (meta or {}).get("authority", ""),
            "court_province": (meta or {}).get("province", ""),
            "snippet": res["documents"][0][i][:400],
        }
    # Rank on the weighted score, not raw distance, or the boost does nothing.
    ranked = sorted(best.values(), key=lambda x: -x["score"])[:n]

    out = []
    for hit in ranked:
        doc = await _judgments_col().find_one({"_id": hit["judgment_id"]}, {"text": 0})
        if doc:
            pub = _public(doc)
            pub["score"] = hit["score"]
            pub["snippet"] = hit["snippet"]
            # Carried through so callers (and the audit trail) can see WHY a
            # judgment ranked where it did, not just that it did.
            pub["semantic_score"] = hit["semantic_score"]
            pub["authority"] = hit["authority"]
            pub["court_province"] = hit["court_province"]
            out.append(pub)
    return out


async def corpus_stats() -> dict:
    col = _judgments_col()
    total = await col.count_documents({})
    with_cites = await col.count_documents({"citations_out.0": {"$exists": True}})
    edges = 0
    async for d in col.aggregate([{"$project": {"n": {"$size": "$citations_out"}}}]):
        edges += d["n"]
    return {"judgments": total, "with_citations": with_cites, "citation_edges": edges}


# ── Human-usable references ──────────────────────────────────────────────────
#
# What the pipeline previously showed as a citation was `f"LHC {judgment_id}"`,
# producing "LHC 2026LHC4480". That is an internal document id with a court
# prefix bolted on. A lawyer cannot look it up, cannot cite it, and cannot check
# it — and presenting it in the same slot as a citation invites them to paste it
# into a filing. Courts fined lawyers $145,000 in Q1 2026 over citations that
# could not be verified; handing them an unverifiable string is not a neutral
# act.
#
# These judgments are mostly UNREPORTED — recent High Court decisions that have
# no PLD/SCMR number yet. That is not a gap in the corpus: the correct way to
# refer to an unreported judgment is party names, case number, court and year,
# and all four are already stored.
#
#     Nisar Ahmad Khan Vs The State etc. — Crl. Misc. 3189/26 (LHC 2026)
#
# Metadata extraction is imperfect (some records have the parties split across
# title and case_no), so this degrades a piece at a time rather than failing.

def format_reference(doc: dict) -> str:
    """A reference a lawyer can actually look up, from whatever fields exist."""
    title = (doc.get("title") or "").strip()
    case_no = (doc.get("case_no") or "").strip()
    court = (doc.get("court") or "").strip()
    year = str(doc.get("year") or "").strip()

    head = " — ".join(p for p in (title, case_no) if p)
    tail = " ".join(p for p in (court, year) if p)

    if head and tail:
        return f"{head} ({tail})"
    if head:
        return head
    if tail:
        # No party names and no case number: say what this is rather than
        # dressing the internal id up as a citation.
        jid = doc.get("_id") or doc.get("judgment_id") or ""
        return f"{tail} judgment [ref: {jid}]" if jid else f"{tail} judgment"
    jid = doc.get("_id") or doc.get("judgment_id") or ""
    return f"Unidentified judgment [ref: {jid}]" if jid else "Unidentified judgment"


def is_reportable_citation(ref: str) -> bool:
    """True when `ref` looks like a real reference rather than an internal id.

    Used to keep synthesised ids out of anywhere that implies citability.
    """
    if not ref:
        return False
    return "[ref:" not in ref and not ref.startswith("Unidentified")
