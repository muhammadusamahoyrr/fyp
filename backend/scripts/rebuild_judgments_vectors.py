"""rebuild_judgments_vectors.py — regenerate judgments_collection from Mongo.

WHY THIS EXISTS
---------------
During the Supreme Court parquet ingest, one batch segfaulted (exit 139) inside
chromadb's native HNSW bindings. Every subsequent operation on
judgments_collection then failed with:

    chromadb.errors.InternalError: Error executing plan: Error sending backfill
    request to compactor: Failed to apply logs to the hnsw segment writer

The collection cannot even be counted. Damage is confined to it — criminal
(3,306), civil (4,648), family (989) and constitutional (1,736) all read
normally, so the retrieval pipeline is unaffected; only the citator, which
searches judgments_collection, is down.

NOTHING IS PERMANENTLY LOST, WHICH IS WHY THIS IS CHEAP TO FIX
---------------------------------------------------------------
ingest_judgments.py and ingest_sc_parquet.py both write the Mongo document
BEFORE the vectors, precisely so that Mongo is the durable copy and Chroma is a
derived index. All 1,006 judgments hold their full text. So the vectors are
regenerable: this re-chunks and re-embeds from Mongo rather than trying to
salvage a corrupted index.

WRITES TO A NEW COLLECTION, THEN SWAPS
---------------------------------------
The rebuild goes to `judgments_collection_rebuild` and is verified before the
broken collection is touched. Rebuilding in place would mean that a crash
halfway leaves NO working collection at all — and a crash halfway is exactly
what happened last time. The swap at the end is two renames, and only runs
after the new collection answers a real query.

`chroma_data` was copied to `chroma_data_backup_2026-08-27` before any of this.

Usage
-----
  python scripts/rebuild_judgments_vectors.py                  # dry run
  python scripts/rebuild_judgments_vectors.py --apply
  python scripts/rebuild_judgments_vectors.py --apply --swap   # rebuild + swap
  python scripts/rebuild_judgments_vectors.py --swap-only      # swap a finished rebuild
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.services import citator_service as cs  # noqa: E402

LIVE = "judgments_collection"
REBUILD = "judgments_collection_rebuild"
BROKEN = "judgments_collection_broken_2026_08_27"

# Embedding batch. Small on purpose: the crash that started this happened deep
# in a long-running native call, and short calls give the process more places to
# survive an interruption between.
BATCH = 32


def _embed_batch(collection, ids, docs, metas) -> None:
    from app.ai.pipelines.retriever import _embeddings
    collection.upsert(
        ids=ids,
        embeddings=_embeddings().embed_documents(docs),
        documents=docs,
        metadatas=metas,
    )


async def rebuild(apply: bool) -> int:
    client = AsyncIOMotorClient(
        settings.mongodb_url,
        connectTimeoutMS=30000,
        serverSelectionTimeoutMS=30000,
        socketTimeoutMS=120000,
    )
    col = client[settings.db_name]["judgments"]
    connect_chroma()
    chroma = get_chroma()

    docs = await col.find(
        {}, {"_id": 1, "text": 1, "court": 1, "province": 1, "authority": 1,
             "year": 1, "judge": 1, "title": 1}
    ).to_list(None)
    client.close()
    print(f"\n  judgments in Mongo: {len(docs)}")

    planned = [(d, cs._chunk(d.get("text") or "")) for d in docs]
    planned = [(d, ch) for d, ch in planned if ch]
    total_chunks = sum(len(ch) for _, ch in planned)
    print(f"  with usable text  : {len(planned)}")
    print(f"  chunks to embed   : {total_chunks}")

    if not apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
        return 0

    target = chroma.get_or_create_collection(
        REBUILD, metadata={"hnsw:space": "cosine"})
    done_ids = set(target.get(include=[])["ids"])
    if done_ids:
        print(f"  resuming: {len(done_ids)} chunk(s) already present")

    started = time.time()
    written = skipped = 0
    ids: list[str] = []
    texts: list[str] = []
    metas: list[dict] = []

    for n, (d, chunks) in enumerate(planned, 1):
        jid = d["_id"]
        for i, chunk in enumerate(chunks):
            cid = f"{jid}:{i}"
            if cid in done_ids:
                skipped += 1
                continue
            ids.append(cid)
            texts.append(chunk)
            metas.append({
                "judgment_id": jid,
                "court": d.get("court") or "",
                "province": d.get("province") or "",
                "authority": d.get("authority") or "",
                "year": d.get("year") or 0,
                "judge": d.get("judge") or "",
                "title": d.get("title") or "",
            })
            if len(ids) >= BATCH:
                await asyncio.to_thread(_embed_batch, target, ids, texts, metas)
                written += len(ids)
                ids, texts, metas = [], [], []

        if n % 25 == 0 or n == len(planned):
            rate = written / max(time.time() - started, 1e-9)
            left = (total_chunks - skipped - written) / rate if rate else 0
            print(f"    {n}/{len(planned)} judgments  chunks={written} "
                  f"skipped={skipped}  {rate:.1f}/s  eta {left/60:.0f}m",
                  flush=True)

    if ids:
        await asyncio.to_thread(_embed_batch, target, ids, texts, metas)
        written += len(ids)

    print(f"\n  rebuilt: {written} chunks written, {skipped} already present")
    print(f"  {REBUILD} count: {target.count()}")
    return 0


def verify() -> bool:
    """The rebuild must answer a real query before it replaces anything.

    The probe is embedded with the SAME model that wrote the collection, and
    handed to Chroma as `query_embeddings`. Passing `query_texts` instead makes
    Chroma reach for its own default embedder (all-MiniLM-L6-v2, 384-d) against
    vectors written by `_embeddings()` at 768-d; the query then dies with a
    dimension mismatch, which reads as "the rebuild is broken" when the rebuild
    is fine. Since swap() gates on this, that mistake blocks the promotion of a
    perfectly good collection.
    """
    from app.ai.pipelines.retriever import _embeddings

    chroma = get_chroma()
    try:
        target = chroma.get_collection(REBUILD)
    except Exception as exc:
        print(f"  {REBUILD} missing: {exc}")
        return False
    try:
        n = target.count()
        qv = _embeddings().embed_query("bail in a murder case under section 302")
        # Compare against what is actually stored, so a model/config drift is
        # reported as the dimension mismatch it is rather than a bare query error.
        stored = target.peek(limit=1).get("embeddings")
        if stored is not None and len(stored) and len(stored[0]) != len(qv):
            print(f"  verification FAILED: {REBUILD} holds {len(stored[0])}-d "
                  f"vectors but the query embedder produced {len(qv)}-d")
            return False
        got = target.query(query_embeddings=[qv], n_results=3)
        hits = got["ids"][0]
        print(f"  {REBUILD}: count={n}, dim={len(qv)}, "
              f"query returned {len(hits)} hit(s)")
        print(f"    e.g. {hits[:3]}")
        return n > 0 and len(hits) > 0
    except Exception as exc:
        print(f"  verification FAILED: {type(exc).__name__}: {str(exc)[:120]}")
        return False


def swap() -> int:
    """Retire the broken collection and promote the rebuild.

    Renamed, not deleted. A corrupted index is still evidence, and dropping the
    only copy of something while diagnosing what corrupted it is how a bad
    afternoon becomes a bad week. `chroma_data_backup_2026-08-27` holds a full
    copy regardless.
    """
    chroma = get_chroma()
    if not verify():
        print("\n  NOT swapping — rebuild did not verify.\n")
        return 1
    try:
        chroma.get_collection(LIVE).modify(name=BROKEN)
        print(f"  renamed {LIVE} -> {BROKEN}")
    except Exception as exc:
        # Deliberately NOT falling back to deletion. The corrupted index is the
        # only first-hand evidence of what caused this, and preserving it is the
        # entire point of the rename. If the rename cannot be done, stop and let
        # a human decide — an automatic delete turns a recoverable situation
        # into an unrecoverable one without anyone being asked.
        print(f"  could not rename {LIVE} "
              f"({type(exc).__name__}: {str(exc)[:100]})")
        print(f"  NOT swapping, NOT deleting — {LIVE} left exactly as it is.")
        return 1
    chroma.get_collection(REBUILD).modify(name=LIVE)
    print(f"  renamed {REBUILD} -> {LIVE}")
    print(f"  {LIVE} count: {chroma.get_collection(LIVE).count()}\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="perform the rebuild")
    p.add_argument("--swap", action="store_true", help="swap in after rebuilding")
    p.add_argument("--swap-only", action="store_true", help="only swap")
    a = p.parse_args()

    if a.swap_only:
        connect_chroma()
        raise SystemExit(swap())
    rc = asyncio.run(rebuild(a.apply))
    if rc == 0 and a.apply and a.swap:
        rc = swap()
    raise SystemExit(rc)
