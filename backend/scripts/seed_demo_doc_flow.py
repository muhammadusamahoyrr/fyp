"""
Demo data for the Documents flow (2026-10-09): Test Client <-> Test Lawyer.

WHY THIS EXISTS
---------------
The document module is a two-sided flow -- a client drafts and sends, a lawyer
reviews and decides -- and on an empty database neither side shows anything.
This fills both sides of ONE pair of demo accounts with every state the flow
has, so the live demo can walk it without preparing data by hand:

    case "Rent arrears -- Gulberg flat"   (accepted engagement)
      * Legal notice                      submitted, URGENT, with a client note  -> lawyer inbox: Pending
    case "Recovery of loan -- Rs. 850,000" (accepted engagement)
      * Plaint (civil suit)               returned with the lawyer's note        -> client: changes requested
    no case (a case is OPTIONAL)
      * Non-Disclosure Agreement          approved
      * Power of Attorney                 rejected with a reason
      * Legal notice                      a private draft, never sent
    the lawyer's own Vault
      * Plaint (civil suit), standalone   filed in the folder "Rent matters"

Every document is made through the real V2 routes -- create, generate, submit,
review -- so revisions, PDFs, hashes, review cycles and notifications are the
ones the application itself produces. Nothing is written into a document by hand
except the `is_demo_seed: True` marker.

SAFETY
------
* LOCAL ONLY. It loads the same overlay the backend runs with
  (`.env.analyzer-demo.local`) and refuses unless the database is
  `attorney_ai_local` on localhost. The hosted `.env` is never used.
* Every row it adds carries `is_demo_seed: True`; `--remove` deletes exactly
  those rows (and the revisions, folders, notifications and events of those
  documents) and nothing else.
* It refuses to seed twice; `--reset` removes the old demo set first.

USAGE
-----
    cd backend
    ./venv/Scripts/python.exe scripts/seed_demo_doc_flow.py            # seed
    ./venv/Scripts/python.exe scripts/seed_demo_doc_flow.py --reset    # replace
    ./venv/Scripts/python.exe scripts/seed_demo_doc_flow.py --remove   # delete
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
OVERLAY = BACKEND / ".env.analyzer-demo.local"

CLIENT_EMAIL = "testclient@attorney.ai"
LAWYER_EMAIL = "testlawyer@attorney.ai"
CASE_IDS = ("demo-doc-case-rent", "demo-doc-case-loan")
FOLDER_NAME = "Rent matters"


def _load_overlay() -> None:
    from scripts.serve import read_env_overlay
    env = read_env_overlay(OVERLAY)
    host = urlparse(env.get("MONGODB_URL", "")).hostname or ""
    if env.get("DB_NAME") != "attorney_ai_local" or host not in ("localhost", "127.0.0.1"):
        raise SystemExit("REFUSED: the overlay does not point at attorney_ai_local on localhost.")
    os.environ.update(env)


def key() -> str:
    return secrets.token_urlsafe(12)


async def _users():
    from app.db.collections import get_users_col
    users = get_users_col()
    client = await users.find_one({"email": CLIENT_EMAIL})
    lawyer = await users.find_one({"email": LAWYER_EMAIL})
    if not client or not lawyer:
        raise SystemExit(f"REFUSED: {CLIENT_EMAIL} and {LAWYER_EMAIL} must both exist.")
    return ({"_id": client["_id"], "role": "client", "full_name": client.get("full_name", "Test Client")},
            {"_id": lawyer["_id"], "role": "lawyer", "full_name": lawyer.get("full_name", "Test Lawyer")})


async def remove() -> dict:
    from app.db import collections as cols
    db_docs = cols.get_documents_col()
    doc_ids = [d["_id"] async for d in db_docs.find({"is_demo_seed": True}, {"_id": 1})]
    out = {
        "revisions": (await cols.get_document_revisions_col().delete_many(
            {"document_id": {"$in": doc_ids}})).deleted_count,
        "documents": (await db_docs.delete_many({"_id": {"$in": doc_ids}})).deleted_count,
        "deleted_documents": (await cols.get_deleted_documents_col().delete_many(
            {"$or": [{"is_demo_seed": True}, {"_id": {"$in": doc_ids}}]})).deleted_count,
        "folders": (await cols.get_document_folders_col().delete_many({"is_demo_seed": True})).deleted_count,
        "engagements": (await cols.get_engagements_col().delete_many({"is_demo_seed": True})).deleted_count,
        "cases": (await cols.get_cases_col().delete_many({"is_demo_seed": True})).deleted_count,
        "notifications": (await cols.get_notifications_col().delete_many(
            {"payload.doc_id": {"$in": doc_ids}})).deleted_count,
    }
    # Transition bookkeeping keyed by document, where those collections exist.
    db = db_docs.database
    for name in ("event_outbox", "review_events", "document_events"):
        if name in await db.list_collection_names():
            res = await db[name].delete_many({"$or": [{"document_id": {"$in": doc_ids}},
                                                      {"payload.doc_id": {"$in": doc_ids}}]})
            out[name] = res.deleted_count
    return out


async def seed(client: dict, lawyer: dict) -> list[str]:
    import app.api.v1.routes.documents_v2 as v2
    from app.db import collections as cols
    from app.services import document_folders

    now = datetime.now(timezone.utc)
    cid, lid = client["_id"], lawyer["_id"]

    # ── two cases, each with an ACCEPTED engagement (what sharing requires) ──
    cases = [
        {"_id": CASE_IDS[0], "title": "Rent arrears — Gulberg flat", "case_type": "civil",
         "case_number": "DEMO-2026-101", "province": "punjab", "status": "in_progress",
         "description": "Tenant has not paid eight months' rent for a flat in Gulberg III, Lahore. "
                        "Client wants a legal notice first, then a suit if unpaid.",
         "created_at": now - timedelta(days=12)},
        {"_id": CASE_IDS[1], "title": "Recovery of loan — Rs. 850,000", "case_type": "civil",
         "case_number": "DEMO-2026-102", "province": "punjab", "status": "in_progress",
         "description": "A friendly loan given by cheque in 2025 was not returned despite reminders.",
         "created_at": now - timedelta(days=6)},
    ]
    for c in cases:
        await cols.get_cases_col().insert_one({
            **c, "client_id": cid, "lawyer_id": lid, "hearing_dates": [], "milestones": [],
            "tasks": [], "updated_at": now, "is_demo_seed": True})
        await cols.get_engagements_col().insert_one({
            "_id": f"demo-eng-{c['_id']}", "client_id": cid, "lawyer_id": lid, "case_id": c["_id"],
            "status": "accepted", "created_at": c["created_at"], "updated_at": now,
            "accepted_at": c["created_at"] + timedelta(days=1), "is_demo_seed": True})

    made: list[str] = []

    async def doc(user, template, title, fields, case_id=None):
        d = await v2.create_document_v2(v2.CreateBody(template_type=template, title=title, case_id=case_id),
                                        idempotency_key=key(), current_user=user)
        rev = await v2.generate_revision_v2(d["id"], v2.GenerateBody(template_type=template, fields=fields),
                                            idempotency_key=key(), current_user=user)
        made.append(d["id"])
        return d["id"], rev

    async def submit(doc_id, rev, urgency="normal", note=None):
        await v2.submit_document(doc_id, v2.SubmitBody(
            expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
            lawyer_id=lid, urgency=urgency, note=note), idempotency_key=key(), current_user=client)

    async def decide(doc_id, rev, action, note):
        await v2.review_document(doc_id, v2.ReviewBody(
            action=action, expected_version=rev["version"], expected_pdf_sha256=rev["pdf_sha256"],
            note=note), idempotency_key=key(), current_user=lawyer)

    # 1. Case document, waiting for the lawyer: urgent, with the client's note.
    d1, r1 = await doc(client, "legal_notice", "Legal notice — unpaid rent (Gulberg flat)", {
        "sender_name": "Test Client", "sender_address": "House 12, Street 4, Model Town, Lahore",
        "recipient_name": "Mr. Kamran Aslam", "recipient_address": "Flat 3-B, Gulberg III, Lahore",
        "notice_body": "You have occupied the flat as a tenant since March 2025 and have not paid the "
                       "agreed monthly rent of Rs. 65,000 for the last eight months.",
        "demand": "Pay the outstanding rent of Rs. 520,000 in full.",
        "response_days": "15", "date": now.strftime("%d %B %Y")}, case_id=CASE_IDS[0])
    await submit(d1, r1, urgency="urgent", note="The tenant is threatening to leave without paying. "
                                                "Please check the amount and send it out this week.")

    # 2. Case document, returned with the lawyer's note.
    d2, r2 = await doc(client, "plaint_civil", "Plaint — recovery of Rs. 850,000", {
        "court_name": "Court of the Senior Civil Judge, Lahore",
        "plaintiff_name": "Test Client", "plaintiff_address": "House 12, Street 4, Model Town, Lahore",
        "defendant_name": "Mr. Faisal Mehmood", "defendant_address": "Shop 7, Liberty Market, Lahore",
        "facts": "The plaintiff lent the defendant Rs. 850,000 by cheque on 10 January 2025, to be "
                 "returned within six months. Despite repeated requests the amount was not returned.",
        "cause_of_action": "Arose on 10 July 2025 when the repayment fell due, and continues.",
        "relief_sought": "A decree for Rs. 850,000 with costs.",
        "applicable_laws": "Order VII Rule 1 CPC", "date": now.strftime("%d %B %Y")}, case_id=CASE_IDS[1])
    await submit(d2, r2, note="Please review before we file.")
    await decide(d2, r2, "return", "Add the cheque number and bank, and attach the reminders you sent "
                                   "(dates). Then send it back and I will approve it.")

    # 3. No case: approved.
    d3, r3 = await doc(client, "nda", "NDA — software vendor (Lahore)", {
        "party_a": "Test Client", "party_b": "Bytewave Solutions (Pvt) Ltd",
        "purpose": "Discussing a custom inventory system for the client's shop.",
        "duration": "2 years", "jurisdiction": "Lahore, Punjab", "date": now.strftime("%d %B %Y")})
    await submit(d3, r3, note="Standard NDA before sharing our sales data.")
    await decide(d3, r3, "approve", "Fine to sign as it is.")

    # 4. No case: rejected with a reason.
    d4, r4 = await doc(client, "power_of_attorney", "Power of Attorney — property sale (Bahria Town)", {
        "principal_name": "Test Client", "principal_cnic": "35202-0000000-1",
        "principal_address": "House 12, Street 4, Model Town, Lahore",
        "attorney_name": "Mr. Usman Tariq", "attorney_cnic": "35202-0000000-2",
        "attorney_address": "Bahria Town, Lahore", "attorney_relation": "Brother",
        "poa_type": "special", "subject": "Sale of Plot 214, Sector C, Bahria Town, Lahore",
        "powers": "To sign the sale deed and receive the sale price.", "restrictions": "",
        "country_of_execution": "Pakistan", "issue_date": now.strftime("%d %B %Y"), "expiry_date": ""})
    await submit(d4, r4, note="My brother will handle the sale while I am abroad.")
    await decide(d4, r4, "reject", "A sale of immovable property needs a registered power of attorney "
                                   "with the plot's file details. Let us redo it together.")

    # 5. No case: a private draft, never sent.
    await doc(client, "legal_notice", "Legal notice — defective washing machine (draft)", {
        "sender_name": "Test Client", "recipient_name": "Star Electronics, Hall Road, Lahore",
        "demand": "Replace the machine or refund Rs. 145,000.", "response_days": "10"})

    # 6. The lawyer's own Vault: a standalone plaint, filed in a folder.
    d6, _ = await doc(lawyer, "plaint_civil", "Plaint — eviction of tenant (draft for filing)", {
        "court_name": "Court of the Rent Controller, Lahore", "plaintiff_name": "Test Client",
        "defendant_name": "Mr. Kamran Aslam", "relief_sought": "Eviction and arrears of rent.",
        "applicable_laws": "Punjab Rented Premises Act, 2009"})
    folder = await document_folders.create_folder(owner_id=lid, name=FOLDER_NAME)
    await document_folders.move_document(owner_id=lid, document_id=d6, folder_id=folder["id"])
    await cols.get_document_folders_col().update_one({"_id": folder["id"]}, {"$set": {"is_demo_seed": True}})

    await cols.get_documents_col().update_many({"_id": {"$in": made}}, {"$set": {"is_demo_seed": True}})
    return made


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--remove", action="store_true", help="delete the demo set and stop")
    ap.add_argument("--reset", action="store_true", help="delete the demo set, then seed again")
    args = ap.parse_args()

    _load_overlay()
    from app.core.config import settings
    from app.db.mongodb import connect_db
    from app.services import artifact_store as store
    await connect_db()
    # The citation check runs at generation; without Chroma every revision
    # would record "verification unavailable".
    from app.db.chroma import connect_chroma
    connect_chroma()
    store.ensure_dirs()
    if not settings.documents_v2:
        raise SystemExit("REFUSED: DOCUMENTS_V2 is off; the demo needs the V2 document routes.")

    from app.db.collections import get_cases_col
    if args.remove or args.reset:
        print("removed:", await remove())
        if args.remove:
            return 0
    elif await get_cases_col().count_documents({"is_demo_seed": True, "_id": {"$in": list(CASE_IDS)}}):
        raise SystemExit("Already seeded. Use --reset to replace it, or --remove to delete it.")

    client, lawyer = await _users()
    made = await seed(client, lawyer)
    print(f"seeded: 2 cases, 2 accepted engagements, {len(made)} documents, 1 folder "
          f"for {CLIENT_EMAIL} <-> {LAWYER_EMAIL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
