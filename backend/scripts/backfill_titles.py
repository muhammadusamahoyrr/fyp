"""backfill_titles.py — re-derive titles the first-page parser used to miss.

WHY THIS EXISTS
---------------
73 judgments reached the corpus with no title at all. They are not damaged and
nothing about them failed loudly: citator search returns them, ranks them
correctly, and shows them with no case name, so a hit reads as a bare neutral
id like `2026LHC1` with no indication of who the parties are.

The cause was one layout. parse_metadata looked for "Versus" alone on a line
between the two parties, which is what the reported-judgment PDFs use. Order
sheets do not: they put both parties on a single line, or open the line with
"Vs." and leave the first party on the lines above. citator_service now handles
all three; this repairs the documents ingested before it did.

66 of the 73 are recoverable. The remaining 7 carry no versus token anywhere in
their first page and are left alone rather than given a guessed title — a wrong
case name is worse than a missing one, because it reads as authoritative.

BOTH STORES
-----------
Mongo holds the document and Chroma carries `title` in every chunk's metadata,
which is what the citator renders. Updating one and not the other leaves the
search results still nameless, or leaves the next rebuild to undo the fix.

Usage
-----
  python scripts/backfill_titles.py            # dry run
  python scripts/backfill_titles.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from pymongo import UpdateOne  # noqa: E402

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402
from app.services.citator_service import _parse_title  # noqa: E402

COLLECTION = "judgments_collection"
BATCH = 32
HEAD_CHARS = 2500  # what parse_metadata itself looks at


async def main(apply: bool) -> int:
    await connect_db()
    connect_chroma()
    mongo = get_database()["judgments"]
    col = get_chroma().get_collection(COLLECTION)

    # Only the head is needed, and pulling whole judgment texts for the entire
    # corpus is minutes of transfer on this link for data that is discarded.
    cursor = mongo.aggregate([
        {"$match": {"$or": [{"title": {"$exists": False}},
                            {"title": None}, {"title": ""}]}},
        {"$project": {"head": {"$substrCP": [{"$ifNull": ["$text", ""]},
                                             0, HEAD_CHARS]}}},
    ])

    found: dict[str, str] = {}
    unparsed: list[str] = []
    async for doc in cursor:
        title = _parse_title(doc.get("head") or "")
        if title:
            found[doc["_id"]] = title
        else:
            unparsed.append(doc["_id"])

    print(f"\n  untitled judgments : {len(found) + len(unparsed)}")
    print(f"  title recovered    : {len(found)}")
    print(f"  no versus token    : {len(unparsed)} (left untitled: "
          f"{', '.join(unparsed[:6])}{' ...' if len(unparsed) > 6 else ''})")
    for jid, title in list(found.items())[:8]:
        print(f"    {jid:14s} {title}")

    if not found:
        print("\n  Nothing to do.\n")
        return 0
    if not apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
        return 0

    res = await mongo.bulk_write([
        UpdateOne({"_id": jid}, {"$set": {"title": t}})
        for jid, t in found.items()
    ])
    print(f"\n  mongo : matched={res.matched_count} modified={res.modified_count}")

    # Chroma keeps `title` on every chunk, so each judgment's chunks all need it.
    got = col.get(where={"judgment_id": {"$in": list(found)}},
                  include=["metadatas"])
    ids, metas = got["ids"], got["metadatas"]
    for start in range(0, len(ids), BATCH):
        sl = slice(start, start + BATCH)
        col.update(
            ids=ids[sl],
            metadatas=[{**(m or {}), "title": found[m["judgment_id"]]}
                       for m in metas[sl]],
        )
    print(f"  chroma: {len(ids)} chunk(s) updated")

    left = sum(1 for m in col.get(include=["metadatas"])["metadatas"]
               if not m.get("title"))
    print(f"\n  chunks still without a title: {left}\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="write the titles")
    a = p.parse_args()
    raise SystemExit(asyncio.run(main(a.apply)))
