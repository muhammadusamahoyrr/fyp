"""Run the citator Redis-Streams consumers (parse + embed stages).

Usage (from backend/, with the venv python; REDIS_URL must be set — Redis 5.0+,
XAUTOCLAIM recovery needs 6.2+):

  python scripts/citator_workers.py --role parse   # parse+store stage
  python scripts/citator_workers.py --role embed   # chunk+embed stage
  python scripts/citator_workers.py --role both    # both in one process (dev)

Scale a stage by starting more processes with the same --role: entries in that
group are split across all its consumers. Feed the pipeline with
  python scripts/ingest_lhc_judgments.py --year YYYY --start A --end B --stream

⚠️  RUN ONLY DURING ACTIVE INGEST/DEMO — DO NOT LEAVE RUNNING 24/7.
The consumer loop continuously polls Redis (XAUTOCLAIM + a blocking XREADGROUP
every CITATOR_BLOCK_MS). Against a hosted Redis on a metered plan (e.g. Upstash
free tier = 500k commands/month) an idle worker still burns commands and can
exhaust the monthly quota in a few days. Start it when you're ingesting or
demoing, and stop it (Ctrl-C) when done. CITATOR_BLOCK_MS is set to 30000 in
.env to minimise idle polling; raise it further to conserve more.
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
    p.add_argument("--role", choices=["parse", "embed", "both"], default="both")
    args = p.parse_args()

    await connect_db()
    connect_chroma()

    from app.core.redis_client import get_redis
    if get_redis() is None:
        p.error("REDIS_URL not set — streaming consumers require Redis 5.0+")
    from app.services import citator_stream as st
    await st.ensure_groups()

    tasks = []
    if args.role in ("parse", "both"):
        tasks.append(asyncio.create_task(st.run_parse_worker()))
    if args.role in ("embed", "both"):
        tasks.append(asyncio.create_task(st.run_embed_worker()))

    print(f"citator workers running (role={args.role}). Ctrl-C to stop.")
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
