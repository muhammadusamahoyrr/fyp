"""
End-to-end test for lawyer matching:
  1. Seed test admin, test lawyer, test client, test case into MongoDB
  2. POST /admin/lawyers/embed-all  (admin token)
  3. GET  /lawyers/match/{case_id} (client token)

Run with the server already running on :8000:
    python test_lawyer_matching.py
"""
import asyncio
import sys
import uuid
import json

sys.path.insert(0, ".")

# ── bootstrap config + db ──────────────────────────────────────────────────────
from app.core.config import settings
from app.core.security import hash_password, create_access_token
from app.db.mongodb import connect_db, get_database
from app.db.chroma import connect_chroma

BASE = "http://localhost:8000/api/v1"

# Fixed IDs so re-runs upsert instead of duplicate-insert
ADMIN_ID  = "test-admin-001"
LAWYER_ID = "test-lawyer-001"
CLIENT_ID = "test-client-001"
CASE_ID   = "test-case-001"


async def _upsert_user(db, doc: dict):
    """Delete any existing doc sharing the same _id or email, then insert fresh."""
    email = doc["email"]
    _id   = doc["_id"]
    await db["users"].delete_many({"$or": [{"_id": _id}, {"email": email}]})
    await db["users"].insert_one(doc)


async def seed_db():
    db = get_database()

    await _upsert_user(db, {
        "_id":           ADMIN_ID,
        "email":         "testadmin@attorney.ai",
        "password_hash": hash_password("Admin@1234"),
        "full_name":     "Test Admin",
        "role":          "admin",
        "is_active":     True,
    })
    print(f"[seed] admin  : {ADMIN_ID}")

    await _upsert_user(db, {
        "_id":       LAWYER_ID,
        "email":     "testlawyer@attorney.ai",
        "password_hash": hash_password("Lawyer@1234"),
        "full_name": "Adv. Kamran Ali",
        "role":      "lawyer",
        "province":  "punjab",
        "is_active": True,
        "lawyer_profile": {
            "specializations":  ["criminal", "family"],
            "experience_years": 12,
            "rating":           4.3,
            "total_reviews":    18,
            "availability":     True,
            "kyc_verified":     True,
            "bio": (
                "Senior criminal defense attorney with 12 years of experience in "
                "Lahore High Court. Handled 200+ FIR cases, bail petitions, and "
                "family disputes including khula, custody, and inheritance matters "
                "under Pakistani law."
            ),
        },
    })
    print(f"[seed] lawyer : {LAWYER_ID}")

    await _upsert_user(db, {
        "_id":           CLIENT_ID,
        "email":         "testclient@attorney.ai",
        "password_hash": hash_password("Client@1234"),
        "full_name":     "Test Client",
        "role":          "client",
        "is_active":     True,
    })
    print(f"[seed] client : {CLIENT_ID}")

    await db["cases"].delete_many({"_id": CASE_ID})
    await db["cases"].insert_one({
        "_id":        CASE_ID,
        "client_id":  CLIENT_ID,
        "case_type":  "criminal",
        "province":   "punjab",
        "status":     "open",
        "description": (
            "My landlord physically assaulted me and filed a false FIR. "
            "I need a defense attorney experienced in criminal cases under "
            "PPC and bail petitions in Punjab courts."
        ),
    })
    print(f"[seed] case   : {CASE_ID}")


async def run():
    import httpx

    await connect_db()
    connect_chroma()
    await seed_db()

    admin_token  = create_access_token(ADMIN_ID,  "admin")
    client_token = create_access_token(CLIENT_ID, "client")

    async with httpx.AsyncClient(base_url=BASE, timeout=120) as client:

        # ── 1. Embed all lawyers ───────────────────────────────────────────────
        print("\n=== POST /admin/lawyers/embed-all ===")
        r = await client.post(
            "/admin/lawyers/embed-all",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        print(f"status : {r.status_code}")
        print(f"body   : {json.dumps(r.json(), indent=2)}")

        # ── 2. Match lawyers for case ──────────────────────────────────────────
        print(f"\n=== GET /lawyers/match/{CASE_ID} ===")
        r = await client.get(
            f"/lawyers/match/{CASE_ID}",
            headers={"Authorization": f"Bearer {client_token}"},
        )
        print(f"status : {r.status_code}")
        matches = r.json()
        print(f"body   : {json.dumps(matches, indent=2, default=str)}")

        if isinstance(matches, list) and matches:
            print("\n--- Top match ---")
            top = matches[0]
            print(f"  name        : {top.get('full_name')}")
            print(f"  match_score : {top.get('match_score')}")
            print(f"  match_reason: {top.get('match_reason')}")


if __name__ == "__main__":
    asyncio.run(run())
