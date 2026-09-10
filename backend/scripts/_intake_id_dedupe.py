"""Remove duplicate cases so `uniq_case_per_intake` can be enforced.

DRY RUN BY DEFAULT. Nothing is deleted without `--apply`.

Read `scripts/_intake_id_census.py` first; this script is the second half of it
and shares its reasoning. For each intake that produced more than one case, the
intake's own `case_id` names the case the client was actually shown. The others
are the losing side of a race that no longer exists.

WHAT THIS REFUSES TO DO
-----------------------
It will not delete a stray that carries anything: documents, appointments,
engagements, payments, milestones, hearings or messages. A case with any of
those is a case somebody worked on, and whether that work should be moved or
discarded is a decision about a real person's legal matter, not a data cleanup.
Those groups are reported and skipped, and the index stays uncreatable until a
human resolves them — which is the correct outcome, because the alternative is
this script quietly destroying the only record of something.

It will also not act on a group whose intake does not name a keeper. Without
that pointer there is nothing to say which case the client saw, and picking by
timestamp would be a guess with a legal record attached.

Every deletion is written to a JSON journal beside this script first, so a
mistaken run can be reconstructed.

Run:  backend/venv/Scripts/python.exe scripts/_intake_id_dedupe.py
      backend/venv/Scripts/python.exe scripts/_intake_id_dedupe.py --apply
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

JOURNAL = Path(__file__).resolve().parent / "_intake_id_dedupe_journal.json"

ATTACHMENT_COLLECTIONS = ("documents", "appointments", "engagements", "payments")
EMBEDDED_LISTS = ("milestones", "hearing_dates", "messages", "tasks")


async def _attachments(db, case_id: str) -> dict:
    counts = {}
    for name in ATTACHMENT_COLLECTIONS:
        counts[name] = await db[name].count_documents({"case_id": case_id})
    case = await db["cases"].find_one({"_id": case_id})
    for field in EMBEDDED_LISTS:
        counts[field] = len((case or {}).get(field) or [])
    return {k: v for k, v in counts.items() if v}


async def main(apply: bool) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.core.config import settings

    client = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=10_000)
    db = client[settings.db_name]
    cases = db["cases"]

    groups = await cases.aggregate([
        {"$match": {"intake_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$intake_id", "n": {"$sum": 1},
                    "case_ids": {"$push": "$_id"}}},
        {"$match": {"n": {"$gt": 1}}},
    ]).to_list(length=None)

    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] database={settings.db_name}  duplicate groups={len(groups)}")
    if not groups:
        print("Nothing to do.")
        return 0

    doomed: list[dict] = []
    skipped: list[str] = []

    for g in groups:
        intake = await db["intakes"].find_one({"_id": g["_id"]}, {"case_id": 1})
        keeper = (intake or {}).get("case_id")
        if not keeper or keeper not in g["case_ids"]:
            print(f"SKIP intake {g['_id']}: intake names no keeper among its cases")
            skipped.append(g["_id"])
            continue

        for case_id in g["case_ids"]:
            if case_id == keeper:
                continue
            busy = await _attachments(db, case_id)
            if busy:
                print(f"SKIP case {case_id} (intake {g['_id']}): carries {busy}")
                skipped.append(g["_id"])
                continue
            doc = await cases.find_one({"_id": case_id})
            doomed.append(doc)
            print(f"DELETE case {case_id}  {doc.get('case_number')}  "
                  f"(keeper {keeper})")

    if not doomed:
        print("\nNothing safely removable.")
        return 1

    if not apply:
        print(f"\n{len(doomed)} case(s) would be deleted. Re-run with --apply.")
        return 0

    JOURNAL.write_text(
        json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                    "database": settings.db_name,
                    "deleted": doomed}, default=str, indent=2),
        encoding="utf-8",
    )
    print(f"\nJournal written to {JOURNAL}")

    result = await cases.delete_many({"_id": {"$in": [d["_id"] for d in doomed]}})
    print(f"Deleted {result.deleted_count} case(s).")

    if skipped:
        print(f"{len(set(skipped))} group(s) still need a human decision; the "
              f"index cannot be created until they are resolved.")
        return 1

    print("All groups resolved. Restart the application to create "
          "uniq_case_per_intake.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--apply" in sys.argv)))
