"""backfill_jurisdiction.py — set province/authority where the citator path omitted them.

WHY THIS EXISTS
---------------
`province` and `authority` are what the precedent-aware ranker reads. A chunk
without them is treated as persuasive everywhere, so a Lahore High Court
judgment that binds in Punjab is ranked as though it binds nowhere.

Two ingest paths write judgment vectors, and only one of them sets the fields:

  * ingest_judgments.py  — passes (court, province, authority) from COURTS into
    both the Mongo document and the Chroma metadata.
  * citator_service._embed_and_upsert — wrote judgment_id/court/year/judge/title
    and nothing else.

Everything ingested through the citator therefore landed without jurisdiction:
200 LHC judgments, 3,230 chunks. `test_corpus_health.py::
test_every_judgment_chunk_has_a_jurisdiction` is the test that catches it, and
it could not report the gap while judgments_collection was unreadable.

This backfills the existing rows. The forward fix is in citator_service, so the
gap does not reappear on the next judgment ingested through that path.

WHERE THE VALUES COME FROM
--------------------------
`ingest_judgments.COURTS` — imported rather than restated, because a second copy
of the court-to-jurisdiction mapping is a second thing to get wrong. A court
this script has no mapping for is reported and skipped, never guessed.

BOTH STORES, OR THE FIX IS HALF-APPLIED
---------------------------------------
Mongo is the durable copy and Chroma is what the ranker actually reads, so both
are updated. Chroma metadata is rewritten with the chunk's existing fields plus
the two new ones — never replaced wholesale, which would drop judge/title/year.

Updates go in batches of 32, the same size ingest and rebuild use: the crash
that started this whole recovery was a long single native call.

Usage
-----
  python scripts/backfill_jurisdiction.py            # dry run
  python scripts/backfill_jurisdiction.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402
from ingest_judgments import COURTS  # noqa: E402

COLLECTION = "judgments_collection"
BATCH = 32

# court code -> (province, authority), inverted from the folder-keyed COURTS.
BY_CODE: dict[str, tuple[str, str]] = {
    code: (province, authority) for code, province, authority in COURTS.values()
}


def _missing(meta: dict) -> bool:
    return not meta.get("province") or not meta.get("authority")


async def main(apply: bool) -> int:
    await connect_db()
    connect_chroma()
    mongo = get_database()["judgments"]
    col = get_chroma().get_collection(COLLECTION)

    got = col.get(include=["metadatas"])
    ids, metas = got["ids"], got["metadatas"]
    gaps = [(i, m) for i, m in zip(ids, metas) if _missing(m or {})]

    print(f"\n  {COLLECTION}: {len(ids)} chunks, {len(gaps)} lacking jurisdiction")
    if not gaps:
        print("  Nothing to do.\n")
        return 0

    by_court: dict[str, list] = {}
    for cid, m in gaps:
        by_court.setdefault((m or {}).get("court") or "", []).append((cid, m))

    unknown = [c for c in by_court if c not in BY_CODE]
    for c in unknown:
        print(f"  SKIPPING {len(by_court[c])} chunk(s) of unmapped court {c!r}")

    plan = [(c, v) for c, v in by_court.items() if c in BY_CODE]
    for court, rows in plan:
        province, authority = BY_CODE[court]
        judgments = {(m or {}).get("judgment_id") for _, m in rows}
        print(f"  {court}: {len(rows)} chunks / {len(judgments)} judgments "
              f"-> province={province!r} authority={authority!r}")

    if not apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
        return 0

    for court, rows in plan:
        province, authority = BY_CODE[court]

        # Mongo first: it is the durable copy, so if this run dies partway the
        # source of truth already carries the fields and a re-run is cheap.
        jids = sorted({(m or {}).get("judgment_id") for _, m in rows})
        res = await mongo.update_many(
            {"_id": {"$in": jids}},
            {"$set": {"province": province, "authority": authority}},
        )
        print(f"  mongo {court}: matched={res.matched_count} "
              f"modified={res.modified_count}")

        for start in range(0, len(rows), BATCH):
            chunk = rows[start:start + BATCH]
            col.update(
                ids=[cid for cid, _ in chunk],
                metadatas=[{**(m or {}), "province": province,
                            "authority": authority} for _, m in chunk],
            )
        print(f"  chroma {court}: {len(rows)} chunk(s) updated")

    after = col.get(include=["metadatas"])
    left = sum(1 for m in after["metadatas"] if _missing(m or {}))
    print(f"\n  {COLLECTION}: {left} chunk(s) still lacking jurisdiction\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="perform the backfill")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.apply)))
