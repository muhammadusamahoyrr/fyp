"""
Embed every KYC-verified, active lawyer into ChromaDB `lawyers_collection`,
reporting the outcome for each one.

WHY THIS EXISTS
---------------
Lawyers were only ever embedded by an admin remembering to POST to
/admin/lawyers/embed-all. Nobody did, so on 2026-09-01 the collection held two
smoke-test rows and not one real lawyer. The application now embeds on KYC
approval and on profile edits; this script is the one-off catch-up for everyone
approved before that wiring existed, and the repair tool if the store is ever
rebuilt.

WHY NOT `POST /admin/lawyers/embed-all`
---------------------------------------
That endpoint calls `embed_all_lawyers`, which swallows every exception in a
bare `except: pass` and returns a single integer — so an empty profile and a
crashed model load are indistinguishable, and "embedded 9" tells you nothing
about the other 16. It also runs inside a request: the first embedding in a
process pays a multi-second model load on a machine with no GPU, so a bulk run
there is a timeout waiting to happen.

WHAT TO EXPECT
--------------
`embed_lawyer` returns False for a profile with no text to embed — no province,
no specializations, no bio, no experience, no past cases. Those lawyers are
reported as `skipped (empty profile)`, not as failures. A lawyer who cannot be
described cannot be matched, and the fix is the profile, not the index. (KYC
approval now refuses a profile with no province or specialization, so new
accounts cannot land in that state.)

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/backfill_lawyer_embeddings.py           # dry run
    ./venv/Scripts/python.exe scripts/backfill_lawyer_embeddings.py --apply   # embed
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.ai.lawyer_embeddings import (  # noqa: E402
    LAWYERS_COLLECTION,
    build_profile_text,
    embed_lawyer,
)
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually embed; without it the script only reports")
    args = ap.parse_args()

    connect_chroma()
    await connect_db()
    db = get_database()

    col = get_chroma().get_or_create_collection(
        name=LAWYERS_COLLECTION, metadata={"hnsw:space": "cosine"}
    )
    print(f"{LAWYERS_COLLECTION}: {col.count()} row(s) before")

    lawyers = [
        u async for u in db["users"].find(
            {"role": "lawyer", "lawyer_profile.kyc_verified": True, "is_active": True}
        )
    ]
    print(f"verified + active lawyers: {len(lawyers)}\n")

    # Predict the outcome without loading the model, so a dry run is instant
    # and still tells you how many of these profiles have anything to embed.
    plan: list[tuple[str, str, bool]] = []
    for u in lawyers:
        cases = await db["cases"].find_one({"lawyer_id": u["_id"]})
        text = build_profile_text(u, [cases] if cases else [])
        plan.append((u["_id"], u.get("email") or "(no email)", bool(text.strip())))

    embeddable = [p for p in plan if p[2]]
    empty = [p for p in plan if not p[2]]

    if not args.apply:
        for lid, email, ok in plan:
            state = "would embed" if ok else "SKIP (empty profile)"
            print(f"  {state:22} {lid:26} {email}")
        print(f"\n{len(embeddable)} would embed, {len(empty)} would be skipped")
        print("DRY RUN - nothing written. Re-run with --apply.")
        return 0

    print("embedding (the first call loads the model - expect a pause)\n")
    counts = {"embedded": 0, "skipped": 0, "failed": 0}
    started = time.monotonic()

    for lid, email, expected in plan:
        t0 = time.monotonic()
        try:
            ok = await embed_lawyer(lid)
        except Exception as exc:  # reported per lawyer, never swallowed
            counts["failed"] += 1
            print(f"  FAILED   {lid:26} {email:34} {type(exc).__name__}: {exc}")
            continue
        took = time.monotonic() - t0
        if ok:
            counts["embedded"] += 1
            print(f"  embedded {lid:26} {email:34} {took:5.1f}s")
        else:
            counts["skipped"] += 1
            print(f"  skipped  {lid:26} {email:34} empty profile — nothing to embed")

    elapsed = time.monotonic() - started
    print(f"\nembedded {counts['embedded']}, skipped {counts['skipped']}, "
          f"failed {counts['failed']} in {elapsed:.1f}s")
    print(f"{LAWYERS_COLLECTION}: {col.count()} row(s) after")

    if counts["skipped"]:
        print("\nSkipped lawyers have no province, specialization, bio, experience "
              "or past case to describe them. They cannot be matched until their "
              "profile is filled in — that is a data problem, not an index one.")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
