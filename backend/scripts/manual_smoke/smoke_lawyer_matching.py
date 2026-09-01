"""
End-to-end test for lawyer matching:
  1. Seed test admin, test lawyer, test client, test case into MongoDB
  2. POST /admin/lawyers/embed-all  (admin token)
  3. GET  /lawyers/match/{case_id} (client token)

Seeds the TEST database, never the configured one, and removes everything it
wrote in a `finally`. These fixtures used to go straight into production: this
script is where `test-lawyer-001` came from, one of the two ghost vectors that
suppressed the real candidate pool for 45 of 59 cases. See _smoke_env.py.

The server must be running against the SAME database, or it cannot see the
seed and every assertion below is meaningless (the script checks and says so):

    DB_NAME=attorney_ai_test ./venv/Scripts/uvicorn.exe app.main:app --reload
    ./venv/Scripts/python.exe scripts/manual_smoke/smoke_lawyer_matching.py
"""
import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

# backend/ for `app.*`, and this directory for `_smoke_env`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── bootstrap config + db ──────────────────────────────────────────────────────
from app.core.security import hash_password, create_access_token  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402
from app.db.chroma import connect_chroma  # noqa: E402
from _smoke_env import (  # noqa: E402
    assert_server_shares_database,
    cleanup,
    use_test_database,
)

BASE = "http://localhost:8000/api/v1"

# Fixed IDs so re-runs upsert instead of duplicate-insert
ADMIN_ID  = "test-admin-001"
LAWYER_ID = "test-lawyer-001"
CLIENT_ID = "test-client-001"
CASE_ID   = "test-case-001"


def _throwaway_hash() -> str:
    """A password nobody knows and nothing needs.

    These fixtures never log in -- the script mints tokens directly with
    create_access_token -- so the hash only has to exist. It used to be a
    hardcoded literal, which put a working credential for a production admin
    account into a public repository.
    """
    return hash_password(secrets.token_urlsafe(32))


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
        "password_hash": _throwaway_hash(),
        "full_name":     "Test Admin",
        "role":          "admin",
        "is_active":     True,
    })
    print(f"[seed] admin  : {ADMIN_ID}")

    await _upsert_user(db, {
        "_id":       LAWYER_ID,
        "email":     "testlawyer@attorney.ai",
        "password_hash": _throwaway_hash(),
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
        "password_hash": _throwaway_hash(),
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


async def run(allow_production: bool = False):
    import httpx

    # Must precede connect_db(): get_database() resolves settings.db_name on
    # every call, so the override has to be in place before anything reads it.
    use_test_database(allow_production)

    await connect_db()
    connect_chroma()
    await seed_db()

    admin_token  = create_access_token(ADMIN_ID,  "admin")
    client_token = create_access_token(CLIENT_ID, "client")

    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=120) as client:

            # This script seeds Mongo directly but asserts over HTTP. If the
            # server reads a different database it sees none of the seed, and
            # every result below would be meaningless.
            await assert_server_shares_database(client, admin_token)

            # ── 1. Embed all lawyers ───────────────────────────────────────────
            print("\n=== POST /admin/lawyers/embed-all ===")
            r = await client.post(
                "/admin/lawyers/embed-all",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            print(f"status : {r.status_code}")
            print(f"body   : {json.dumps(r.json(), indent=2)}")

            # ── 2. Match lawyers for case ──────────────────────────────────────
            print(f"\n=== GET /lawyers/match/{CASE_ID} ===")
            r = await client.get(
                f"/lawyers/match/{CASE_ID}",
                headers={"Authorization": f"Bearer {client_token}"},
            )
            print(f"status : {r.status_code}")
            body = r.json()
            print(f"body   : {json.dumps(body, indent=2, default=str)}")

            # /lawyers/match returns {result_kind, notice, matches}. Reading it
            # as a bare list is the pre-2400824 shape and would report "no
            # matches" against the current API however well matching worked.
            if isinstance(body, dict):
                matches = body.get("matches") or []
                print(f"\nresult_kind : {body.get('result_kind')}")
                if body.get("notice"):
                    print(f"notice      : {body['notice']}")
            else:
                matches = body if isinstance(body, list) else []

            if matches:
                print("\n--- Top match ---")
                top = matches[0]
                print(f"  name        : {top.get('full_name')}")
                print(f"  match_score : {top.get('match_score')}")
                print(f"  match_reason: {top.get('match_reason')}")
            else:
                print("\n--- No matches returned ---")
    finally:
        # Always, including after a failed assertion. Leaving the fixture
        # lawyer behind — in Mongo or in the vector store — is the exact
        # failure this script caused before.
        await cleanup([ADMIN_ID, LAWYER_ID, CLIENT_ID], [CASE_ID])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-production", action="store_true",
                    help="seed the configured database instead of the test one")
    asyncio.run(run(ap.parse_args().allow_production))
