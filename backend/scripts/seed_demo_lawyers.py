"""
Demo lawyer roster — intentional, curated seed data for demonstrating matching.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
These are FICTIONAL lawyers created so the matching feature can be demonstrated
before the platform has real signups. They are not real advocates, the bar
numbers are not real enrolment numbers, and nobody should ever be able to
engage one. Every account written here carries `is_demo_seed: True` so it can
be listed, audited or removed in one query, and so it is never confused with
either a real signup or a leftover test fixture.

    demo seed   is_demo_seed: True,  @attorney.ai,  curated, KYC-verified
    test fixture @example.com / null email — deleted by purge_test_fixtures.py
    real signup  neither marker

BEFORE ANY PUBLIC DEPLOYMENT these accounts must be removed. A real client
reaching a fictional advocate is a worse failure than an empty search result.
`--remove` does that.

WHY MORE THAN THE ORIGINAL 8
----------------------------
The original seed personas covered 12 of the 20 province x case-type
combinations. Nothing broke — every combination still returned a match,
because the vector query filters on province only, so a lawyer from the same
province or from `federal` was always reachable. But three combinations
recommended a lawyer with no relevant expertise at all:

    kpk + criminal          -> a federal CONSTITUTIONAL lawyer, no spec match
    balochistan + criminal  -> the same lawyer
    sindh + family          -> a criminal/constitutional lawyer

and kpk/balochistan returned only 2 candidates against a top_n of 5, so the
ranked list looked threadbare. This roster fills all 8 empty cells and gives
Punjab — where 43 of 59 real cases sit — a second specialist per case type.

The bios are the main signal the embedding model has to work with, so each one
names the instruments that lawyer actually works under (PPC 1860, CrPC 1898,
the Muslim Family Laws Ordinance 1961, Article 199 writs, and so on). Generic
bios would collapse the semantic scores toward each other and make the ranking
look arbitrary in a demo.

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/seed_demo_lawyers.py            # dry run
    ./venv/Scripts/python.exe scripts/seed_demo_lawyers.py --apply    # insert
    ./venv/Scripts/python.exe scripts/seed_demo_lawyers.py --list     # show roster
    ./venv/Scripts/python.exe scripts/seed_demo_lawyers.py --remove   # delete all demo seeds

Idempotent: an email that already exists is skipped, never duplicated or
overwritten. After inserting, run scripts/backfill_lawyer_embeddings.py so the
new profiles are searchable.

Shared password for every demo account: Lawyer@123
"""
import argparse
import asyncio
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

DEMO_PASSWORD = "Lawyer@123"
DEMO_MARKER = "is_demo_seed"

# province -> the bar council that actually enrols there, so the numbers at
# least follow the right shape for the province they sit in.
_COUNCIL = {
    "punjab": "PBC", "sindh": "SBC", "kpk": "KPBC",
    "balochistan": "BBC", "federal": "IBC",
}

