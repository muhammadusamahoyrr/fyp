"""
Drop rows from ChromaDB `lawyers_collection` that no longer correspond to a
KYC-verified, active lawyer in MongoDB.

WHY THIS EXISTS
---------------
Nothing in the application ever removed a lawyer from the vector store. Embeds
were written by two admin endpoints; rejection, deactivation and account
closure wrote nothing. So a deleted lawyer's vector outlived the lawyer.

That is not cosmetic. `match_lawyers_for_case` branched on whether the semantic
query returned *any* rows, before checking whether those rows resolved to a real
lawyer. On 2026-09-01 `lawyers_collection` held exactly two rows — `test-lawyer-001`
and `e2e-lawyer-seed-001`, both smoke-test accounts long since deleted from Mongo,
both `province: punjab`. For every Punjab or federal case (45 of 59 real cases)
the matcher took the semantic branch, resolved both hits to nothing, produced an
empty list, and fell through to a last-resort listing — so the province- and
case-type-filtered MongoDB path never ran at all.

The application now deletes vectors on rejection/deactivation/closure and heals
unresolvable hits at query time. This script is the maintenance sweep: run it
after a bulk data change (such as `purge_test_fixtures.py`) or any time the
store and the database may have drifted.

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/purge_orphan_lawyer_vectors.py           # dry run
    ./venv/Scripts/python.exe scripts/purge_orphan_lawyer_vectors.py --apply   # delete
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.ai.lawyer_embeddings import LAWYERS_COLLECTION  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; without it the script only reports")
    args = ap.parse_args()

    connect_chroma()
    col = get_chroma().get_or_create_collection(
        name=LAWYERS_COLLECTION, metadata={"hnsw:space": "cosine"}
    )
    total = col.count()
    print(f"{LAWYERS_COLLECTION}: {total} row(s)")
    if total == 0:
        print("nothing to purge")
        return 0

    stored = col.get(include=["metadatas"])
    stored_ids = list(stored["ids"])
    metas = stored["metadatas"] or [{}] * len(stored_ids)

    client = AsyncIOMotorClient(os.getenv("MONGODB_URL"), serverSelectionTimeoutMS=10000)
    db = client[os.getenv("DB_NAME", "attorney_ai")]

    # The invariant the store is meant to hold: every row is a KYC-verified,
    # active lawyer. Anything else is an orphan — deleted, deactivated,
    # de-verified, or never a lawyer to begin with.
    valid_ids = set()
    async for u in db["users"].find(
        {"role": "lawyer", "lawyer_profile.kyc_verified": True, "is_active": True},
        {"_id": 1},
    ):
        valid_ids.add(u["_id"])

    orphans: list[tuple[str, str]] = []
    for i, lid in enumerate(stored_ids):
        if lid in valid_ids:
            continue
        doc = await db["users"].find_one({"_id": lid}, {"role": 1, "is_active": 1,
                                                       "lawyer_profile.kyc_verified": 1})
        if doc is None:
            why = "no such user in Mongo"
        elif doc.get("role") != "lawyer":
            why = f"role={doc.get('role')}"
        elif not doc.get("is_active", True):
            why = "inactive"
        else:
            why = "not KYC-verified"
        prov = (metas[i] or {}).get("province", "?")
        orphans.append((lid, f"{why}, province={prov}"))

    print(f"valid (verified+active lawyers in Mongo): {len(valid_ids)}")
    print(f"orphan rows: {len(orphans)}")
    for lid, why in orphans:
        print(f"  {lid:26} {why}")

    if not orphans:
        client.close()
        return 0

    if not args.apply:
        print("\nDRY RUN - nothing deleted. Re-run with --apply.")
        client.close()
        return 0

    col.delete(ids=[lid for lid, _ in orphans])
    print(f"\ndeleted {len(orphans)} orphan row(s); {col.count()} remaining")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
