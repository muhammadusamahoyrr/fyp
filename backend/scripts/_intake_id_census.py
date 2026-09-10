"""READ-ONLY census: cases that share an intake_id.

One finished intake must produce exactly one case. `convert_to_case` enforces
that now — an atomic claim, and the case pinned to the intake the moment it
exists — but that guard shipped on 2026-09-10 and every duplicate created
before it is still in the collection.

This script does not fix anything. It cannot: for each duplicate group the
intake's own `case_id` names the keeper, but a stray may have accumulated
documents, messages, hearings or an engagement, and deleting one of those is a
decision about a real person's legal matter. So it reports, with enough context
to make that decision, and stops.

It also reports whether the partial unique index that would make this
structurally impossible can be created yet — it cannot while duplicates exist,
and `create_indexes` runs in the startup lifespan, so adding it blind would
take the application down on boot.

Run:  backend/venv/Scripts/python.exe scripts/_intake_id_census.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.core.config import settings

    client = AsyncIOMotorClient(settings.mongodb_url, serverSelectionTimeoutMS=10_000)
    db = client[settings.db_name]
    cases = db["cases"]
    intakes = db["intakes"]

    total = await cases.count_documents({})
    with_intake = await cases.count_documents({"intake_id": {"$nin": [None, ""]}})

    print(f"database:           {settings.db_name}")
    print(f"cases:              {total}")
    print(f"cases from intake:  {with_intake}")

    groups = await cases.aggregate([
        {"$match": {"intake_id": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$intake_id", "n": {"$sum": 1},
                    "case_ids": {"$push": "$_id"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$sort": {"n": -1}},
    ]).to_list(length=None)

    if not groups:
        print("\nNo duplicates. The partial unique index can be created safely.")
        await _report_index(cases)
        return 0

    dupes = sum(g["n"] - 1 for g in groups)
    print(f"\n{len(groups)} intake(s) produced more than one case "
          f"({dupes} extra case(s)).\n")

    for g in groups:
        intake = await intakes.find_one({"_id": g["_id"]},
                                        {"case_id": 1, "client_id": 1, "created_at": 1})
        keeper = (intake or {}).get("case_id")
        print(f"intake {g['_id']}  ({g['n']} cases)")
        print(f"  intake points at: {keeper or '(nothing)'}")
        for case_id in g["case_ids"]:
            case = await cases.find_one({"_id": case_id})
            # Everything that would be LOST by deleting this row. A stray with
            # attachments is not a stray any more; it is a case someone worked on.
            attachments = {
                "documents":    await db["documents"].count_documents({"case_id": case_id}),
                "appointments": await db["appointments"].count_documents({"case_id": case_id}),
                "engagements":  await db["engagements"].count_documents({"case_id": case_id}),
                "payments":     await db["payments"].count_documents({"case_id": case_id}),
                "milestones":   len(case.get("milestones") or []),
                "hearings":     len(case.get("hearing_dates") or []),
                "messages":     len(case.get("messages") or []),
            }
            busy = {k: v for k, v in attachments.items() if v}
            mark = "KEEPER" if case_id == keeper else "stray "
            print(f"  [{mark}] {case_id}  {case.get('case_number', '?')}  "
                  f"status={case.get('status')}  lawyer={case.get('lawyer_id') or '-'}")
            print(f"           created={case.get('created_at')}  "
                  f"attachments={busy or 'none'}")
        print()

    print("NOT deleting anything. For each group the intake names the keeper, but a")
    print("stray carrying attachments is a case someone worked on — that is a human")
    print("decision. The unique index cannot be created until each group is resolved.")
    await _report_index(cases)
    return 1


async def _report_index(cases) -> None:
    info = await cases.index_information()
    name = "uniq_case_per_intake"
    print(f"\nindex {name}: {'present' if name in info else 'NOT present'}")
    if name in info:
        print(f"  {info[name]}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