# Fills every province x case-type cell the original 8 personas left empty,
# and doubles up Punjab, which carries most of the real case volume.
ROSTER = [
    # ── Punjab: a second specialist per case type ────────────────────────────
    dict(full_name="Bilal Ahmed Sheikh", province="punjab", specs=["criminal"],
         exp=14, rating=4.7, reviews=52, avail=True, year=2011, seq=4417,
         phone="+92-300-2220101",
         bio="Criminal defence advocate practising before the Lahore High Court and "
             "sessions courts across central Punjab. Fourteen years handling FIR "
             "quashment, pre-arrest and post-arrest bail under the Criminal Procedure "
             "Code 1898, and trials for offences under the Pakistan Penal Code 1860, "
             "including theft, hurt and fraud matters."),
    dict(full_name="Ayesha Kamal", province="punjab", specs=["civil", "family"],
         exp=9, rating=4.5, reviews=31, avail=True, year=2016, seq=7734,
         phone="+92-300-2220102",
         bio="Civil and family practitioner in Lahore. Advises on ejectment and "
             "rent matters under the Punjab Rented Premises Act 2009, suits for "
             "specific performance and declaration under the Specific Relief Act "
             "1877, and parallel maintenance and custody proceedings in the family "
             "courts."),
    dict(full_name="Usman Javed Rana", province="punjab", specs=["family"],
         exp=6, rating=4.2, reviews=19, avail=False, year=2019, seq=9120,
         phone="+92-300-2220103",
         bio="Family law practitioner in Rawalpindi and Islamabad. Khula and "
             "dissolution suits, custody and guardianship applications, dower and "
             "maintenance recovery under the Muslim Family Laws Ordinance 1961 and "
             "the Guardians and Wards Act 1890."),

    # ── Sindh: the missing family practice ───────────────────────────────────
    dict(full_name="Rabia Kazmi", province="sindh", specs=["family"],
         exp=12, rating=4.6, reviews=44, avail=True, year=2013, seq=2290,
         phone="+92-301-3330201",
         bio="Family lawyer practising in the Karachi family courts for twelve "
             "years. Khula, custody and visitation, dower recovery and maintenance "
             "under the Muslim Family Laws Ordinance 1961, and inheritance "
             "distribution disputes among heirs."),
    dict(full_name="Farhan Abbas Shah", province="sindh", specs=["civil", "criminal"],
         exp=17, rating=4.4, reviews=63, avail=False, year=2008, seq=1176,
         phone="+92-301-3330202",
         bio="Senior advocate of the High Court of Sindh with a mixed civil and "
             "criminal practice. Property partition and possession suits, "
             "landlord-tenant disputes, and defence in cheque dishonour "
             "prosecutions under section 489-F of the Pakistan Penal Code 1860."),

    # ── KPK: criminal and constitutional were both empty ─────────────────────
    dict(full_name="Zubair Khan Marwat", province="kpk", specs=["criminal"],
         exp=11, rating=4.3, reviews=28, avail=True, year=2014, seq=3308,
         phone="+92-302-4440301",
         bio="Criminal advocate before the Peshawar High Court. Bail petitions, "
             "FIR registration applications under section 22-A of the Criminal "
             "Procedure Code 1898, and defence at trial in narcotics and offences "
             "against the person under the Pakistan Penal Code 1860."),
    dict(full_name="Nasreen Bibi Khattak", province="kpk", specs=["constitutional", "family"],
         exp=8, rating=4.5, reviews=22, avail=True, year=2017, seq=5561,
         phone="+92-302-4440302",
         bio="Constitutional and family practitioner in Peshawar. Writ petitions "
             "under Article 199 of the Constitution against administrative action "
             "and service matters, alongside a family practice covering custody and "
             "maintenance in the district family courts."),

    # ── Balochistan: criminal and constitutional were both empty ─────────────
    dict(full_name="Naveed Ahmed Shahwani", province="balochistan", specs=["criminal"],
         exp=16, rating=4.1, reviews=25, avail=True, year=2009, seq=884,
         phone="+92-303-5550401",
         bio="Criminal defence advocate practising before the Balochistan High "
             "Court in Quetta. Sixteen years of bail applications, quashment "
             "petitions and criminal trials under the Pakistan Penal Code 1860 and "
             "the Criminal Procedure Code 1898."),
    dict(full_name="Shazia Panezai", province="balochistan", specs=["constitutional", "civil"],
         exp=10, rating=4.4, reviews=18, avail=False, year=2015, seq=1203,
         phone="+92-303-5550402",
         bio="Advocate in Quetta handling constitutional and civil work. Article "
             "199 writ petitions in service and licensing matters, judicial review "
             "of departmental action, and civil suits for declaration and permanent "
             "injunction."),

    # ── Federal: only constitutional existed ─────────────────────────────────
    dict(full_name="Kamran Aziz Malik", province="federal", specs=["criminal"],
         exp=19, rating=4.8, reviews=71, avail=True, year=2006, seq=559,
         phone="+92-304-6660501",
         bio="Advocate of the Supreme Court with a criminal appellate practice in "
             "Islamabad. Criminal appeals and revisions, bail before the Islamabad "
             "High Court, and prosecution of anti-corruption references. Nineteen "
             "years under the Pakistan Penal Code 1860 and the Criminal Procedure "
             "Code 1898."),
    dict(full_name="Hina Tariq", province="federal", specs=["civil"],
         exp=13, rating=4.6, reviews=39, avail=True, year=2012, seq=2841,
         phone="+92-304-6660502",
         bio="Civil litigator in Islamabad. Contract enforcement and damages "
             "under the Contract Act 1872, suits for specific performance of "
             "agreements to sell immovable property, and recovery suits before the "
             "civil courts of the Islamabad Capital Territory."),
    dict(full_name="Junaid Iqbal Qureshi", province="federal", specs=["family", "civil"],
         exp=7, rating=4.0, reviews=15, avail=True, year=2018, seq=6690,
         phone="+92-304-6660503",
         bio="Family and civil practitioner in the Islamabad Capital Territory. "
             "Khula, custody and maintenance under the Muslim Family Laws Ordinance "
             "1961, guardianship certificates, and civil suits over residential "
             "property in the capital."),
]


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def _bar_number(entry: dict) -> str:
    return f"{_COUNCIL[entry['province']]}/{entry['year']}/{entry['seq']:04d}"


