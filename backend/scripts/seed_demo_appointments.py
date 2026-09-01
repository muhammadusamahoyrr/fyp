"""
Demo appointments — curated seed data so the appointment screens are not blank.

WHY THIS EXISTS
---------------
The appointments collection was empty (0 rows against 52 cases), so the client
Overview tile, the tracking Appointments page and the lawyer calendar all
rendered nothing during a demo. This fills them with a realistic spread —
past and future, across statuses and modes — against the demo lawyer roster.

Like seed_demo_lawyers.py, every row carries `is_demo_seed: True`, so demo data
is one query away from being listed or removed and can never be mistaken for a
real booking or for a leftover test fixture:

    demo seed    is_demo_seed: True — curated, intentional
    test fixture @example.com / null email — deleted by purge_test_fixtures.py
    real booking neither marker

BEFORE ANY PUBLIC DEPLOYMENT remove these: `--remove`. A fictional consultation
on a real lawyer's calendar is worse than an empty one.

CONSTRAINTS THIS RESPECTS
-------------------------
`uniq_pending_slot` is a unique partial index on (lawyer_id, scheduled_at) for
PENDING rows, so two pending appointments cannot share a lawyer and start time.
Slots here are generated per lawyer at distinct hours, and the script re-checks
before inserting rather than relying on the exception.

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py            # dry run
    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py --apply
    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py --list
    ./venv/Scripts/python.exe scripts/seed_demo_appointments.py --remove
    ... --client someone@example.com     # default: the non-fixture client with
                                         # the most cases
"""
import argparse
import asyncio
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

DEMO_MARKER = "is_demo_seed"
FIXTURE_EMAIL = re.compile(r"@example\.(com|org|net)$", re.I)

# (days from now, hour UTC, duration, status, mode, note)
# Past rows are completed, the near future is confirmed, the far future pending
# — so the calendar shows history, a settled booking and an open request.
PLAN = [
    (-21, 10, 45, "completed", "in_person",
     "Initial consultation — reviewed the FIR and advised on bail options."),
    (-14,  14, 30, "completed", "video",
     "Follow-up on documents required for the next hearing."),
    (-6,   11, 60, "completed", "in_person",
     "Went through the draft petition line by line."),
    (-2,   15, 30, "cancelled", "phone",
     "Client asked to move this; rescheduled to the following week."),
    (2,     9, 45, "confirmed", "video",
     "Pre-hearing briefing. Bring the original agreement."),
    (5,    16, 30, "confirmed", "phone",
     "Quick call to confirm the witness list."),
    (9,    11, 60, "pending", "in_person",
     "Requested: full case review ahead of the trial date."),
    (16,   13, 45, "pending", "video",
     "Requested: discuss settlement options with the other party."),
]


async def _pick_client(db, email: str | None) -> dict:
    if email:
        u = await db["users"].find_one({"email": email, "role": "client"})
        if not u:
            raise SystemExit(f"no client found with email {email!r}")
        return u
    # Otherwise the non-fixture client with the most cases — the account a demo
    # is most likely to be driven from.
    best, best_n = None, -1
    async for u in db["users"].find({"role": "client", "is_active": True}):
        e = u.get("email") or ""
        if not e or FIXTURE_EMAIL.search(e) or e.startswith("closed+"):
            continue
        n = await db["cases"].count_documents({"client_id": u["_id"]})
        if n > best_n:
            best, best_n = u, n
    if not best:
        raise SystemExit("no non-fixture client account to attach appointments to")
    return best


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="insert the appointments")
    ap.add_argument("--list", action="store_true", help="list demo appointments")
    ap.add_argument("--remove", action="store_true", help="delete every demo appointment")
    ap.add_argument("--client", help="client email to attach them to")
    args = ap.parse_args()

    client = AsyncIOMotorClient(os.getenv("MONGODB_URL"), serverSelectionTimeoutMS=15000)
    db = client[os.getenv("DB_NAME", "attorney_ai")]
    appts = db["appointments"]

    if args.list:
        n = 0
        async for a in appts.find({DEMO_MARKER: True}).sort("scheduled_at", 1):
            print(f"  {str(a['scheduled_at'])[:16]}  {a['status']:10} {a['mode']:10} "
                  f"lawyer={a['lawyer_id'][:12]} case={str(a.get('case_id'))[:12]}")
            n += 1
        print(f"\n{n} demo appointment(s)")
        client.close()
        return 0

    if args.remove:
        doomed = await appts.count_documents({DEMO_MARKER: True})
        print(f"{doomed} demo appointment(s) to delete")
        if doomed:
            res = await appts.delete_many({DEMO_MARKER: True})
            print(f"deleted {res.deleted_count}")
        client.close()
        return 0

    who = await _pick_client(db, args.client)
    print(f"client : {who.get('email')}  ({who['_id']})")

    lawyers = [u async for u in db["users"].find(
        {"role": "lawyer", DEMO_MARKER: True, "is_active": True}
    ).sort("province", 1)]
    if not lawyers:
        raise SystemExit("no demo lawyers found — run scripts/seed_demo_lawyers.py first")
    print(f"lawyers: {len(lawyers)} demo lawyer(s) available")

    cases = [c async for c in db["cases"].find({"client_id": who["_id"]}).limit(len(PLAN))]
    print(f"cases  : {len(cases)} belonging to this client\n")

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    planned, skipped = [], 0
    for i, (days, hour, mins, status, mode, note) in enumerate(PLAN):
        lawyer = lawyers[i % len(lawyers)]
        when = (now + timedelta(days=days)).replace(hour=hour)
        # Respect uniq_pending_slot rather than relying on the write to fail.
        clash = await appts.find_one({
            "lawyer_id": lawyer["_id"], "scheduled_at": when,
            "status": {"$in": ["pending", "confirmed"]},
        })
        if clash:
            skipped += 1
            print(f"  skip     {when:%Y-%m-%d %H:%M}  {lawyer['email']:34} slot already taken")
            continue
        planned.append({
            "_id": secrets.token_urlsafe(16),
            "client_id": who["_id"],
            "lawyer_id": lawyer["_id"],
            "case_id": cases[i]["_id"] if i < len(cases) else None,
            "scheduled_at": when,
            "end_at": when + timedelta(minutes=mins),
            "duration_minutes": mins,
            "status": status,
            "mode": mode,
            "notes": note,
            "lawyer_notes": None,
            "cancel_reason": "Client requested a different time." if status == "cancelled" else None,
            "cancelled_by": who["_id"] if status == "cancelled" else None,
            "meeting_link": "https://meet.example.invalid/demo" if mode == "video" else None,
            DEMO_MARKER: True,
            "created_at": now - timedelta(days=abs(days) + 2),
            "updated_at": now,
        })
        print(f"  {'would add' if not args.apply else 'add      '} "
              f"{when:%Y-%m-%d %H:%M}  {status:10} {mode:10} {lawyer['email']}")

    if not args.apply:
        print(f"\n{len(planned)} would be inserted, {skipped} skipped")
        print("DRY RUN - nothing written. Re-run with --apply.")
        client.close()
        return 0

    if planned:
        await appts.insert_many(planned)
    total = await appts.count_documents({})
    print(f"\ninserted {len(planned)}, skipped {skipped}")
    print(f"appointments in the database now: {total}")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
