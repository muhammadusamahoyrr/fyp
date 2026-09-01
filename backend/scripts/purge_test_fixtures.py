"""
Delete leftover test-fixture lawyer accounts from MongoDB, with cascade.

WHY THIS EXISTS
---------------
Smoke tests, E2E runs and QA audits registered lawyer accounts directly against
the production database and never cleaned up. As of 2026-09-01 that left 24
synthetic lawyer accounts, 17 of them KYC-verified — which meant `find_lawyers`
returned them as real, rankable matches to real clients. Every one has an
`@example.com` (or null) email, a generator name ("Test Lawyer", "Audit
lawyer"), a machine-prefixed bar number (BAR-TEST-*, AUD-*, SHIP-*) and no
phone. None is a real lawyer with incomplete data.

Deleting the user document alone would leave dependent rows pointing at a
nonexistent lawyer. Dangling references of exactly that kind are what broke
lawyer matching in the first place (two deleted smoke-test lawyers survived in
the ChromaDB vector store and suppressed the entire real candidate pool — see
`purge_orphan_lawyer_vectors.py`), so this cascades.

SAFETY
------
- Dry run by default. `--apply` is required to write.
- Every document that will be deleted is written to a JSON backup FIRST.
- A dependent row is only deleted if its *other* party is also a fixture. If a
  real client is attached to a fixture lawyer's case, the row is kept and
  reported rather than silently destroyed.
- Only `role: "lawyer"` accounts are considered. Fixture *client* accounts are
  deliberately out of scope.

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/purge_test_fixtures.py           # dry run
    ./venv/Scripts/python.exe scripts/purge_test_fixtures.py --apply   # delete
"""
import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")

# A fixture account is one that could only have been created by an automated
# test: a reserved-for-documentation email domain (RFC 2606), no email at all,
# or an id stamped by a seeding helper.
FIXTURE_EMAIL = re.compile(r"@example\.(com|org|net)$", re.I)
FIXTURE_ID    = re.compile(r"^(e2e[_-]|test[_-])", re.I)

# collection -> (fields naming the lawyer, fields naming the counterparty)
# A row is deleted only when every counterparty it names is also a fixture.
DEPENDENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "cases":         (("lawyer_id",),                 ("client_id",)),
    "engagements":   (("lawyer_id",),                 ("client_id",)),
    "appointments":  (("lawyer_id", "cancelled_by"),  ("client_id",)),
    "documents":     (("submitted_to",),              ("client_id",)),
    "notifications": (("user_id",),                   ()),
    "lawyer_reviews": (("lawyer_id",),                ("client_id",)),
}


def is_fixture(user: dict) -> bool:
    # Demo seed accounts (scripts/seed_demo_lawyers.py) are curated, verified
    # and deliberately present. They are not fixtures and must survive this
    # script even if a future email convention happens to match the rules
    # below. Remove them with `seed_demo_lawyers.py --remove` instead.
    if user.get("is_demo_seed"):
        return False
    email = user.get("email") or ""
    return (
        not email
        or bool(FIXTURE_EMAIL.search(email))
        or bool(FIXTURE_ID.match(str(user.get("_id", ""))))
    )


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; without it the script only reports")
    args = ap.parse_args()

    client = AsyncIOMotorClient(os.getenv("MONGODB_URL"), serverSelectionTimeoutMS=10000)
    db = client[os.getenv("DB_NAME", "attorney_ai")]
    existing = set(await db.list_collection_names())

    # ── 1. Identify fixture lawyers ───────────────────────────────────────────
    doomed: list[dict] = []
    kept: list[dict] = []
    async for u in db["users"].find({"role": "lawyer"}):
        (doomed if is_fixture(u) else kept).append(u)

    print(f"lawyer accounts: {len(doomed) + len(kept)}  "
          f"fixtures: {len(doomed)}  real (kept): {len(kept)}")
    if not doomed:
        print("nothing to purge")
        client.close()
        return 0

    doomed_ids = {u["_id"] for u in doomed}
    verified = sum(1 for u in doomed if (u.get("lawyer_profile") or {}).get("kyc_verified"))
    print(f"  of the fixtures, {verified} are KYC-verified "
          f"(i.e. currently reachable by lawyer matching)\n")

    print("-- fixture lawyer accounts to delete --")
    for u in sorted(doomed, key=lambda x: str(x.get("created_at") or "")):
        lp = u.get("lawyer_profile") or {}
        created = u.get("created_at")
        created_s = created.strftime("%Y-%m-%d %H:%M") if isinstance(created, datetime) else "(none)"
        print(f"  {created_s:17} {str(u['_id']):24} {str(u.get('email')):34} "
              f"kyc={str(lp.get('kyc_verified')):5} {str(u.get('full_name'))[:22]}")

    # ── 2. Plan the cascade ───────────────────────────────────────────────────
    async def counterparty_is_real(row: dict, fields: tuple[str, ...]) -> str | None:
        """Return the email/id of a real (non-fixture) counterparty, else None."""
        for f in fields:
            other = row.get(f)
            if not other or other in doomed_ids:
                continue
            other_user = await db["users"].find_one({"_id": other})
            if other_user and not is_fixture(other_user):
                return other_user.get("email") or str(other)
        return None

    to_delete: dict[str, list[dict]] = {}
    protected: list[tuple[str, str, str]] = []

    for coll, (lawyer_fields, other_fields) in DEPENDENTS.items():
        if coll not in existing:
            continue
        query = {"$or": [{f: {"$in": list(doomed_ids)}} for f in lawyer_fields]}
        async for row in db[coll].find(query):
            real = await counterparty_is_real(row, other_fields)
            if real:
                protected.append((coll, str(row["_id"]), real))
            else:
                to_delete.setdefault(coll, []).append(row)

    print("\n-- cascade --")
    for coll in DEPENDENTS:
        n = len(to_delete.get(coll, []))
        if n:
            print(f"  {coll:16} {n} row(s)")
    if not any(to_delete.values()):
        print("  (no dependent rows)")

    if protected:
        print("\n-- KEPT: dependent rows attached to a REAL user --")
        for coll, rid, who in protected:
            print(f"  {coll}/{rid} -> {who}")
        print("  These are left in place; they now reference a deleted lawyer.")

    total_rows = len(doomed) + sum(len(v) for v in to_delete.values())
    print(f"\ntotal documents in scope: {total_rows}")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply to delete.")
        client.close()
        return 0

    # ── 3. Backup, then delete ────────────────────────────────────────────────
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = BACKEND / "data" / "purge_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"fixture_purge_{stamp}.json"

    payload = {
        "purged_at": stamp,
        "db": os.getenv("DB_NAME", "attorney_ai"),
        "users": doomed,
        "dependents": {c: rows for c, rows in to_delete.items()},
        "kept_because_real_counterparty": [
            {"collection": c, "_id": i, "counterparty": w} for c, i, w in protected
        ],
    }
    backup_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    print(f"\nbackup written: {backup_path}")

    for coll, rows in to_delete.items():
        if not rows:
            continue
        res = await db[coll].delete_many({"_id": {"$in": [r["_id"] for r in rows]}})
        print(f"  deleted {res.deleted_count:3} from {coll}")

    res = await db["users"].delete_many({"_id": {"$in": list(doomed_ids)}})
    print(f"  deleted {res.deleted_count:3} from users")

    remaining = await db["users"].count_documents(
        {"role": "lawyer", "lawyer_profile.kyc_verified": True, "is_active": True}
    )
    print(f"\nverified+active lawyers remaining: {remaining}")
    print("NEXT: run scripts/purge_orphan_lawyer_vectors.py to drop their vectors.")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
