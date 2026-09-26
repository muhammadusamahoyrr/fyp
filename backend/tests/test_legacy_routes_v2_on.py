"""The legacy document routes are LEGACY-ONLY once DOCUMENTS_V2 is on.

Decided in docs/v2-activation-evidence/README.md ("Legacy endpoints"). A V2
document is served by /documents/v2/*, whose reviewer sees only the revision
put in front of them. The legacy detail, list and download serve "the current
document", so making them V2-compatible with the flag on would let a reviewer
read a client's newer private draft. They fail closed instead:

  * detail and download of a V2 row → 409 (after the access check);
  * case list and review queue → V2 rows omitted (V2 lists them);
  * legacy submit and review never write a V2 row, flag on OR off — they bind no
    revision, check no staleness and record no receipt.

With the flag OFF the rollback view is unchanged (test_v2_rollback_routes.py).
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col, get_users_col
from app.services import artifact_store as store

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:6]
CLIENT = {"_id": f"lr-client-{TAG}", "role": "client", "is_active": True,
          "email": f"lr-client-{TAG}@test.invalid"}
LAWYER = {"_id": f"lr-lawyer-{TAG}", "role": "lawyer", "is_active": True,
          "email": f"lr-lawyer-{TAG}@test.invalid", "lawyer_profile": {"kyc_verified": True}}
CASE_ID = f"lr-case-{TAG}"
PDF = b"%PDF-1.4 v2 row"


@pytest.fixture
async def rows(mongo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    native, legacy = f"lr-native-{TAG}", f"lr-legacy-{TAG}"
    rev_id = f"lr-rev-{TAG}"
    key = store.write_final(rev_id, 0, PDF)
    try:
        await get_users_col().insert_many([dict(CLIENT), dict(LAWYER)])
        await get_document_revisions_col().insert_one({
            "_id": rev_id, "document_id": native, "version": 1, "status": "generated",
            "artifact_key": key, "pdf_sha256": store.sha256_bytes(PDF),
            "fields": {"notice_body": "x"}, "compliance": {"checked": False},
            "verification": {"ran": True, "counts": {}}})
        await get_documents_col().insert_many([
            # A MIGRATED-looking V2 row: it keeps a legacy status, which is what
            # made the legacy submit guard pass it.
            {"_id": native, "client_id": CLIENT["_id"], "case_id": CASE_ID,
             "template_type": "legal_notice", "title": "V2 notice", "schema_version": 2,
             "status": "generated", "current_revision_id": rev_id, "current_version": 1,
             "review_status": "submitted", "submitted_to": LAWYER["_id"]},
            {"_id": legacy, "client_id": CLIENT["_id"], "case_id": CASE_ID,
             "template_type": "legal_notice", "title": "Legacy notice",
             "status": "generated", "fields": {"notice_body": "y"},
             "review_status": "submitted", "submitted_to": LAWYER["_id"]},
        ])
        yield {"native": native, "legacy": legacy}
    finally:
        await get_document_revisions_col().delete_many({"_id": rev_id})
        await get_documents_col().delete_many({"_id": {"$in": [native, legacy]}})
        await get_users_col().delete_many({"_id": {"$in": [CLIENT["_id"], LAWYER["_id"]]}})


@pytest.fixture
async def http():
    from app.dependencies import get_current_user, require_client, require_lawyer
    from app.main import app

    state = {"user": CLIENT}

    async def _current():
        return state["user"]

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_lawyer] = _current
    app.dependency_overrides[require_client] = _current
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                 base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", True)


# ── flag ON: reads fail closed ───────────────────────────────────────────────

@pytest.mark.parametrize("suffix", ["", "/download"])
async def test_detail_and_download_refuse_a_v2_row(rows, http, flag_on, suffix):
    res = await http.get(f"/documents/{rows['native']}{suffix}")
    assert res.status_code == 409, res.text
    assert b"%PDF" not in res.content


async def test_a_stranger_still_gets_the_access_answer_not_the_409(rows, http, flag_on):
    http.act_as({"_id": "someone-else", "role": "client"})
    res = await http.get(f"/documents/{rows['native']}")
    assert res.status_code == 404        # existence not disclosed


async def test_the_case_list_lists_legacy_rows_only(rows, http, flag_on):
    res = await http.get(f"/documents/case/{CASE_ID}")
    assert res.status_code == 200, res.text      # was a 500: DocumentOut needs `status`
    assert [r["_id"] for r in res.json()] == [rows["legacy"]]


async def test_the_legacy_queue_lists_legacy_rows_only(rows, http, flag_on):
    http.act_as(LAWYER)
    res = await http.get("/documents/review-queue")
    assert res.status_code == 200, res.text
    ids = {r["id"] for r in res.json()}
    assert rows["legacy"] in ids and rows["native"] not in ids


async def test_legacy_rows_are_still_served(rows, http, flag_on):
    res = await http.get(f"/documents/{rows['legacy']}")
    assert res.status_code == 200 and res.json()["title"] == "Legacy notice"


# ── both flag states: legacy writes never touch a V2 row ─────────────────────

@pytest.mark.parametrize("v2_flag", [True, False])
async def test_legacy_review_never_decides_a_v2_row(rows, http, monkeypatch, v2_flag):
    monkeypatch.setattr(settings, "documents_v2", v2_flag)
    http.act_as(LAWYER)
    res = await http.patch(f"/documents/{rows['native']}/review",
                           json={"action": "approve", "note": None})
    assert res.status_code == 409, res.text
    row = await get_documents_col().find_one({"_id": rows["native"]})
    assert row["review_status"] == "submitted", "a V2 row was decided outside V2"


@pytest.mark.parametrize("v2_flag", [True, False])
async def test_legacy_submit_never_submits_a_v2_row(rows, monkeypatch, v2_flag):
    from app.core.exceptions import ConflictError
    from app.services import document_service
    monkeypatch.setattr(settings, "documents_v2", v2_flag)
    await get_documents_col().update_one({"_id": rows["native"]},
                                         {"$set": {"review_status": "none"}})
    with pytest.raises(ConflictError):
        await document_service.submit_for_review(
            rows["native"], CLIENT["_id"], LAWYER["_id"], note=None, urgency="normal")


async def test_legacy_review_still_works_on_a_legacy_row(rows, http, flag_on):
    http.act_as(LAWYER)
    res = await http.patch(f"/documents/{rows['legacy']}/review",
                           json={"action": "approve", "note": None})
    assert res.status_code == 200, res.text