def _email(full_name: str) -> str:
    parts = full_name.lower().replace(".", "").split()
    return f"{parts[0]}.{parts[-1]}@attorney.ai"


def _doc(entry: dict, pw_hash: str, now: datetime) -> dict:
    return {
        "_id": secrets.token_urlsafe(16),
        "role": "lawyer",
        "email": _email(entry["full_name"]),
        "password_hash": pw_hash,
        "full_name": entry["full_name"],
        "phone": entry["phone"],
        "province": entry["province"],
        "avatar_url": None,
        "is_active": True,
        # The marker. One query finds every demo account, and no purge or audit
        # has to guess from the email what this row is.
        DEMO_MARKER: True,
        "lawyer_profile": {
            "bar_number": _bar_number(entry),
            "specializations": entry["specs"],
            "kyc_verified": True,
            # Explicit, unlike the original 8 which predate the state machine
            # and carry a null status.
            "kyc_status": "approved",
            "kyc_rejection_reason": None,
            "rating": entry["rating"],
            "total_reviews": entry["reviews"],
            "availability": entry["avail"],
            "bio": entry["bio"],
            "experience_years": entry["exp"],
            "specialization_embedding": None,
        },
        "created_at": now,
        "updated_at": now,
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="insert the roster")
    ap.add_argument("--list", action="store_true", help="list demo seeds in the database")
    ap.add_argument("--remove", action="store_true",
                    help="delete every account marked is_demo_seed")
    args = ap.parse_args()

    client = AsyncIOMotorClient(os.getenv("MONGODB_URL"), serverSelectionTimeoutMS=15000)
    db = client[os.getenv("DB_NAME", "attorney_ai")]
    col = db["users"]

    if args.list:
        n = 0
        async for u in col.find({DEMO_MARKER: True}).sort("province", 1):
            lp = u.get("lawyer_profile") or {}
            print(f"  {u['_id']:24} {u['email']:34} {str(u.get('province')):13} "
                  f"{','.join(lp.get('specializations') or [])}")
            n += 1
        print(f"\n{n} demo seed account(s)")
        client.close()
        return 0

    if args.remove:
        doomed = [u async for u in col.find({DEMO_MARKER: True})]
        print(f"{len(doomed)} demo seed account(s) to delete")
        for u in doomed:
            print(f"  {u['email']}")
        if not doomed:
            client.close()
            return 0
        res = await col.delete_many({DEMO_MARKER: True})
        print(f"deleted {res.deleted_count}")
        print("NEXT: run scripts/purge_orphan_lawyer_vectors.py to drop their vectors.")
        client.close()
        return 0

    print(f"roster: {len(ROSTER)} demo lawyers\n")
    now = datetime.now(timezone.utc)
    pw_hash = _hash(DEMO_PASSWORD) if args.apply else "(dry run)"

    inserted = skipped = 0
    for entry in ROSTER:
        email = _email(entry["full_name"])
        existing = await col.find_one({"email": email})
        if existing:
            print(f"  skip     {email:34} already exists")
            skipped += 1
            continue
        if not args.apply:
            print(f"  would insert {email:30} {entry['province']:13} "
                  f"{','.join(entry['specs']):24} bar={_bar_number(entry)}")
            inserted += 1
            continue
        await col.insert_one(_doc(entry, pw_hash, now))
        print(f"  inserted {email:34} {entry['province']:13} "
              f"{','.join(entry['specs']):24} bar={_bar_number(entry)}")
        inserted += 1

    if not args.apply:
        print(f"\n{inserted} would be inserted, {skipped} already present")
        print("DRY RUN - nothing written. Re-run with --apply.")
        client.close()
        return 0

    print(f"\ninserted {inserted}, skipped {skipped}")
    total = await col.count_documents(
        {"role": "lawyer", "lawyer_profile.kyc_verified": True, "is_active": True}
    )
    print(f"verified + active lawyers now: {total}")
    print(f"login password for every demo account: {DEMO_PASSWORD}")
    print("NEXT: run scripts/backfill_lawyer_embeddings.py --apply to index them.")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
