"""Bulk-ingest LHC reported judgments into the citator corpus.

Usage (from backend/, with the venv python):
  python scripts/ingest_lhc_judgments.py --latest            # listing page (~50, w/ tag lines)
  python scripts/ingest_lhc_judgments.py --year 2026 --start 4400 --end 4480
  python scripts/ingest_lhc_judgments.py --year 2025 --start 1 --end 500

  # Streaming mode: fetch only, hand each judgment to the Redis-Streams
  # pipeline (parse + embed run in separate worker processes). Requires
  # REDIS_URL (Redis 5.0+). Run the consumers with scripts/citator_workers.py.
  python scripts/ingest_lhc_judgments.py --year 2025 --start 1 --end 500 --stream

Idempotent — already-ingested ids are skipped, so ranges can be re-run and
extended. Throttled to be polite to the court server.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.chroma import connect_chroma
from app.db.mongodb import connect_db, close_db


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--latest", action="store_true", help="ingest from the listing page")
    p.add_argument("--year", type=int)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int)
    p.add_argument("--delay", type=float, default=1.0, help="seconds between fetches")
    p.add_argument("--stream", action="store_true",
                   help="fetch only; enqueue to the Redis-Streams pipeline (parse+embed run as separate workers)")
    args = p.parse_args()

    await connect_db()
    connect_chroma()
    from app.services import citator_service as cs

    st = None
    if args.stream:
        from app.core.redis_client import get_redis
        if get_redis() is None:
            p.error("--stream requires REDIS_URL (Redis 5.0+)")
        from app.services import citator_stream as st
        await st.ensure_groups()

    async def handle(neutral_id: str, listing_meta: dict | None) -> str:
        """Return one of: 'ok' (ingested/queued), 'skip' (already have it),
        'miss' (no PDF). In --stream mode this fetches then XADDs; otherwise it
        runs the full inline fetch→parse→store→embed."""
        if st is None:
            doc = await cs.ingest_judgment(neutral_id, listing_meta=listing_meta)
            if doc is None:
                return "miss"
            return "ok"
        # Streaming: don't re-fetch known ids (polite to the court server).
        if await cs._judgments_col().find_one({"_id": neutral_id}, {"_id": 1}):
            return "skip"
        text = await cs.fetch_pdf_text(neutral_id)
        if not text or len(text.strip()) < 200:
            return "miss"
        await st.produce_fetched(neutral_id, text, listing_meta)
        return "ok"

    ingested = skipped = missing = 0
    try:
        if args.latest:
            items = await cs.fetch_listing()
            print(f"Listing page: {len(items)} judgments")
            for it in items:
                res = await handle(it["neutral_id"], it)
                if res == "miss":
                    missing += 1
                    print(f"  MISS {it['neutral_id']}")
                elif res == "skip":
                    skipped += 1
                else:
                    ingested += 1
                    print(f"  {'QUEUED' if st else 'OK'} {it['neutral_id']}  {str(it.get('title'))[:60]}")
                await asyncio.sleep(args.delay)
        elif args.year and args.end:
            errors = 0
            for seq in range(args.start, args.end + 1):
                nid = f"{args.year}LHC{seq}"
                # Resilient: a transient network blip must not abort a multi-hour
                # sweep. Skip the item, back off, and keep going. Idempotent, so a
                # later re-run of the same range fills anything skipped here.
                try:
                    res = await handle(nid, None)
                except Exception as e:
                    errors += 1
                    print(f"  ERR  {nid}  {type(e).__name__}: {str(e)[:80]}")
                    await asyncio.sleep(min(args.delay * 5, 15))
                    continue
                if res == "miss":
                    missing += 1
                elif res == "skip":
                    skipped += 1
                else:
                    ingested += 1
                    print(f"  {'QUEUED' if st else 'OK'} {nid}")
                await asyncio.sleep(args.delay)
            if errors:
                print(f"  ({errors} transient errors skipped — re-run the range to backfill)")
        else:
            p.error("use --latest or --year with --end")

        verb = "queued" if st else "ingested/existing"
        print(f"\nDone. {verb}={ingested} skipped={skipped} missing={missing}")
        if st is not None:
            print(await st.stream_stats())
        else:
            print(await cs.corpus_stats())
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
