"""ingest_sc_parquet.py — Supreme Court judgments from the Ibtehaj10 parquet.

WHY
---
judgments holds 502 judgments, of which 68 are Supreme Court — and 61 of those
68 are from 2025. The citator's `binding_national` branch (x1.15) therefore
fires almost exclusively on one year of authority, and any question whose
controlling precedent predates 2025 finds nothing binding at all.

This adds 1,414 Supreme Court judgments spanning 1993-2023, which is precisely
the gap: the existing corpus covers the present, this covers the two decades
before it.

THE EMBEDDINGS IN THIS FILE ARE DELIBERATELY DISCARDED
-------------------------------------------------------
The parquet ships a 1024-d `embeddings` column from mixedbread-ai/mxbai-embed-
large-v1. Our retriever uses intfloat/multilingual-e5-base at 768 dimensions.
The vectors are not merely a different size — they are a different space, so
they cannot be projected, padded or reused in any form. Loading them would cost
8.3 MB per row group to no purpose, so the parquet is read with an explicit
column list that never mentions them, and text is re-embedded with our own
model.

WHAT THE COLUMNS ACTUALLY CONTAIN
----------------------------------
`citation_number` is byte-identical to `case_details` on all 1,414 rows. Despite
the name it holds no citation — both are a stringified dict of the source
filename and an always-empty url:

    {'id': 'C.A.10_2021.pdf', 'url': ''}

So the filename is the ONLY metadata, and everything else — title, judge, year,
case number, outgoing citations — has to come from the document body. That is
the same problem ingest_judgments.py solved for Balochistan, whose filenames are
bare UUIDs, so this reuses its derivation rather than writing a second one:

    derive_metadata, clean_citations, slug, MIN_TEXT_CHARS, _embed

DEDUPLICATION
-------------
Two independent keys, because either alone has a blind spot:

  * Normalised text hash — catches the same judgment filed under a different
    case number. Byte-hashing would not: the existing corpus stores the sha256
    of a PDF, and this source has no PDF.
  * Canonical case key — registry included. "Crl.P.L.A.123-L_2020" (Lahore
    registry) and "Crl.P.L.A.123_2020" (principal seat) are DIFFERENT cases
    that share a number, so discarding the registry suffix would silently
    collapse two judgments into one. 306 of the 1,414 ids carry such a suffix.

Measured before ingesting: 0 rows overlap the existing 68. That is expected
rather than surprising — only 6 of the existing SC judgments fall inside this
dataset's 1993-2023 range, and none of the six appear in it.

Usage
-----
  python scripts/ingest_sc_parquet.py --parquet FILE            # dry run
  python scripts/ingest_sc_parquet.py --parquet FILE --apply
  python scripts/ingest_sc_parquet.py --parquet FILE --apply --limit 20
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import collections
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pyarrow.parquet as pq  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.services import citator_service as cs  # noqa: E402
from scripts.ingest_judgments import (  # noqa: E402
    MIN_TEXT_CHARS,
    _embed,
    clean_citations,
    derive_metadata,
    slug,
)

# Read the text and the filename. Never the embeddings — see module docstring.
COLUMNS = ["text", "case_details"]

COURT, PROVINCE, AUTHORITY = "SC", "federal", "binding_national"
SOURCE = "ibtehaj10-supreme-court-parquet"

_WS = re.compile(r"\s+")
# prefix letters, case number, optional registry letter, year.
_CASE_KEY = re.compile(r"^(?P<pre>[^0-9]*?)(?P<num>\d+)(?P<mid>[^0-9]*?)"
                       r"(?P<year>\d{4})\D*$")


def normalised_hash(text: str) -> str:
    return hashlib.sha256(_WS.sub(" ", (text or "")).strip().lower().encode()).hexdigest()


def case_key(identifier: str) -> str | None:
    """Registry-aware identity for a Supreme Court case number.

    Handles both this dataset's "Crl.P.L.A.123-L_2020.pdf" and the existing
    corpus's slugged "SC:crl_p_l_a_123_l_2020", so the two can be compared.
    Returns None when no case number can be read, in which case the caller
    falls back to the text hash alone.
    """
    stem = re.sub(r"\.pdf$", "", identifier or "", flags=re.I)
    stem = re.sub(r"^SC:", "", stem, flags=re.I).lower()
    m = _CASE_KEY.match(stem)
    if not m:
        return None
    prefix = re.sub(r"[^a-z]", "", m.group("pre"))
    registry = re.sub(r"[^a-z]", "", m.group("mid"))
    if len(registry) > 1:          # not a registry letter, don't guess
        registry = ""
    return f"{prefix}:{m.group('num')}:{registry}:{m.group('year')}"


def judgment_id_for(identifier: str) -> str:
    return f"{COURT}:{slug(re.sub(r'.pdf$', '', identifier or '', flags=re.I))}"


def read_rows(path: Path) -> list[tuple[str, str]]:
    """(source filename, text) for every row, embeddings never loaded."""
    table = pq.read_table(str(path), columns=COLUMNS)
    texts = table.column("text").to_pylist()
    details = table.column("case_details").to_pylist()
    rows = []
    for text, detail in zip(texts, details):
        try:
            identifier = ast.literal_eval(detail).get("id", "")
        except Exception:
            identifier = ""
        rows.append((identifier, text or ""))
    return rows


async def with_retry(what, coro_factory, attempts: int = 5):
    """Retry a Mongo write through a transient Atlas network fault.

    The first run of this script died at judgment 255 of 1,405 on
    pymongo._OperationCancelled — the connection to Atlas dropped mid-write
    after ~50 minutes. Nothing was wrong with the data; the run simply had no
    tolerance for a blip. At roughly four hours of CPU embedding, a run that
    aborts on one dropped socket will rarely finish, so writes get a bounded
    backoff. Genuine errors still surface: this gives up after `attempts`
    rather than looping forever.
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except PyMongoError as exc:
            if attempt == attempts:
                raise
            print(f"      {what}: {type(exc).__name__}, retry "
                  f"{attempt}/{attempts - 1} in {delay:.0f}s", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


async def main(args) -> None:
    path = Path(args.parquet)
    if not path.is_file():
        raise SystemExit(f"not a file: {path}")

    # OWN CLIENT, NOT app.db.mongodb.connect_db().
    #
    # The app client sets connectTimeoutMS=5000 and serverSelectionTimeoutMS
    # =5000 to "fail fast instead of hanging if Mongo is down". That is right
    # for a request handler and wrong here: this cluster is a shared M0 in
    # ap-south-1 whose TLS handshake plus replica-set discovery does not
    # reliably fit in five seconds, and a batch job should wait rather than
    # abandon four hours of work. Raw TCP to all three shards answers in
    # under 0.15s, so the link is fine; only the budget was too tight.
    #
    # Kept local to this script so the API keeps its fail-fast behaviour.
    client = AsyncIOMotorClient(
        settings.mongodb_url,
        connectTimeoutMS=30000,
        serverSelectionTimeoutMS=30000,
        socketTimeoutMS=120000,
        retryWrites=True,
    )
    connect_chroma()
    try:
        col = client[settings.db_name]["judgments"]
        vectors = get_chroma().get_or_create_collection(
            "judgments_collection", metadata={"hnsw:space": "cosine"})

        def has_vectors(jid: str) -> bool:
            got = vectors.get(where={"judgment_id": {"$eq": jid}}, include=[], limit=1)
            return bool(got.get("ids"))

        # ── what is already held ─────────────────────────────────────────────
        # TEXT IS DELIBERATELY NOT PROJECTED. Fetching it pulled ~21 KB x every
        # stored judgment across the link on every start — 17 MB now, 40 MB by
        # the end — which is the load this connection keeps dropping under, and
        # a chunked run repays it on every batch.
        #
        # `sha256` already holds the normalised TEXT hash for every row this
        # script wrote, so re-hashing our own writes is waste. The 502
        # originally-ingested judgments store a PDF BYTE hash there instead and
        # so contribute no usable text key — which is safe, because those 502
        # were compared against all 1,414 parquet rows by full text in a
        # one-time check before the first run and zero matched; only 6 of them
        # even fall inside this dataset's 1993-2023 range, and the case key
        # below covers them anyway.
        existing = await with_retry("load index", lambda: col.find(
            {}, {"_id": 1, "court": 1, "sha256": 1, "source": 1}).to_list(None))
        before_total = len(existing)
        before_sc = sum(1 for d in existing if d.get("court") == COURT)
        known_ids = {d["_id"] for d in existing}
        known_hash = {d["sha256"]: d["_id"] for d in existing
                      if d.get("source") == SOURCE and d.get("sha256")}
        known_case = {}
        for d in existing:
            if d.get("court") != COURT:
                continue
            key = case_key(d["_id"])
            if key:
                known_case.setdefault(key, d["_id"])
        print(f"\n  held now: {before_total} judgments, {before_sc} Supreme Court")
        print(f"  dedup keys from existing SC: {len(known_case)} case, "
              f"{len(known_hash)} text")

        # ── plan ─────────────────────────────────────────────────────────────
        rows = read_rows(path)
        print(f"\n  parquet rows: {len(rows)}  (embeddings column not read)")

        todo, stats = [], collections.Counter()
        seen_hash, seen_case = {}, {}
        for identifier, text in rows:
            if len(text.strip()) < MIN_TEXT_CHARS:
                stats["too_short"] += 1
                continue
            digest = normalised_hash(text)
            key = case_key(identifier)
            if digest in known_hash:
                stats["dupe_existing_text"] += 1
                continue
            if key and key in known_case:
                stats["dupe_existing_case"] += 1
                continue
            if digest in seen_hash:
                stats["dupe_within_dataset_text"] += 1
                continue
            if key and key in seen_case:
                stats["dupe_within_dataset_case"] += 1
                continue
            seen_hash[digest] = identifier
            if key:
                seen_case[key] = identifier
            else:
                stats["no_case_key_hash_only"] += 1
            todo.append((identifier, text, digest))

        print(f"  eligible after dedup: {len(todo)}")
        for reason, n in stats.most_common():
            print(f"    {reason:28s} {n}")

        already = []
        remaining = []
        for identifier, text, digest in todo:
            jid = judgment_id_for(identifier)
            # Both stores, or the judgment is invisible — citator search drops a
            # Chroma hit with no Mongo doc, and a Mongo doc with no vectors is
            # never a hit. Same rule as ingest_judgments.
            # Membership in the id set loaded above. A find_one per row was
            # 1,405 round trips on a link that drops.
            if jid in known_ids and has_vectors(jid):
                already.append(jid)
                continue
            remaining.append((identifier, text, digest, jid))
        print(f"  {len(already)} already ingested, {len(remaining)} to process")

        if args.limit:
            remaining = remaining[:args.limit]
            print(f"  --limit {args.limit} applied")

        if not remaining:
            print("\n  Nothing to do.\n")
            return
        if not args.apply:
            est = sum(len(cs._chunk(t)) for _, t, _, _ in remaining)
            print(f"\n  would embed ~{est} chunks")
            print("  Dry run — nothing written. Re-run with --apply.\n")
            return

        # ── ingest ───────────────────────────────────────────────────────────
        done = collections.Counter()
        dropped_cites = 0
        for i, (identifier, text, digest, jid) in enumerate(remaining, 1):
            meta = derive_metadata(text, Path(identifier))
            citations, dropped = clean_citations(text)
            dropped_cites += dropped

            doc = {
                "_id": jid,
                "court": COURT,
                "province": PROVINCE,
                "authority": AUTHORITY,
                "year": meta.get("year"),
                "case_no": meta.get("case_no", ""),
                "title": meta.get("title", "") or Path(identifier).stem[:120],
                "judge": meta.get("judge", ""),
                "citations_out": citations,
                "text": text,
                "text_chars": len(text),
                "source_file": identifier,
                "sha256": digest,          # of normalised TEXT, not PDF bytes
                "source": SOURCE,
                "ingested_at": datetime.now(timezone.utc),
            }
            await with_retry(f"write {jid}",
                             lambda: col.replace_one({"_id": jid}, doc, upsert=True))
            done["mongo"] += 1

            chunks = cs._chunk(text)
            if chunks:
                await asyncio.to_thread(
                    _embed, jid, chunks, COURT, PROVINCE, AUTHORITY, doc)
                done["embedded"] += 1
                done["chunks"] += len(chunks)

            if i % 25 == 0 or i == len(remaining):
                print(f"    {i}/{len(remaining)}  mongo={done['mongo']} "
                      f"embedded={done['embedded']} chunks={done['chunks']}",
                      flush=True)

        after_total = await col.count_documents({})
        after_sc = await col.count_documents({"court": COURT})
        print(f"\n  stored   : {done['mongo']}")
        print(f"  embedded : {done['embedded']}  ({done['chunks']} chunks)")
        print(f"  citations dropped as impossible years: {dropped_cites}")
        print(f"\n  judgments   {before_total} -> {after_total}")
        print(f"  Supreme Ct  {before_sc} -> {after_sc}\n")
    finally:
        client.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Ingest SC judgments from parquet.")
    p.add_argument("--parquet", required=True, help="path to the parquet file")
    p.add_argument("--apply", action="store_true", help="perform the ingest")
    p.add_argument("--limit", type=int, default=0, help="process only the first N")
    asyncio.run(main(p.parse_args()))
