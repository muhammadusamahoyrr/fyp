"""
Seed script — inserts 8 KYC-verified lawyer accounts + 1 admin into MongoDB.
Run once (idempotent: skips existing emails):

    cd backend
    python seed_lawyers.py

Requirements: motor, bcrypt, python-dotenv  (already in requirements.txt)
"""

import asyncio
import secrets
from datetime import datetime
from pathlib import Path

import bcrypt
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env")

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME     = os.getenv("DB_NAME", "attorney_ai")

# ─── Lawyer seed data ────────────────────────────────────────────────────────

def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


NOW = datetime.utcnow()

LAWYERS = [
    {
        "full_name":    "Ahmad Raza Khan",
        "email":        "ahmad.raza@attorney.ai",
        "phone":        "+92-300-1111001",
        "province":     "punjab",
        "bio":          "Senior criminal defense lawyer with 12 years in Lahore High Court. "
                        "Handled 200+ FIR, bail, and trial matters under PPC 1860.",
        "specializations": ["criminal"],
        "experience_years": 12,
        "rating":       4.8,
        "total_reviews": 47,
        "bar_number":   "LHC-2012-3041",
        "availability": True,
    },
    {
        "full_name":    "Fatima Malik",
        "email":        "fatima.malik@attorney.ai",
        "phone":        "+92-300-1111002",
        "province":     "punjab",
        "bio":          "Family law specialist with 8 years. Expert in khula, custody, "
                        "and inheritance matters under Muslim Family Laws Ordinance 1961.",
        "specializations": ["family"],
        "experience_years": 8,
        "rating":       4.6,
        "total_reviews": 34,
        "bar_number":   "LHC-2016-7821",
        "availability": True,
    },
    {
        "full_name":    "Imran Hussain Baloch",
        "email":        "imran.hussain@attorney.ai",
        "phone":        "+92-300-1111003",
        "province":     "sindh",
        "bio":          "15 years criminal litigation in Sindh High Court. Specialist in "
                        "organised crime, anti-terrorism, and PECA 2016 digital offences.",
        "specializations": ["criminal", "constitutional"],
        "experience_years": 15,
        "rating":       4.5,
        "total_reviews": 61,
        "bar_number":   "SHC-2009-1152",
        "availability": True,
    },
    {
        "full_name":    "Sara Qureshi",
        "email":        "sara.qureshi@attorney.ai",
        "phone":        "+92-300-1111004",
        "province":     "sindh",
        "bio":          "Civil and property law advocate with 10 years. Specialises in CPC "
                        "1908 suits, rent disputes, and commercial contract enforcement.",
        "specializations": ["civil"],
        "experience_years": 10,
        "rating":       4.3,
        "total_reviews": 28,
        "bar_number":   "SHC-2014-4430",
        "availability": False,
    },
    {
        "full_name":    "Tariq Mehmood",
        "email":        "tariq.mehmood@attorney.ai",
        "phone":        "+92-300-1111005",
        "province":     "kpk",
        "bio":          "Civil litigation and land dispute lawyer based in Peshawar. "
                        "6 years handling agricultural and urban property cases in KPK.",
        "specializations": ["civil", "family"],
        "experience_years": 6,
        "rating":       4.1,
        "total_reviews": 19,
        "bar_number":   "PHC-2018-2290",
        "availability": True,
    },
    {
        "full_name":    "Zainab Chaudhry",
        "email":        "zainab.chaudhry@attorney.ai",
        "phone":        "+92-300-1111006",
        "province":     "federal",
        "bio":          "Constitutional and human rights lawyer at Supreme Court of Pakistan. "
                        "9 years handling fundamental rights, writ petitions, and PIL.",
        "specializations": ["constitutional"],
        "experience_years": 9,
        "rating":       4.7,
        "total_reviews": 52,
        "bar_number":   "SCP-2015-0881",
        "availability": True,
    },
    {
        "full_name":    "Hassan Nawaz Mengal",
        "email":        "hassan.nawaz@attorney.ai",
        "phone":        "+92-300-1111007",
        "province":     "balochistan",
        "bio":          "Family and tribal law practitioner in Balochistan High Court. "
                        "7 years resolving divorce, dower, and jirga-related matters.",
        "specializations": ["family", "civil"],
        "experience_years": 7,
        "rating":       3.9,
        "total_reviews": 14,
        "bar_number":   "BHC-2017-5503",
        "availability": True,
    },
    {
        "full_name":    "Nadia Farooq",
        "email":        "nadia.farooq@attorney.ai",
        "phone":        "+92-300-1111008",
        "province":     "punjab",
        "bio":          "Constitutional litigation and administrative law specialist with 11 years. "
                        "Handled judicial review, service matters, and election law cases.",
        "specializations": ["constitutional", "civil"],
        "experience_years": 11,
        "rating":       4.4,
        "total_reviews": 39,
        "bar_number":   "LHC-2013-6614",
        "availability": False,
    },
]

ADMIN = {
    "full_name": "Platform Admin",
    "email":     "admin@attorney.ai",
    "phone":     "+92-300-0000001",
    "province":  "federal",
}

# ─── Seed logic ───────────────────────────────────────────────────────────────

async def seed():
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(MONGODB_URL)
    db     = client[DB_NAME]
    col    = db["users"]

    inserted = 0
    skipped  = 0

    # ── Lawyers ──────────────────────────────────────────────────────────────
    pw_hash = _hash("Lawyer@123")

    for l in LAWYERS:
        existing = await col.find_one({"email": l["email"]})
        if existing:
            print(f"  skip  {l['email']} (already exists)")
            skipped += 1
            continue

        doc = {
            "_id":           secrets.token_urlsafe(16),
            "role":          "lawyer",
            "email":         l["email"],
            "password_hash": pw_hash,
            "full_name":     l["full_name"],
            "phone":         l["phone"],
            "province":      l["province"],
            "is_active":     True,
            "lawyer_profile": {
                "bar_number":              l["bar_number"],
                "specializations":         l["specializations"],
                "kyc_verified":            True,
                "kyc_rejection_reason":    None,
                "rating":                  l["rating"],
                "total_reviews":           l["total_reviews"],
                "availability":            l["availability"],
                "bio":                     l["bio"],
                "experience_years":        l["experience_years"],
                "specialization_embedding": None,
            },
            "created_at": NOW,
            "updated_at": NOW,
        }
        await col.insert_one(doc)
        print(f"  [OK] inserted  {l['full_name']} ({l['province']}, {l['specializations']})")
        inserted += 1

    # ── Admin ─────────────────────────────────────────────────────────────────
    existing_admin = await col.find_one({"email": ADMIN["email"]})
    if existing_admin:
        print(f"  skip  {ADMIN['email']} (already exists)")
        skipped += 1
    else:
        await col.insert_one({
            "_id":           secrets.token_urlsafe(16),
            "role":          "admin",
            "email":         ADMIN["email"],
            "password_hash": _hash("Admin@1234"),
            "full_name":     ADMIN["full_name"],
            "phone":         ADMIN["phone"],
            "province":      ADMIN["province"],
            "is_active":     True,
            "lawyer_profile": None,
            "created_at": NOW,
            "updated_at": NOW,
        })
        print(f"  [OK] inserted  admin ({ADMIN['email']})")
        inserted += 1

    client.close()
    print(f"\nDone — {inserted} inserted, {skipped} skipped.")
    print("\nTest credentials:")
    print("  Lawyers : any lawyer email above  /  Lawyer@123")
    print("  Admin   : admin@attorney.ai        /  Admin@1234")


if __name__ == "__main__":
    asyncio.run(seed())
